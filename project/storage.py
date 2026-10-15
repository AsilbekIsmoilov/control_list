"""Qo'ng'iroq yozuvlari uchun MinIO qatlami.

Har bir yozuv — bitta fayl emas, papka:

    call-records/9f3ac1d2-.../index.m3u8      playlist
    call-records/9f3ac1d2-.../seg_000.ts      AES-128 bilan shifrlangan bo'lak
    call-records/9f3ac1d2-.../seg_001.ts      …

Papka nomi tasodifiy UUID: `call_code` ketma-ket raqam bo'lgani uchun undan
foydalansak, ombordagi barcha yozuvlarni sanab chiqish mumkin bo'lardi.

Deshifrlash kaliti bu yerda saqlanmaydi — u `Records.encryption_key` da turadi.
Shu sababli MinIO'dan olingan bo'laklarning o'zi hech narsa bermaydi.
"""

import os
import uuid

import urllib3
from django.conf import settings
from minio import Minio
from minio.deleteobjects import DeleteObject

PLAYLIST_NAME = "index.m3u8"

# Playlistdagi kalit havolasi. Paketlash paytida shu nisbiy nom yoziladi,
# uzatishda esa view uni token bilan to'ldiradi.
KEY_URI = "key"


_client = None


def get_client():
    """MinIO klienti (birinchi chaqiruvda yaratiladi).

    Standart klient timeout'siz va 5 marta qayta urinadi — MinIO yetib
    bo'lmaydigan bo'lsa, har bir chaqiruv daqiqalab osilib qoladi va yuzlab
    yozuvli sikl amalda to'xtab qolgandek ko'rinadi. Shuning uchun ulanish
    tez uziladi, o'qish esa yuklash uchun yetarli darajada uzun.
    """
    global _client
    if _client is None:
        _client = Minio(
            f"{settings.MINIO_ENDPOINT}:{settings.MINIO_PORT}",
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_USE_SSL,
            http_client=urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=5, read=60),
                retries=urllib3.Retry(total=2, backoff_factor=0.3),
                maxsize=10,
            ),
        )
    return _client


def ensure_bucket():
    """Bucket yo'q bo'lsa yaratadi (WFM ham boot paytida shuni qiladi)."""
    client = get_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)


def new_audio_dir():
    """Yangi yozuv uchun papka: `call-records/<uuid>` (oxirida `/` yo'q)."""
    return f"{settings.RECORDS_OBJECT_PREFIX}/{uuid.uuid4()}"


def audio_id_from_key(key):
    """`call-records/9f3ac1d2-…` -> `9f3ac1d2-…`

    Frontga aynan shu qiymat boradi — prefiks ham, fayl nomlari ham
    brauzerga umuman ko'rinmaydi.
    """
    if not key:
        return None
    return key.rstrip("/").rsplit("/", 1)[-1]


def key_from_audio_id(audio_id):
    return f"{settings.RECORDS_OBJECT_PREFIX}/{audio_id}"


def playlist_key(audio_dir):
    return f"{audio_dir}/{PLAYLIST_NAME}"


def segment_key(audio_dir, segment):
    return f"{audio_dir}/{segment}"


def stat_object(key):
    return get_client().stat_object(settings.MINIO_BUCKET, key)


def iter_object(key, offset=0, length=0, chunk_size=32 * 1024):
    """MinIO'dan baytlarni bo'lak-bo'lak oqizadi (Range uchun offset/length)."""
    response = get_client().get_object(
        settings.MINIO_BUCKET, key, offset=offset, length=length
    )
    try:
        for chunk in response.stream(chunk_size):
            yield chunk
    finally:
        response.close()
        response.release_conn()


def read_object(key):
    """Kichik obyektni butunligicha o'qiydi (playlist uchun)."""
    response = get_client().get_object(settings.MINIO_BUCKET, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def object_exists(key):
    client = get_client()
    try:
        client.stat_object(settings.MINIO_BUCKET, key)
        return True
    except Exception:
        return False


def audio_exists(audio_dir):
    """Papkada playlist bormi — yozuv to'liq yuklanganining belgisi."""
    return object_exists(playlist_key(audio_dir))


CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
}


def upload_hls_dir(local_dir, audio_dir):
    """Paketlangan HLS papkasini MinIO'ga ko'chiradi.

    `enc.key` va `key.info` ataylab yuklanmaydi — kalit faqat bazada turadi.
    Playlist eng oxirida yuklanadi: uning mavjudligi "yozuv tayyor" degani,
    shuning uchun yarim yuklangan papka hech qachon tayyor ko'rinmaydi.
    """
    ensure_bucket()
    client = get_client()
    uploaded = 0

    segments = sorted(
        name for name in os.listdir(local_dir)
        if name.endswith(".ts")
    )
    for name in segments:
        client.fput_object(
            settings.MINIO_BUCKET, segment_key(audio_dir, name),
            os.path.join(local_dir, name), content_type=CONTENT_TYPES[".ts"],
        )
        uploaded += 1

    client.fput_object(
        settings.MINIO_BUCKET, playlist_key(audio_dir),
        os.path.join(local_dir, PLAYLIST_NAME), content_type=CONTENT_TYPES[".m3u8"],
    )
    return uploaded + 1


def delete_object(key):
    get_client().remove_object(settings.MINIO_BUCKET, key)


def delete_audio_dir(audio_dir):
    """Papkadagi hamma narsani o'chiradi."""
    client = get_client()
    names = [
        obj.object_name
        for obj in client.list_objects(
            settings.MINIO_BUCKET, prefix=f"{audio_dir}/", recursive=True
        )
    ]
    if not names:
        return 0
    errors = list(client.remove_objects(
        settings.MINIO_BUCKET, (DeleteObject(name) for name in names)
    ))
    return len(names) - len(errors)


def delete_all_record_objects():
    """Prefiks ostidagi barcha yozuvlarni o'chiradi (oy almashganda)."""
    client = get_client()
    prefix = f"{settings.RECORDS_OBJECT_PREFIX}/"
    names = [
        obj.object_name
        for obj in client.list_objects(settings.MINIO_BUCKET, prefix=prefix, recursive=True)
    ]
    if not names:
        return 0

    errors = list(
        client.remove_objects(
            settings.MINIO_BUCKET, (DeleteObject(name) for name in names)
        )
    )
    for error in errors:
        print(f"MinIO delete error: {error.object_name} | {error.message}")

    return len(names) - len(errors)
