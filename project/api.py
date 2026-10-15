from rest_framework import filters, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from project import storage
from project.models import CallData, Records, ScoresForMonth
from project.views import record_playlist_url
from project.serializers import (
    CallDataSerializer,
    CallDataFullSerializer,
    ScoresForMonthSerializer,
)


class RecordPlayUrlView(APIView):
    """Bitta yozuv uchun HLS playlist havolasi.

        GET /api/records/<audio_id>/play-url/

    `audio_id` — control list javobidagi `comments[].audio_id`. Qaytgan manzil
    audio fayl emas, playlist: bo'laklar shifrlangan va deshifrlash kaliti
    alohida endpointdan olinadi. hls.js ikkalasini ham o'zi so'raydi.
    """

    def get(self, request, audio_id):
        record = (
            Records.objects.filter(
                status=Records.STATUS_DONE,
                audio_key=storage.key_from_audio_id(audio_id),
            )
            .exclude(encryption_key="")
            .only("call_code")
            .first()
        )
        if record is None:
            raise NotFound("Bunday yozuv yo'q")

        return Response({
            "audio_id": audio_id,
            "call_code": record.call_code,
            "url": request.build_absolute_uri(record_playlist_url(audio_id)),
            "type": "application/vnd.apple.mpegurl",
        })


class CallDataViewSet(viewsets.ReadOnlyModelViewSet):
    """Operatorlar (joriy oy ballari). GET /api/operators/"""

    queryset = CallData.objects.filter(is_active=True).order_by("name")
    serializer_class = CallDataSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "group", "bl"]
    ordering_fields = ["name", "mark", "month"]

    def get_serializer_class(self):
        # ?full=1 bilan to'liq (yassi) ko'rinish
        if self.request.query_params.get("full") in ("1", "true", "yes"):
            return CallDataFullSerializer
        return CallDataSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        group = params.get("group")
        month = params.get("month")
        operator_code = params.get("operator_code")
        if operator_code:
            qs = qs.filter(operator_code=operator_code)
        if group:
            qs = qs.filter(group=group)
        if month:
            qs = qs.filter(month=month)
        return qs


class ScoresForMonthViewSet(viewsets.ReadOnlyModelViewSet):
    """Arxiv (oldingi oylar ballari). GET /api/archive/"""

    queryset = ScoresForMonth.objects.all().order_by("-month", "name")
    serializer_class = ScoresForMonthSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "group", "bl"]
    ordering_fields = ["name", "mark", "month"]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        month = params.get("month")
        operator = params.get("operator")
        operator_code = params.get("operator_code")
        group = params.get("group")
        if operator_code:
            qs = qs.filter(operator_code=operator_code)
        if month:
            qs = qs.filter(month=month)
        if operator:
            qs = qs.filter(operator_id=operator)
        if group:
            qs = qs.filter(group=group)
        return qs
