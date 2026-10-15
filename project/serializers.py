from rest_framework import serializers

from project.models import CALL_CODE_RE, CallData, Records, ScoresForMonth
from project.storage import audio_id_from_key


# API chiqishidagi maydon nomi  ->  modeldagi yassi maydon prefiksi (1..10)
_STR_GROUPS = {
    "code_data": "code",
    "call_data": "call",
    "service_data": "service",
    "comment": "comment",
}
_NUM_GROUPS = {
    f: f for f in [
        "greeting", "hearing", "question", "interest", "cons", "polite",
        "speech", "note", "warning", "emotion", "solution",
    ]
}
_DEC_GROUPS = {"dialog": "dialog"}


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _structured_comments(obj, audio_ids=None):
    """Build comment1..comment10 objects from the matching flat model fields.

    `audio_ids` — {call_code: audio_id} xaritasi. Frontga to'g'ridan-to'g'ri
    havola emas, faqat noaniq identifikator beriladi; baytlarni WFM o'zining
    guard'li stream endpointi orqali uzatadi.
    """
    result = []
    for index in range(1, 11):
        raw_comment = (getattr(obj, f"comment{index}", "") or "").strip()
        if not raw_comment:
            continue

        match = CALL_CODE_RE.search(raw_comment)
        call_code = match.group(1) if match else None
        comment = raw_comment
        if match:
            comment = (raw_comment[: match.start()] + raw_comment[match.end() :]).lstrip(
                " \t\r\n"
            )

        checked_at = None
        if call_code:
            for call_index in range(1, 11):
                if str(getattr(obj, f"call{call_index}", "") or "").strip() == call_code:
                    checked_at = getattr(obj, f"code{call_index}", "") or None
                    break

        result.append(
            {
                "call_code": call_code,
                "checked_at": checked_at,
                "comment": comment,
                "audio_id": (audio_ids or {}).get(call_code),
            }
        )
    return result

def _grouped_arrays(obj):
    """Yassi code1..code10 ... maydonlarni mezon bo'yicha massivlarga yig'adi.
    Har bir massiv uzunligi = to'ldirilgan qo'ng'iroqlar soni (bo'shlari kesiladi)."""
    # 1) barcha maydonlarni to'liq 10 talik massivga o'qib olamiz
    raw = {}
    for out, prefix in _STR_GROUPS.items():
        raw[out] = [getattr(obj, f"{prefix}{i}", "") or "" for i in range(1, 11)]
    for out, prefix in _NUM_GROUPS.items():
        raw[out] = [getattr(obj, f"{prefix}{i}", None) for i in range(1, 11)]
    for out, prefix in _DEC_GROUPS.items():
        raw[out] = [_to_float(getattr(obj, f"{prefix}{i}", None)) for i in range(1, 11)]

    # 2) to'ldirilgan qo'ng'iroqlar sonini (N) aniqlaymiz
    n = 0
    for i in range(10):
        has = any(raw[out][i] for out in _STR_GROUPS) or \
            any(raw[out][i] is not None for out in _NUM_GROUPS) or \
            any(raw[out][i] for out in _DEC_GROUPS)
        if has:
            n = i + 1

    # 3) har bir massivni [0:N] gacha kesamiz
    return {out: vals[:n] for out, vals in raw.items()}


# Guruhlangan (massiv) chiqishdagi barcha maydonlar tartibi
_GROUP_FIELDS = [
    "code_data", "call_data", "service_data",
    "greeting", "hearing", "question", "interest", "cons", "polite",
    "speech", "note", "warning", "emotion", "solution",
    "dialog",
]


class GroupedCallsMixin(serializers.ModelSerializer):
    """Yassi 1..10 maydonlarni mezon bo'yicha massivlarga aylantiradi (JSONField ko'rinishi)."""

    mark = serializers.SerializerMethodField()
    mis = serializers.SerializerMethodField()
    total_call_datas = serializers.SerializerMethodField()
    total_comments = serializers.SerializerMethodField()
    # guruhlangan massivlar dinamik qo'shiladi (get_ metodlarsiz)
    code_data = serializers.SerializerMethodField()
    call_data = serializers.SerializerMethodField()
    service_data = serializers.SerializerMethodField()
    greeting = serializers.SerializerMethodField()
    hearing = serializers.SerializerMethodField()
    question = serializers.SerializerMethodField()
    interest = serializers.SerializerMethodField()
    cons = serializers.SerializerMethodField()
    polite = serializers.SerializerMethodField()
    speech = serializers.SerializerMethodField()
    note = serializers.SerializerMethodField()
    warning = serializers.SerializerMethodField()
    emotion = serializers.SerializerMethodField()
    solution = serializers.SerializerMethodField()
    dialog = serializers.SerializerMethodField()

    @property
    def audio_ids(self):
        """{call_code: audio_id}. `many=True` da bitta child serializer barcha
        obyektlarga xizmat qilgani uchun so'rov bir marta bajariladi."""
        if not hasattr(self, "_audio_ids"):
            # Kalitsiz yozuvni eshittirib bo'lmaydi — u yo'q deb hisoblanadi.
            self._audio_ids = {
                call_code: audio_id_from_key(key)
                for call_code, key in Records.objects.filter(
                    status=Records.STATUS_DONE
                ).exclude(audio_key="").exclude(encryption_key="")
                .values_list("call_code", "audio_key")
            }
        return self._audio_ids

    def to_representation(self, obj):
        self._groups = _grouped_arrays(obj)
        representation = super().to_representation(obj)
        representation["comments"] = _structured_comments(obj, self.audio_ids)
        return representation

    def get_mark(self, obj):
        return _to_float(obj.mark)

    def get_mis(self, obj):
        return [obj.mis1, obj.mis2, obj.mis3]

    def get_total_call_datas(self, obj):
        return sum(1 for v in self._groups["call_data"] if v)

    def get_total_comments(self, obj):
        return len(_structured_comments(obj))


# har bir guruh maydoni uchun get_<field> metodini avtomatik biriktiramiz
def _make_group_getter(field):
    def getter(self, obj):
        return self._groups[field]
    return getter


for _f in _GROUP_FIELDS:
    setattr(GroupedCallsMixin, f"get_{_f}", _make_group_getter(_f))


class CallDataSerializer(GroupedCallsMixin):
    """JSONField ko'rinishi: har bir mezon alohida massiv (code_data, greeting, ...)."""

    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = CallData
        fields = [
            "id", "operator_code", "name", "group", "bl", "mark", "month",
            "photo_url", "photo_hash",
            "total_call_datas", "total_comments",
            *_GROUP_FIELDS, "mis",
        ]

    def get_photo_url(self, obj):
        if not obj.photo:
            return None
        request = self.context.get("request")
        url = obj.photo.url
        return request.build_absolute_uri(url) if request else url


class CallDataFullSerializer(serializers.ModelSerializer):
    """To'liq (yassi) ko'rinish — ?full=1 bilan chaqiriladi."""

    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = CallData
        fields = "__all__"

    def get_photo_url(self, obj):
        if not obj.photo:
            return None
        request = self.context.get("request")
        url = obj.photo.url
        return request.build_absolute_uri(url) if request else url


class ScoresForMonthSerializer(GroupedCallsMixin):
    """Arxiv — CallData bilan bir xil JSONField ko'rinishi."""

    operator_id = serializers.IntegerField(source="operator.id", read_only=True)

    class Meta:
        model = ScoresForMonth
        fields = [
            "id", "operator_id", "operator_code", "source_row",
            "name", "group", "bl", "mark", "month",
            "total_call_datas", "total_comments",
            *_GROUP_FIELDS, "mis",
        ]
