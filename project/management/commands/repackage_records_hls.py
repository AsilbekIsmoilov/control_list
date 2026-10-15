"""Yozuvlarni shifrlangan AAC/HLS ko'rinishiga keltiradi.

Ikkita manba shaklini biladi:

    call-records/<uuid>.mp3            eski, bitta fayl
    call-records/<uuid>/index.m3u8     HLS, lekin ichida mp3 (--force bilan)

Ikkalasi ham quyidagiga aylanadi:

    call-records/<uuid>/index.m3u8     AAC-LC 44.1 kHz
    call-records/<uuid>/seg_NNN.ts     AES-128

`audio_id` (UUID) o'zgarmaydi — u WFM Mongo'sida `comments[].audio_id` sifatida
yotibdi, o'zgartirsak barcha havolalar uzilardi.

    python manage.py repackage_records_hls --dry-run
    python manage.py repackage_records_hls
    python manage.py repackage_records_hls --force   # mp3-ichidagi HLS'ni ham
"""

import os
import shutil

from django.core.management.base import BaseCommand

from project import storage
from project.helpers import make_work_dir, package_hls
from project.models import Records


class Command(BaseCommand):
    help = "Yozuvlarni shifrlangan AAC/HLS ga o'tkazadi"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--force", action="store_true",
            help="Allaqachon HLS bo'lganlarni ham qayta kodlaydi (mp3 -> AAC)",
        )

    # --- manbani vaqtinchalik papkaga tushirish -------------------------

    def _fetch_mp3(self, key, work_dir):
        path = os.path.join(work_dir, "source.mp3")
        with open(path, "wb") as f:
            for chunk in storage.iter_object(key):
                f.write(chunk)
        return path, ()

    def _fetch_hls(self, audio_dir, encryption_key, work_dir):
        """Mavjud HLS'ni lokal playlistga yig'adi, kalitni fayl qilib qo'yadi.

        Manba alohida `src/` papkasiga tushadi: ffmpeg chiqishi ham `seg_NNN.ts`
        deb nomlanadi va bitta papkada bo'lsa manbani o'chirib yuborardi.
        """
        src_dir = os.path.join(work_dir, "src")
        os.makedirs(src_dir, exist_ok=True)

        raw = storage.read_object(storage.playlist_key(audio_dir)).decode()

        with open(os.path.join(src_dir, "source.key"), "wb") as f:
            f.write(bytes.fromhex(encryption_key))

        lines = []
        for line in raw.splitlines():
            if line.startswith("#EXT-X-KEY"):
                line = line.replace(f'URI="{storage.KEY_URI}"', 'URI="source.key"')
            elif line.startswith("seg_"):
                with open(os.path.join(src_dir, line), "wb") as f:
                    for chunk in storage.iter_object(storage.segment_key(audio_dir, line)):
                        f.write(chunk)
            lines.append(line)

        path = os.path.join(src_dir, "source.m3u8")
        with open(path, "w") as f:
            f.write("\n".join(lines))
        # Lokal playlistdagi .key/.ts fayllarini o'qish uchun kerak.
        return path, ("-allowed_extensions", "ALL")

    # --- asosiy oqim -----------------------------------------------------

    def handle(self, *args, **options):
        dry_run, force = options["dry_run"], options["force"]
        done = skipped = failed = 0

        for record in Records.objects.filter(status=Records.STATUS_DONE).exclude(audio_key=""):
            old_key = record.audio_key
            is_mp3 = old_key.endswith(".mp3")

            if not is_mp3 and not force:
                skipped += 1
                continue
            if not is_mp3 and not record.encryption_key:
                self.stderr.write(f"kalitsiz HLS, o'tkazib yuborildi: {old_key}")
                skipped += 1
                continue

            audio_id = old_key.rsplit("/", 1)[-1][:-4] if is_mp3 else storage.audio_id_from_key(old_key)
            audio_dir = storage.key_from_audio_id(audio_id)

            if dry_run:
                self.stdout.write(f"{old_key} -> {audio_dir}/index.m3u8 (AAC)")
                done += 1
                continue

            work_dir = make_work_dir()
            try:
                if is_mp3:
                    source, input_args = self._fetch_mp3(old_key, work_dir)
                else:
                    source, input_args = self._fetch_hls(
                        audio_dir, record.encryption_key, work_dir
                    )

                encryption_key = package_hls(source, work_dir, input_args)
                if not encryption_key:
                    self.stderr.write(f"paketlash xatosi: {old_key}")
                    failed += 1
                    continue

                # Eski bo'laklar soni yangisidan ko'p bo'lishi mumkin —
                # papkani avval tozalaymiz, yetim `seg_NNN.ts` qolmasin.
                storage.delete_audio_dir(audio_dir)
                storage.upload_hls_dir(work_dir, audio_dir)
            except Exception as e:
                self.stderr.write(f"xato {old_key}: {e}")
                failed += 1
                continue
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

            record.audio_key = audio_dir
            record.encryption_key = encryption_key
            record.save(update_fields=["audio_key", "encryption_key"])

            if is_mp3:
                try:
                    storage.delete_object(old_key)
                except Exception as e:
                    self.stderr.write(f"eski mp3 o'chmadi {old_key}: {e}")

            done += 1

        self.stdout.write(self.style.SUCCESS(
            f"paketlandi: {done} | o'tkazib yuborildi: {skipped} | xato: {failed}"
            + (" (dry-run)" if dry_run else "")
        ))

        if done and not dry_run:
            # Har paketlashda yangi AES kaliti yaraladi. WFM'dagi eski kalit
            # bilan bo'laklar ochilmaydi va audio jimgina buziladi.
            self.stdout.write(self.style.WARNING(
                "\nKalitlar o'zgardi — WFM'ga uzatish SHART:\n"
                "  python manage.py shell -c \""
                "from project.wfm_sync import push_audio_keys_to_wfm; "
                "print(push_audio_keys_to_wfm())\""
            ))
