import os
import requests
import shutil
import subprocess
import tempfile
import zipfile
from django.conf import settings
from django.core.files.base import File
from django.db.models import Q
from . import storage
from .models import CALL_CODE_RE, CallData, Records
from io import BytesIO
from django.utils.timezone import now, timedelta
from dotenv import load_dotenv

# Bo'sh chaqiruv joriy katalogdan yuqoriga qidiradi; systemd ostida u
# loyiha katalogi emas.
load_dotenv(settings.BASE_DIR / ".env")

def searchable_operators():
    """Operators offered by the search dropdown.

    Not just the active ones: a full sync deactivates everybody missing from
    the current month's sheet, and that would hide their archive as well —
    the operator page itself looks operators up by name without checking
    `is_active`, so the data stays readable, only unreachable. Anyone who
    still has an archived month is therefore kept in the list.
    """
    return (
        CallData.objects
        .filter(Q(is_active=True) | Q(scores_for_month__isnull=False))
        .exclude(is_excluded=True)
        .distinct()
        .order_by("name")
    )


def get_operator_from_request(request):
    name_from_url = request.GET.get("operator-name")
    if name_from_url:
        request.session["selected_operator"] = name_from_url
        return name_from_url
    return request.session.get("selected_operator")




API_BASE_URL = os.getenv("API_BASE_URL")

# Systemd birligi PATH'ni venv bilan almashtiradi
# (`Environment="PATH=…/venv/bin"`), ya'ni `/usr/bin` ko'rinmaydi va oddiy
# "ffmpeg" topilmaydi. Buni har deployda .env ga yozib qo'yish o'rniga
# odatiy joylarni o'zimiz ko'ramiz; .env dagi qiymat baribir ustun turadi.
FFMPEG_FALLBACKS = (
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/snap/bin/ffmpeg",
)


def _find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for path in FFMPEG_FALLBACKS:
        if os.path.exists(path):
            return path
    return "ffmpeg"


FFMPEG_PATH = os.getenv("FFMPEG_PATH") or _find_ffmpeg()

# .spx va .mp3 ikkalasi ham shu yerda vaqtincha turadi — mp3 MinIO'ga
# yuklangach darhol o'chiriladi, diskda doimiy nusxa qolmaydi.
TEMP_DIR = os.path.join(settings.BASE_DIR, "temp_audio")

os.makedirs(TEMP_DIR, exist_ok=True)

# Muvaffaqiyatsiz call_code'ni cheksiz qayta urinmaslik uchun.
MAX_DOWNLOAD_ATTEMPTS = 3


def download_file(url):
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response
    except Exception as e:
        print(f"Download error: {url} | {e}")
    return None


def save_spx_from_zip(zip_content, call_code):
    try:
        base_code = call_code.split("_")[0]

        with zipfile.ZipFile(BytesIO(zip_content)) as archive:
            spx_files = [f for f in archive.namelist() if f.endswith(".spx")]

            if not spx_files:
                print(f"No SPX inside ZIP: {call_code}")
                return None

            for filename in spx_files:
                if call_code in filename:
                    return extract_spx(archive, filename, call_code)

            for filename in spx_files:
                if base_code in filename:
                    return extract_spx(archive, filename, call_code)

        print(f"SPX not matched inside ZIP: {call_code}")
        return None

    except zipfile.BadZipFile:
        print(f"Invalid ZIP file: {call_code}")
        return None


def extract_spx(archive, filename, call_code):
    spx_path = os.path.join(TEMP_DIR, f"{call_code}.spx")

    with archive.open(filename) as src, open(spx_path, "wb") as dst:
        dst.write(src.read())

    print(f"Extracted SPX: {filename}")
    return spx_path


HLS_SEGMENT_SECONDS = 6


def make_work_dir():
    """Paketlash uchun vaqtinchalik papka.

    Odatda `temp_audio/` ichida. Lekin u Celery foydalanuvchisi (www-data)
    egaligida bo'ladi, ya'ni buyruqni boshqa foydalanuvchidan ishlatganda
    yozib bo'lmaydi — bunday holatda tizim temp papkasiga tushamiz.
    """
    try:
        return tempfile.mkdtemp(dir=TEMP_DIR)
    except (PermissionError, OSError):
        path = tempfile.mkdtemp(prefix="call-audio-")
        print(f"{TEMP_DIR} ga yozib bo'lmadi, {path} ishlatilmoqda")
        return path


