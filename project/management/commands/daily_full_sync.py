from django.core.management.base import BaseCommand

from project.helpers import extract_and_download_records
from project.sheets import update_call_data


class Command(BaseCommand):
    help = "Kunlik to'liq sync: CallData, rasmlar va records."

    def handle(self, *args, **options):
        updated_count = update_call_data()
        extract_and_download_records()
        self.stdout.write(
            self.style.SUCCESS(
                f"Kunlik sync tugadi: {updated_count} ta faol CallData yangilandi."
            )
        )