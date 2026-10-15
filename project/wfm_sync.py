import re
import requests
from django.conf import settings

from project.models import CallData, Records, ScoresForMonth
from project.serializers import CallDataSerializer, ScoresForMonthSerializer


WFM_FIELDS = [
    "operator_code", "operator_name", "group", "bl", "mark", "month",
    "total_call_datas", "total_comments", "code_data", "call_data",
    "service_data", "greeting", "hearing", "question", "interest", "cons",
    "polite", "speech", "note", "warning", "emotion", "solution",
    "dialog", "mis", "comments",
]


# WFM `mis` ni nomlangan obyekt sifatida kutadi va massivni ataylab rad etadi
# (`misData`: `!Array.isArray(value)`), ya'ni [1, null, null] yuborilsa hamma
# qiymat null bo'lib qoladi. Ochiq API'da shakl massivligicha qolsin — bu yerda,
# faqat WFM uchun, o'giramiz.
_MIS_LABELS = ("Ошибка -25", "Ошибка -10", "Ошибка -2")


def _wfm_record(serialized):
    source = dict(serialized)
    name = source.get("name") or ""
    source["operator_name"] = re.sub(r"\s*\(\d+\).*$", "", name).strip()

    mis = source.get("mis")
    if isinstance(mis, (list, tuple)):
        source["mis"] = dict(zip(_MIS_LABELS, list(mis) + [None] * len(_MIS_LABELS)))

    return {field: source.get(field) for field in WFM_FIELDS}


def _config():
    base_url = settings.WFM_SYNC_BASE_URL.rstrip("/")
    token = settings.WFM_SYNC_TOKEN
    if not base_url:
        raise RuntimeError("WFM_SYNC_BASE_URL sozlanmagan")
    if not token:
        raise RuntimeError("WFM_SYNC_TOKEN sozlanmagan")
    return base_url, {"x-sync-token": token, "content-type": "application/json"}


def _post(path, payload):
    base_url, headers = _config()
    response = requests.post(
        f"{base_url}/{path.lstrip('/')}", json=payload, headers=headers,
        timeout=settings.WFM_SYNC_TIMEOUT,
    )
    response.raise_for_status()
    body = response.json()
    data = body.get("data", body)
    if data.get("error"):
        raise RuntimeError(f"WFM sync xatosi: {data['error']}")
    return data


def push_current_to_wfm(operator_ids=None, reconcile=False):
    # `is_excluded` — qo'lda belgilangan operator. Uzatilmaydi, va `reconcile`
    # ro'yxatga tushmagani uchun WFM'dagi nusxasini ham o'chiradi.
    queryset = (
        CallData.objects.filter(is_active=True)
        .exclude(is_excluded=True)
        .order_by("pk")
    )
    if operator_ids is not None:
        queryset = queryset.filter(pk__in=operator_ids)
    records = []
    for serialized in CallDataSerializer(queryset, many=True).data:
        item = _wfm_record(serialized)
        item["external_id"] = serialized["id"]  # internal sync key; GET'da yashiriladi
        records.append(item)
    result = _post("ingest/operator-call-data", records) if records else {"received": 0, "upserted": 0}
    if reconcile and records:
        result["reconcile"] = _post(
            "reconcile/operator-call-data",
            {"all": True, "external_ids": [item["external_id"] for item in records]},
        )
    return result


def push_audio_keys_to_wfm():
    """Deshifrlash kalitlarini WFM'ga uzatadi.

    Kalitlar ataylab alohida entity: `comments` ichida yuborilsa, control list
    javobi bilan birga frontga chiqib ketardi. WFM ularni `call_audio_keys`
    kolleksiyasida saqlaydi va faqat key endpointi o'qiydi.
    """
    records = [
        {
            "external_id": pk,
            "audio_id": audio_key.rstrip("/").rsplit("/", 1)[-1],
            "encryption_key": encryption_key,
        }
        for pk, audio_key, encryption_key in Records.objects.filter(
            status=Records.STATUS_DONE
        ).exclude(audio_key="").exclude(encryption_key="")
        .values_list("pk", "audio_key", "encryption_key")
    ]
    if not records:
        return {"received": 0, "upserted": 0}
    return _post("ingest/call-audio-keys", records)


def push_archive_to_wfm(reconcile=True):
    serialized_records = ScoresForMonthSerializer(
        ScoresForMonth.objects.all().order_by("pk"), many=True
    ).data
    records = []
    for serialized in serialized_records:
        item = _wfm_record(serialized)
        item["external_id"] = serialized["id"]  # internal sync key
        item["source_row"] = serialized["source_row"]  # duplicate-safe archive key
        records.append(item)
    result = _post("ingest/operator-call-archive", records) if records else {"received": 0, "upserted": 0}
    if reconcile and records:
        result["reconcile"] = _post(
            "reconcile/operator-call-archive",
            {"all": True, "external_ids": [item["external_id"] for item in records]},
        )
    return result