def ffmpeg_available():
    """ffmpeg chaqirib bo'ladimi — run boshida bir marta tekshiriladi."""
    try:
        subprocess.run(
            [FFMPEG_PATH, "-version"], capture_output=True, timeout=10, check=True
        )
        return True
    except Exception:
        return False


def package_hls(source_path, out_dir, extra_input_args=()):
    """Audioni AES-128 bilan shifrlangan HLS bo'laklariga paketlaydi.

    `out_dir` ichida `index.m3u8` va `seg_NNN.ts` hosil bo'ladi. Kalit fayli
    ffmpeg ishlatib bo'lgach o'chiriladi va faqat hex ko'rinishida qaytariladi
    — u MinIO'ga hech qachon tushmasligi kerak.

    Kodek AAC-LC, 44.1 kHz: manba 8 kHz mp3 bo'lsa ham shu ko'rinishga
    keltiriladi. Sababi — 8 kHz mp3 (MPEG-2.5 Layer III) ni brauzer oddiy
    `<audio src>` da o'ynaydi, lekin Media Source Extensions qabul qilmaydi
    va hls.js `bufferAppendError` beradi. AAC esa HLS uchun standart kodek.
    """
    key_path = os.path.join(out_dir, "enc.key")
    info_path = os.path.join(out_dir, "key.info")

    key = os.urandom(16)
    with open(key_path, "wb") as f:
        f.write(key)
    with open(info_path, "w") as f:
        f.write(f"{storage.KEY_URI}\n{key_path}\n{os.urandom(16).hex()}\n")

    command = [
        FFMPEG_PATH, "-y", *extra_input_args, "-i", source_path,
        "-c:a", "aac", "-b:a", "24k", "-ac", "1", "-ar", "44100",
        "-f", "hls",
        "-hls_time", str(HLS_SEGMENT_SECONDS),
        "-hls_playlist_type", "vod",
        "-hls_key_info_file", info_path,
        "-hls_segment_filename", "seg_%03d.ts",
        storage.PLAYLIST_NAME,
    ]
    # cwd = out_dir: playlistga nisbiy nomlar yozilsin (absolyut yo'l emas).
    result = subprocess.run(command, cwd=out_dir, capture_output=True, text=True)

    for path in (key_path, info_path):
        if os.path.exists(path):
            os.remove(path)

    playlist = os.path.join(out_dir, storage.PLAYLIST_NAME)
    if result.returncode != 0 or not os.path.exists(playlist):
        print("FFmpeg HLS error:")
        print(result.stderr)
        return None

    return key.hex()


def _mark_failed(record, reason, permanent=True):
    """Xatoni yozadi.

    permanent=True  — manbada yozuv yo'q yoki buzuq. `attempts` oshadi va
                      MAX_DOWNLOAD_ATTEMPTS dan keyin bu kod tashlab ketiladi.
    permanent=False — infratuzilma nosozligi (MinIO o'chgan, tarmoq uzilgan).
                      Yozuv aybdor emas, shuning uchun `attempts` oshmaydi va
                      status `pending` bo'lib qoladi — keyingi runda qayta uriniladi.
    """
    record.error = reason
    if permanent:
        record.status = Records.STATUS_FAILED
        record.attempts += 1
        print(f"{reason}: {record.call_code} (urinish {record.attempts})")
    else:
        record.status = Records.STATUS_PENDING
        print(f"{reason}: {record.call_code} (vaqtinchalik, urinish sanalmadi)")
    record.save(update_fields=["status", "error", "attempts"])


def _mark_done(record, audio_dir, encryption_key):
    record.audio_key = audio_dir
    record.encryption_key = encryption_key
    record.status = Records.STATUS_DONE
    record.error = ""
    record.save(update_fields=["audio_key", "encryption_key", "status", "error"])


