# Control List

Django backend for contact center quality evaluations, archives, and call recordings. Runs as a standalone web application or integrates with other projects through a read-only REST API.

**Stack:** Django · DRF · MySQL · Celery · Redis · Google Sheets · MinIO · FFmpeg.

## Services and Functions

| Module | Main functions / responsibility |
| --- | --- |
| `project/sheets.py` | `update_call_data(row_numbers=None)`, `get_archive()` — import evaluations and archives from Google Sheets |
| `project/helpers.py` | `extract_and_download_records()`, `package_hls()` — download SPX/ZIP recordings and create AES-128 encrypted AAC/HLS |
| `project/storage.py` | `ensure_bucket()`, `upload_hls_dir()`, `read_object()`, `iter_object()` — MinIO storage |
| `project/wfm_sync.py` | `push_current_to_wfm()`, `push_archive_to_wfm()`, `push_audio_keys_to_wfm()` — external WFM synchronization |
| `project/wfm_images.py` | `find_photo_url()`, `prime_cache()` — WFM operator photos and caching |
| `project/serializers.py` | Group evaluation fields into arrays and attach comment/audio IDs |
| `project/views.py` | Monthly/quarterly summaries, task progress, documents, audio streaming, and activity logs |

MySQL stores evaluations, archives, recording status, and AES keys. MinIO stores playlists and encrypted segments. The 2025 archive uses a separate model.

## Endpoints

| Method | URL | Purpose |
| --- | --- | --- |
| GET | `/api/operators/`, `/api/operators/<id>/` | Active operators and evaluations |
| GET | `/api/archive/`, `/api/archive/<id>/` | Monthly archives |
| GET | `/api/records/<audio_id>/play-url/` | HLS playback URL |
| GET | `/record-audio/<audio_id>/index.m3u8` | Playlist |
| GET | `/record-audio/<audio_id>/<segment>` | Encrypted `seg_NNN.ts` segment |
| GET | `/record-audio/<audio_id>/key` | AES decryption key |
| GET | `/update/process/<action>/` | Queue an update; login required |
| GET | `/update/status/<task_id>/` | Task state and logs; login required |
| POST | `/log-calendar-open/` | Record calendar activity |

API filters: `operator_code`, `group`, `month`, `search`, `ordering`, `page`; archive additionally accepts `operator`, operators accept `full=1`. Lists return 50 records per page. Use `comments[].audio_id` to request a playback URL.

Update actions: `current`, `archive`, `archive_2025`, `records`. Other routes provide monthly/quarterly pages (`/`, `/list2/`), documents (`/management/`, `/updates/`), schedules (`/latest-schedule/<code>/`), login/logout, and `/admin/`.

## Celery and Redis

| Task (`project.` prefix) | Work |
| --- | --- |
| `daily_autoupdate` | Import current data, process audio, push keys, queue WFM export |
| `archive_update` | Import archive and queue WFM export |
| `update_current`, `download_records`, `import_archive_2025` | Manual background updates |
| `push_current_to_wfm`, `push_archive_to_wfm` | WFM exports with retries |
| `sync_queue`, `warm_photo_cache` | Changed-row import and photo-cache warming; not scheduled by default |

Beat schedule: daily **05:00**, archive on the **20th–22nd at 06:00**, timezone **Asia/Tashkent**. Redis defaults: broker database **5**, results/cache database **6**; queue **`list_myproject`**. Import completion does not confirm completion of a separately queued WFM export.

## Run

Requires Python 3.10+, MySQL, Redis; audio additionally requires MinIO and FFmpeg.

```bash
python -m venv .venv
# Activate: .venv\Scripts\Activate.ps1 (Windows) or source .venv/bin/activate (Linux)
pip install -r requirements.txt
pip install whitenoise
```

Copy `.env.example` to `.env` next to `manage.py`. Set `DJANGO_SECRET_KEY`, your MySQL credentials (`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`), and the settings needed for your integrations:

| Service | Environment variables |
| --- | --- |
| Redis | `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CACHE_URL` |
| Google Sheets | `GOOGLE_CREDENTIALS_FILE` — private service-account JSON path |
| Audio source | `API_BASE_URL` — call code is appended directly; `FFMPEG_PATH` |
| MinIO | `MINIO_ENDPOINT`, `MINIO_PORT`, `MINIO_USE_SSL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `STORAGE_BUCKET` |
| WFM export | `WFM_SYNC_BASE_URL`, `WFM_SYNC_TOKEN` |
| WFM photos | `WFM_IMAGES_BASE_URL`, `WFM_IMAGES_CLIENT_ID`, `WFM_IMAGES_CLIENT_SECRET` |

Share `СВОД` (`WEB UCHUN`) and `ЛК сайт` (`Архив`, `Архив (2025)`) with the service account. Imports use fixed columns in `A2:GT`.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
# Run each in a separate terminal:
celery -A myproject worker --loglevel=info --concurrency=1
celery -A myproject beat --loglevel=info
# Initial current-data/audio import, without WFM export:
python manage.py daily_full_sync
```

For local Windows workers, replace `--concurrency=1` with `--pool=solo`. Open `http://127.0.0.1:8000/`.

## Important Notes

- API and audio endpoints currently allow unauthenticated access. Configure production permissions, `DEBUG`, and `ALLOWED_HOSTS` before deployment; keep secrets in `.env`.
- `sync_changed_rows` needs fixes: missing `CREDENTIALS` import and unsupported `sync_photos` argument. WhiteNoise is missing from requirements; dependency installation is not verified.
- Back up MySQL **and** MinIO: encrypted recordings require their database keys. Keep credentials and temporary files out of Git.
- Check with `python manage.py check`; diagnostics: `diag_audio.py`, `diag_wfm.py`, `diag_lost.py`. Meaningful automated tests are not yet implemented.
