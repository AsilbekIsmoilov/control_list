from django.core.management.base import BaseCommand, CommandError

import gspread

from project.sheets import CREDENTIALS, update_call_data


SPREADSHEET_NAME = "СВОД"
SOURCE_WORKSHEET_NAME = "WEB UCHUN"
QUEUE_WORKSHEET_NAME = "SYNC_QUEUE"


class Command(BaseCommand):
    help = "SYNC_QUEUE dagi o'zgargan WEB UCHUN qatorlarini CallData'ga sync qiladi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-queue",
            action="store_true",
            help="Muvaffaqiyatli syncdan keyin ham queue qatorlarini o'chirmaydi.",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Queue bo'sh bo'lsa log yozmaydi.",
        )

    def handle(self, *args, **options):
        client = gspread.authorize(CREDENTIALS)

        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
            queue = spreadsheet.worksheet(QUEUE_WORKSHEET_NAME)
        except gspread.WorksheetNotFound as exc:
            raise CommandError(
                f"{QUEUE_WORKSHEET_NAME} varag'i topilmadi."
            ) from exc
        except gspread.SpreadsheetNotFound as exc:
            raise CommandError(
                f"{SPREADSHEET_NAME} spreadsheet topilmadi."
            ) from exc

        queue_rows = queue.get_all_values()
        if len(queue_rows) <= 1:
            if not options["quiet"]:
                self.stdout.write("SYNC_QUEUE bo'sh.")
            return

        source_rows = []
        processed_queue_rows = []
        invalid_count = 0

        # Birinchi qator header. Queue ichidagi real Google Sheets row raqami
        # 2 dan boshlanadi.
        for queue_row_number, values in enumerate(queue_rows[1:], start=2):
            sheet_name = values[0].strip() if len(values) > 0 else ""
            source_row_raw = values[1].strip() if len(values) > 1 else ""

            if sheet_name != SOURCE_WORKSHEET_NAME:
                continue

            try:
                source_row = int(source_row_raw)
            except (TypeError, ValueError):
                invalid_count += 1
                continue

            if source_row < 2:
                invalid_count += 1
                continue

            source_rows.append(source_row)
            processed_queue_rows.append(queue_row_number)

        unique_source_rows = sorted(set(source_rows))
        if not unique_source_rows:
            self.stdout.write(
                self.style.WARNING(
                    f"Yangilanadigan qator topilmadi. Noto'g'ri queue yozuvlari: {invalid_count}."
                )
            )
            return

        try:
            updated_count = update_call_data(row_numbers=unique_source_rows, sync_photos=False)
        except Exception as exc:
            # Muhim: sync xato bo'lsa queue o'chirilmaydi va keyingi ishga
            # tushishda qayta uriniladi.
            raise CommandError(f"CallData sync bajarilmadi: {exc}") from exc

        if updated_count == 0:
            raise CommandError(
                "Sheets qatori CallData'ga yozilmadi; queue keyingi urinish uchun saqlandi."
            )  

        if not options["keep_queue"]:
            for queue_row_number in sorted(processed_queue_rows, reverse=True):
                queue.delete_rows(queue_row_number)

        queue_status = "saqlandi" if options["keep_queue"] else "o'chirildi"
        self.stdout.write(
            self.style.SUCCESS(
                f"Sync tugadi: {len(unique_source_rows)} ta Sheets qatori, "
                f"{updated_count} ta CallData yangilandi, "
                f"{len(processed_queue_rows)} ta queue yozuvi {queue_status}."
            )
        )