def extract_and_download_records():
    """Kommentlardagi call_code'larni yig'ib, audioni MinIO'ga yuklaydi.

    Fayl API'dan .spx bo'lib keladi (to'g'ridan-to'g'ri yoki ZIP ichida),
    ffmpeg bilan shifrlangan HLS bo'laklariga paketlanadi va MinIO'ga qo'yiladi.
    Diskda doimiy nusxa qolmaydi; deshifrlash kaliti esa faqat bazada saqlanadi.
    """

    # Ikkala tashqi bog'liqlikni run boshida bir marta tekshiramiz. Aks holda
    # har bir yozuv alohida yiqilib, o'nlab daqiqa behuda ketardi va sabab
    # yuzlab satr ichida ko'rinmay qolardi.
    if not ffmpeg_available():
        print(
            f"ffmpeg ishga tushmadi ({FFMPEG_PATH}) — audio yuklash o'tkazib "
            "yuborildi. PATH va " + ", ".join(FFMPEG_FALLBACKS) + " tekshirildi. "
            "O'rnatilgan bo'lsa .env ga FFMPEG_PATH=<`which ffmpeg` natijasi> qo'ying."
        )
        return {"skipped": "ffmpeg_unavailable"}

    try:
        storage.ensure_bucket()
    except Exception as e:
        print(f"MinIO ishlamayapti, audio yuklash o'tkazib yuborildi: {e}")
        return {"skipped": "minio_unavailable"}

    # Avval kommentlardan yangi kodlarni yig'amiz, keyin yuklashni yozuvlar
    # jadvali bo'yicha yuritamiz. Ilgari ikkalasi bitta siklda edi va bu
    # jimgina yo'qotishga olib kelardi: operator nofaol bo'lib qolsa (yoki
    # o'chirilsa) uning pending yozuvi hech qachon qayta urinib ko'rilmasdi.
    for cd in CallData.objects.filter(is_active=True):
        for i in range(1, 11):
            match = CALL_CODE_RE.search(getattr(cd, f"comment{i}", "") or "")
            if not match:
                continue
            _, created = Records.objects.get_or_create(
                call_code=match.group(1), defaults={"operator": cd}
            )
            if created:
                print(f"New record created: {match.group(1)}")

    exhausted = Records.objects.filter(
        status=Records.STATUS_PENDING, attempts__gte=MAX_DOWNLOAD_ATTEMPTS
    ).count()
    if exhausted:
        print(
            f"{exhausted} ta yozuv urinishlarini sarflagan — "
            "`manage.py reset_records --pending --yes` bilan tiklanadi"
        )

    pending = list(
        Records.objects.filter(
            status=Records.STATUS_PENDING, attempts__lt=MAX_DOWNLOAD_ATTEMPTS
        ).order_by("pk")
    )
    print(f"Yuklanadigan yozuv: {len(pending)}")

    for record in pending:
        call_code = record.call_code

        # Papka nomi tasodifiy, ya'ni call_code'dan hisoblab bo'lmaydi.
        # Shuning uchun avval yozuvda saqlangani tekshiriladi — MinIO'da
        # papka joyida bo'lsa (DB qisman tiklangan holat) qayta yuklamaymiz.
        # Kalit ham saqlanib turgan bo'lishi shart, aks holda foydasiz.
        if (
            record.audio_key
            and record.encryption_key
            and storage.audio_exists(record.audio_key)
        ):
            _mark_done(record, record.audio_key, record.encryption_key)
            print(f"Already in MinIO: {call_code}")
            continue

        audio_dir = storage.new_audio_dir()

        spx_path = None

        direct_url = f"{API_BASE_URL}{call_code}"
        response = download_file(direct_url)

        if response and "application/zip" not in response.headers.get("content-type", ""):
            spx_path = os.path.join(TEMP_DIR, f"{call_code}.spx")
            with open(spx_path, "wb") as f:
                f.write(response.content)

            print(f"Direct SPX downloaded: {call_code}")

        else:
            base_code = call_code.split("_")[0]
            zip_url = f"{API_BASE_URL}{base_code}"
            response = download_file(zip_url)

            if not response:
                _mark_failed(record, "File not found")
                continue

            spx_path = save_spx_from_zip(response.content, call_code)

            if not spx_path:
                _mark_failed(record, "SPX not found in ZIP")
                continue

        work_dir = make_work_dir()
        try:
            encryption_key = package_hls(spx_path, work_dir)

            if os.path.exists(spx_path):
                os.remove(spx_path)

            if not encryption_key:
                _mark_failed(record, "FFmpeg HLS packaging failed")
                continue

            try:
                parts = storage.upload_hls_dir(work_dir, audio_dir)
            except Exception as e:
                # Infratuzilma nosozligi — yozuvni "yo'q" deb belgilamaymiz.
                _mark_failed(record, f"MinIO upload failed: {e}", permanent=False)
                continue
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

        _mark_done(record, audio_dir, encryption_key)

        print(f"Uploaded to MinIO: {call_code} ({parts} ta obyekt)")



# Yozuvlar hech qachon o'chirilmaydi: arxivga o'tgan komment ham 2-3 oydan keyin
# eshitilishi kerak. Manba API eski qo'ng'iroqlarni bermaydi, ya'ni o'chirilgan
# audioni tiklab bo'lmaydi — shu sababli avvalgi "oy almashsa hammasini o'chir"
# logikasi (delete_all_records / delete_records_if_month_changed) olib tashlandi.

