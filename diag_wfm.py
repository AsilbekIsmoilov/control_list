"""WFM Mongo'sidagi operator_call_data holatini sync endpointi orqali ko'radi.

WFM serveriga kirish shart emas — Django'dagi sync tokeni yetarli.

    python diag_wfm.py
"""
import os
from collections import Counter

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
django.setup()

from django.conf import settings

from project.models import CallData

base = settings.WFM_SYNC_BASE_URL.rstrip("/")
print("WFM:", base)
print()

# --- Django tomoni ---------------------------------------------------
active = CallData.objects.filter(is_active=True)
print("=== Django ===")
print("  is_active=True        :", active.count())
print("  operator_code bo'sh   :", active.filter(operator_code__isnull=True).count()
      + active.filter(operator_code="").count())
print("  unikal operator_code  :",
      active.exclude(operator_code__isnull=True).exclude(operator_code="")
      .values("operator_code").distinct().count())

# --- WFM tomoni ------------------------------------------------------
print()
print("=== WFM Mongo (sync/changes orqali) ===")
try:
    response = requests.get(
        f"{base}/changes",
        params={
            "entities": "operator-call-data",
            "since": "1970-01-01T00:00:00.000Z",
            "limit": 5000,
        },
        # /changes Control List tokenini emas, HOUR_BY_PROJECT_SYNC_TOKEN ni
        # kutadi. Uni WFM jamoasidan olib, .env ga WFM_CHANGES_TOKEN qilib
        # qo'ying — bo'lmasa oddiy sync tokeni bilan urinib ko'ramiz.
        headers={"x-sync-token": os.getenv("WFM_CHANGES_TOKEN") or settings.WFM_SYNC_TOKEN},
        timeout=settings.WFM_SYNC_TIMEOUT,
    )
except Exception as e:
    raise SystemExit(f"  ulanmadi: {type(e).__name__} {e}")

if response.status_code == 401:
    raise SystemExit(
        "  401 — bu endpoint boshqa tokenni kutadi (HOUR_BY_PROJECT_SYNC_TOKEN).\n"
        "  WFM jamoasidan o'sha tokenni so'rang yoki ular quyidagini bajarsin:\n"
        "    mongosh wfm --eval 'db.operator_call_data.countDocuments()'"
    )
if not response.ok:
    raise SystemExit(f"  HTTP {response.status_code}: {response.text[:200]}")

body = response.json()
# WFM javobni {data: …} konvertiga o'raydi, getChanges esa o'zi ham
# {since, limit, entities, data: {...}} qaytaradi — ya'ni ikki qavat.
payload = body.get("data", body)
rows = payload.get("data", {}).get("operator-call-data", [])

print("  hujjatlar             :", len(rows))
if not rows:
    raise SystemExit("  bo'sh — yozuvlar Mongo'ga tushmagan")

with_user = [r for r in rows if r.get("user_id")]
print("  user_id bor           :", len(with_user), "  <-- control list shularni oladi")
print("  user_id yo'q          :", len(rows) - len(with_user))
print("  UNIKAL user_id        :", len({str(r["user_id"]) for r in with_user}),
      "  <-- control list AYNAN shuncha qator qaytaradi")
print("  unikal operator_code  :", len({r.get("operator_code") for r in rows}))

dup = [(u, n) for u, n in Counter(str(r["user_id"]) for r in with_user).items() if n > 1]
if dup:
    print()
    print(f"  bir user_id bir necha operatorda: {len(dup)} holat")
    for user_id, count in sorted(dup, key=lambda x: -x[1])[:5]:
        names = [r.get("operator_name") for r in with_user if str(r["user_id"]) == user_id][:3]
        print(f"    {user_id}: {count} ta — {names}")
