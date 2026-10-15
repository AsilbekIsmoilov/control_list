"""Audio zanjirini tekshirish: Records -> serializer -> audio_id.

    python diag_audio.py
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
django.setup()

from project import storage
from project.models import CALL_CODE_RE, CallData, Records
from project.serializers import CallDataSerializer

qs = Records.objects.filter(status=Records.STATUS_DONE)

print("=== 1. Records jadvali ===")
print("  done               :", qs.count())
print("  audio_key bor      :", qs.exclude(audio_key="").count())
print("  encryption_key bor :", qs.exclude(encryption_key="").count())
ready = qs.exclude(audio_key="").exclude(encryption_key="")
print("  ikkalasi ham bor   :", ready.count(), "  <-- serializer shularni oladi")

sample = qs.exclude(audio_key="").first()
if sample:
    print(f"  namuna: call_code      = {sample.call_code}")
    print(f"          audio_key      = {sample.audio_key}")
    print(f"          kalit uzunligi = {len(sample.encryption_key or '')}")
    print(f"          audio_id       = {storage.audio_id_from_key(sample.audio_key)}")

print()
print("=== 2. Serializer xaritasi ===")
serializer = CallDataSerializer(CallData.objects.filter(is_active=True)[:1], many=True)
mapping = serializer.child.audio_ids
print("  {call_code: audio_id} yozuvlari:", len(mapping))
for key, value in list(mapping.items())[:2]:
    print(f"    {key} -> {value}")

print()
print("=== 3. Serializer chiqishi ===")
operator = CallData.objects.filter(is_active=True, comment1__gt="").first()
if operator:
    data = CallDataSerializer(operator).data
    print("  operator      :", data["name"])
    print("  total_comments:", data["total_comments"])
    for comment in data["comments"][:3]:
        print(f"    call_code={comment['call_code']}  audio_id={comment['audio_id']}")
else:
    print("  kommentli faol operator topilmadi")

print()
print("=== 4. Kod mosligi ===")
comment_codes = set()
for operator in CallData.objects.filter(is_active=True):
    for index in range(1, 11):
        match = CALL_CODE_RE.search(getattr(operator, f"comment{index}", "") or "")
        if match:
            comment_codes.add(match.group(1))

record_codes = set(ready.values_list("call_code", flat=True))
print("  kommentlardagi kodlar :", len(comment_codes))
print("  tayyor Records kodlari:", len(record_codes))
print("  mos kelgan            :", len(comment_codes & record_codes))
missing = comment_codes - record_codes
if missing:
    print("  Records da yo'q       :", sorted(missing)[:5])

print()
print("=== 5. Fayl versiyalari ===")
import inspect

from project import serializers as serializers_module

src = inspect.getsource(serializers_module)
print("  serializers.py da 'audio_id'      :", "bor" if "audio_id" in src else "YO'Q — eski fayl!")
print("  serializers.py da 'encryption_key':", "bor" if "encryption_key" in src else "YO'Q — eski fayl!")
