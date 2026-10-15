"""Yo'qolgan yozuvlarni aniqlaydi va nimasi tiklanishi mumkinligini ko'rsatadi.

Faqat o'qiydi — hech narsani o'zgartirmaydi.

    python diag_lost.py
"""
import os

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
django.setup()

from project import storage
from project.helpers import API_BASE_URL
from project.models import Records

qs = Records.objects.filter(status=Records.STATUS_DONE).exclude(audio_key="")

ok_hls, lost, still_there = [], [], []

print("MinIO tekshirilmoqda…")
for record in qs:
    if record.audio_key.endswith(".mp3"):
        if storage.object_exists(record.audio_key):
            still_there.append(record)
        else:
            lost.append(record)
    else:
        ok_hls.append(record)

print()
print("=== Holat ===")
print("  HLS, tayyor           :", len(ok_hls))
print("  .mp3, MinIO'da bor    :", len(still_there), " <-- repackage bilan tiklanadi")
print("  .mp3, MinIO'dan o'chgan:", len(lost), " <-- manba API'ga bog'liq")

if not lost:
    print("\nYo'qolgan yozuv yo'q.")
    raise SystemExit

print()
print("=== O'chganlarini manba API'dan so'rab ko'ramiz ===")
print("(har biri uchun bitta so'rov, biroz vaqt oladi)")

recoverable, gone = [], []
for index, record in enumerate(lost, 1):
    code = record.call_code
    found = False
    for candidate in (code, code.split("_")[0]):
        try:
            response = requests.get(f"{API_BASE_URL}{candidate}", timeout=20)
            if response.status_code == 200 and response.content:
                found = True
                break
        except Exception:
            pass
    (recoverable if found else gone).append(record)
    if index % 25 == 0:
        print(f"  … {index}/{len(lost)}  (tiklanadi: {len(recoverable)})")

print()
print("=== Natija ===")
print("  API'dan qayta yuklanadi :", len(recoverable))
print("  butunlay yo'qolgan      :", len(gone))

if recoverable:
    print("\n  tiklanadigan kodlar (dastlabki 10):")
    for record in recoverable[:10]:
        print("   ", record.call_code)

if gone:
    print("\n  yo'qolgan kodlar (dastlabki 10):")
    for record in gone[:10]:
        print("   ", record.call_code)

print()
print("Keyingi qadam:")
if recoverable:
    print("  1) Tiklanadiganlarni qayta yuklashga qo'yish:")
    print("     python manage.py shell -c \"")
    print("     from project.models import Records")
    print("     codes = %r" % [r.call_code for r in recoverable[:3]] + "  # to'liq ro'yxat quyida")
    print("     Records.objects.filter(call_code__in=codes).update(")
    print("         status='pending', audio_key='', encryption_key='', attempts=0, error='')\"")
if gone:
    print("  2) Yo'qolganlarni 'failed' deb belgilash — ular hech qachon tiklanmaydi.")
