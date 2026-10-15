from django.urls import path
from rest_framework.routers import DefaultRouter

from project.api import CallDataViewSet, RecordPlayUrlView, ScoresForMonthViewSet

router = DefaultRouter()
router.register(r"operators", CallDataViewSet, basename="operators")
router.register(r"archive", ScoresForMonthViewSet, basename="archive")

urlpatterns = router.urls + [
    path(
        "records/<str:audio_id>/play-url/",
        RecordPlayUrlView.as_view(),
        name="record-play-url",
    ),
]
