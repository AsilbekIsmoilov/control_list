import io
import sys
import time
from contextlib import contextmanager

from celery import shared_task
from django.core.management import call_command
from django.utils import timezone

from project.helpers import extract_and_download_records, searchable_operators
from project import wfm_images
from project.models import CallData
from project.sheets import get_archive, update_call_data
from project.wfm_sync import push_archive_to_wfm, push_audio_keys_to_wfm, push_current_to_wfm


LOG_FLUSH_SECONDS = 1.5


class TaskLog(io.TextIOBase):
    """Collects `print()` output and periodically writes it to the Celery meta.

    Writing on every line would mean hundreds of round trips to Redis, so
    updates are throttled to `LOG_FLUSH_SECONDS`.
    """

    def __init__(self, task):
        self.task = task
        self.lines = []
        self._buffer = ""
        self._last_flush = 0.0

    def write(self, text):
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.lines.append(line)
        now = time.monotonic()
        if now - self._last_flush >= LOG_FLUSH_SECONDS:
            self._last_flush = now
            self.publish()
        return len(text)

    def text(self):
        return "\n".join(self.lines + ([self._buffer] if self._buffer else []))

    def publish(self, state="PROGRESS"):
        try:
            self.task.update_state(state=state, meta={"log": self.text()})
        except Exception:
            pass  # a failed log write must not abort the task


@contextmanager
def capture_log(task):
    """Captures `print()` calls made inside the task and adds them to the result."""
    log = TaskLog(task)
    original = sys.stdout
    sys.stdout = log
    try:
        yield log
    finally:
        sys.stdout = original
        # Keep a copy in the worker journal too. If the console encoding is
        # limited (Windows cp1251 plus emoji) the write fails — that must not
        # affect the outcome of the work.
        try:
            original.write(log.text() + "\n")
        except Exception:
            pass



@shared_task(
    name="project.push_current_to_wfm",
    autoretry_for=(Exception,),
    retry_backoff=30,
    retry_kwargs={"max_retries": 10},
)
def push_current_to_wfm_task(operator_ids=None, reconcile=False):
    return push_current_to_wfm(operator_ids=operator_ids, reconcile=reconcile)


@shared_task(
    name="project.push_archive_to_wfm",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 10},
)
def push_archive_to_wfm_task():
    return push_archive_to_wfm(reconcile=True)


@shared_task(
    name="project.sync_queue",
    autoretry_for=(Exception,),
    retry_backoff=20,
    retry_kwargs={"max_retries": 3},
)
def sync_queue_task():
    """Reads SYNC_QUEUE and refreshes the CallData rows that changed."""
    started_at = timezone.now()
    call_command("sync_changed_rows", quiet=True)
    changed_ids = list(
        CallData.objects.filter(
            is_active=True, source_updated_at__gte=started_at
        ).values_list("pk", flat=True)
    )
    if changed_ids:
        push_current_to_wfm_task.delay(changed_ids, False)
    return {"status": "ok", "wfm_push_count": len(changed_ids)}


@shared_task(
    name="project.warm_photo_cache",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 2},
)
def warm_photo_cache_task():
    """Keeps the WFM photo answers warm so no page render waits on a search."""
    names = searchable_operators().values_list("name", flat=True)
    warmed = wfm_images.prime_cache(list(names))
    return {"status": "ok", "warmed": warmed}


@shared_task(
    name="project.daily_autoupdate",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 2},
)
def daily_autoupdate_task():
    """Daily full sync of CallData and audio records."""
    updated_count = update_call_data()
    extract_and_download_records()
    # Keys must go before the comments: the front end tries to play as soon
    # as it sees an audio_id, so the key has to be ready in WFM by then.
    push_audio_keys_to_wfm()
    push_current_to_wfm_task.delay(None, True)
    return {"status": "ok", "updated_count": updated_count}


@shared_task(
    name="project.archive_update",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 3},
)
def archive_update_task(self):
    """Refreshes the ScoresForMonth archive on days 20-22 of the month."""
    with capture_log(self) as log:
        print("▶ Обновляем архив…")
        get_archive()
        push_archive_to_wfm_task.delay()
        print("✅ Arxiv yangilandi, WFM'ga uzatildi")
    return {"status": "ok", "log": log.text()}


# --- Buttons on the admin page --------------------------------------------
# These jobs run for several minutes. They used to run inside the web request
# and would exceed the gunicorn `--timeout`, which killed the worker
# (SystemExit -> 500). Now they are queued: the browser gets an immediate
# response and the work happens on a Celery worker, in the right environment.
#
# The functions print a lot — that output is written to the Celery meta as it
# goes, which is what lets the admin page show the log live.

@shared_task(
    name="project.update_current",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 2},
)
def update_current_task(self):
    """Current month scores: Sheets -> CallData -> WFM."""
    with capture_log(self) as log:
        print("▶ Обновляем текущий месяц…")
        updated_count = update_call_data()
        print(f"✅ {updated_count} ta CallData yangilandi")
        push_audio_keys_to_wfm()
        push_current_to_wfm_task.delay(None, True)
        print("✅ WFM'ga uzatildi")
    return {"status": "ok", "updated_count": updated_count, "log": log.text()}


@shared_task(
    name="project.download_records",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 2},
)
def download_records_task(self):
    """Downloads the audio records and pushes keys and audio_ids to WFM."""
    with capture_log(self) as log:
        print("▶ Обновляем архив записей…")
        extract_and_download_records()
        # Keys before the comments: the front end tries to play as soon as it
        # sees an audio_id, so the key has to be ready in WFM by then.
        push_audio_keys_to_wfm()
        push_current_to_wfm_task.delay(None, True)
        print("✅ WFM'ga uzatildi")
    return {"status": "ok", "log": log.text()}


@shared_task(
    name="project.import_archive_2025",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_kwargs={"max_retries": 1},
)
def import_archive_2025_task(self):
    """One-off import of the 2025 archive."""
    with capture_log(self) as log:
        print("▶ Скачать архив (2025)…")
        call_command("import_archive")
        print("✅ Tugadi")
    return {"status": "ok", "log": log.text()}