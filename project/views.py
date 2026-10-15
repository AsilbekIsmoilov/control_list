import json
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

import re

from django.http import HttpResponse, JsonResponse, HttpResponseServerError, FileResponse, HttpResponseForbidden, Http404, StreamingHttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from project import storage, tasks, wfm_images
from myproject.celery import app as celery_app
from project.models import *
from .forms import *
import datetime
import sys
from io import StringIO
from project.sheets import get_archive,update_call_data
from datetime import datetime
from statistics import mean
from django.views.decorators.http import require_http_methods
import shutil
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login,logout
from django.contrib import messages
from .helpers import *
from django.utils import timezone
from archive.models import Archive2025
from django.core.management import call_command
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST


# Sahifadagi JS `/log-calendar-open/` ga POST qiladi va `X-CSRFToken` ni
# cookie'dan oladi. index.html -> base.html zanjirida `{% csrf_token %}` yo'q,
# ya'ni Django cookie'ni hech qachon o'rnatmasdi va har POST 403 bilan
# tugardi ("CSRF cookie not set").
@ensure_csrf_cookie
def index(request):
    selected_name = get_operator_from_request(request)
    selected_month_param = request.GET.get("month")
    operators = searchable_operators()
    backgrounds = BackgroundImage.objects.order_by('order')

    total_requests = RequestLog.objects.count()

    unique_users = RequestLog.objects.values(
        "ip_address"
    ).distinct().count()

    selected_operator = None
    monthly_scores = None
    month_names_in_db = []
    selected_month = ""
    selected_month_pair = ""
    selected_month_int = None
    source_label = ""

    # Ombor havolasi emas — o'z HLS endpointimiz. Front hls.js bilan
    # bo'laklarni deshifrlab eshittiradi.
    call_code_to_url = {
        call_code: record_playlist_url(storage.audio_id_from_key(key))
        for call_code, key in Records.objects.filter(status=Records.STATUS_DONE)
        .exclude(audio_key="")
        .exclude(encryption_key="")
        .values_list("call_code", "audio_key")
    }

    month_pairs = {
        1: "Январь-Февраль", 2: "Февраль-Март", 3: "Март-Апрель",
        4: "Апрель-Май", 5: "Май-Июнь", 6: "Июнь-Июль",
        7: "Июль-Август", 8: "Август-Сентябрь", 9: "Сентябрь-Октябрь",
        10: "Октябрь-Ноябрь", 11: "Ноябрь-Декабрь", 12: "Декабрь-Январь"
    }

    if selected_name:
        try:
            selected_operator = CallData.objects.get(name=selected_name)
            months_set = set()
            if selected_operator.month is not None:
                months_set.add(selected_operator.month)
            archived_months = ScoresForMonth.objects.filter(operator=selected_operator).values_list('month', flat=True).distinct()
            months_set.update(m for m in archived_months if m is not None)

            months_in_db = sorted(int(m) for m in months_set)
            month_names_in_db = [(f"{m:02}", month_pairs.get(m)) for m in months_in_db]

            if selected_month_param:
                try:
                    selected_month_int = int(selected_month_param)
                    monthly_scores = ScoresForMonth.objects.filter(operator=selected_operator, month=selected_month_int).first()
                    if monthly_scores:
                        source_label = "Источник: архив"
                    elif selected_operator.month == selected_month_int:
                        monthly_scores = selected_operator
                except (ValueError, TypeError):
                    selected_month_int = selected_operator.month or 1
                    monthly_scores = selected_operator
            else:
                selected_month_int = selected_operator.month or 1
                monthly_scores = selected_operator

            if selected_month_int:
                selected_month = f"{selected_month_int:02}"
                selected_month_pair = month_pairs.get(selected_month_int)
        except CallData.DoesNotExist:
            pass



    return render(request, 'project/index.html', {
        "title": "Лист контроль",
        "operators": operators,
        "selected_operator": selected_operator,
        "monthly_scores": monthly_scores,
        "selected_month": selected_month,
        "selected_month_pair": selected_month_pair,
        "month_names_in_db": month_names_in_db,
        "selected_month_param": selected_month_param,
        'backgrounds': backgrounds,
        "call_code_to_url": call_code_to_url,
        "operator_photo_url": operator_photo_url(selected_operator),

        "total_requests": total_requests,
        "unique_users": unique_users,
    })

def get_month_source(operator, month: int, year: str):
    if year == "2025":
        return Archive2025.objects.filter(
            operator=operator,
            month=str(month)
        ).first()

    if operator.month == month:
        return operator

    return ScoresForMonth.objects.filter(
        operator=operator,
        month=str(month)
    ).first()

def get_quarter_score(operator: CallData, quarter: str, year: str) -> float | None:
    QUARTERS = {
        "Q1": [1, 2, 3],
        "Q2": [4, 5, 6],
        "Q3": [7, 8, 9],
        "Q4": [10, 11, 12],
    }

    scores = []

    for month in QUARTERS.get(quarter, []):
        source = get_month_source(operator, month, year)
        if source and source.mark is not None:
            scores.append(float(source.mark))

    return round(mean(scores), 1) if scores else None

def get_current_quarter():
    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day

    if day < 20:
        month -= 1
        if month == 0:
            month = 12
            year -= 1


    cycle_number = {
        1: 1,
        2: 2,
        3: 3,
        4: 4,
        5: 5,
        6: 6,
        7: 7,
        8: 8,
        9: 9,
        10: 10,
        11: 11,
        12: 12,
    }[month]

    if month in [1, 2, 3]:
        return "Q1"
    elif month in [4, 5, 6]:
        return "Q2"
    elif month in [7, 8, 9]:
        return "Q3"
    else:
        return "Q4"

def get_month_names_for_quarter(quarter: str):
    mapping = {
        "Q1": ["Янв", "Фев", "Мар"],
        "Q2": ["Апр", "Май", "Июнь"],
        "Q3": ["Июль", "Авг", "Сен"],
        "Q4": ["Окт", "Ноя", "Дек"],
    }
    return mapping.get(quarter, ["—", "—", "—"])

def get_criteria_penalties(operator, quarter, year):
    QUARTERS = {
        "Q1": [1, 2, 3],
        "Q2": [4, 5, 6],
        "Q3": [7, 8, 9],
        "Q4": [10, 11, 12],
    }

    group = str(operator.group) if operator.group else ""

    criteria_titles = {
        "greeting": "<div style='margin-top:5px; margin-bottom:10px;'>Приветствие</div>",
        "hearing": "Внимательное слушание",
        "question": "Исп. уточняющих вопросов",
        "interest": "Заинтересованность в проблеме",
        "cons": "Понятное пред.. информации",
        "polite": "Доброжелательн.. Вежливость",
        "speech": "Грамотная<br>речь",
        "note": 'Установка на "Удержание"' if group == "1009" else "Оформление и обработка заявок",
        "warning": "Предупреждение об ожидании",
        "emotion": "Скорость обслуживания" if group == "1009" else "Эмоциональная окраска голоса",
        "solution": "<div style='margin-top:5px; margin-bottom:10px;'>Прощание</div>",
    }


    result = []

    for criterion, title in criteria_titles.items():
        penalties = []

        for month in QUARTERS.get(quarter, []):
            source = get_month_source(operator, month, year)
            if not source:
                penalties.append(0)
                continue

            count = 0
            for i in range(1, 11):
                val = getattr(source, f"{criterion}{i}", None)
                if val == 2:
                    count += 1
                elif val == 1:
                    count += 2

            penalties.append(count)

        result.append({"title": title, "data": penalties})

    return result

def get_total_penalty_sum(operator, quarter, year):
    criteria_data = get_criteria_penalties(operator, quarter, year)
    return sum(sum(item["data"]) for item in criteria_data)


def get_penalties_per_quarter(operator, year):
    return [
        get_total_penalty_sum(operator, "Q1", year),
        get_total_penalty_sum(operator, "Q2", year),
        get_total_penalty_sum(operator, "Q3", year),
        get_total_penalty_sum(operator, "Q4", year),
    ]


def get_comments_for_quarter(operator, quarter, year):
    QUARTERS = {
        "Q1": [1, 2, 3],
        "Q2": [4, 5, 6],
        "Q3": [7, 8, 9],
        "Q4": [10, 11, 12],
    }

    MONTH_NAMES = {
        1: "Январь-Февраль", 2: "Февраль-Март", 3: "Март-Апрель",
        4: "Апрель-Май", 5: "Май-Июнь", 6: "Июнь-Июль",
        7: "Июль-Август", 8: "Август-Сентябрь", 9: "Сентябрь-Октябрь",
        10: "Октябрь-Ноябрь", 11: "Ноябрь-Декабрь", 12: "Декабрь-Январь",
    }

    comments = []

    for month in QUARTERS.get(quarter, []):
        source = get_month_source(operator, month, year)
        if not source:
            continue

        for i in range(1, 11):
            text = getattr(source, f"comment{i}", "")
            if text:
                comments.append({
                    "text": text,
                    "month": month,
                    "month_name": MONTH_NAMES.get(month),
                })

    return comments

def get_mistakes_for_quarter(operator, quarter, year):
    QUARTERS = {
        "Q1": [1, 2, 3],
        "Q2": [4, 5, 6],
        "Q3": [7, 8, 9],
        "Q4": [10, 11, 12],
    }

    TYPE_MAP = {1: "severe", 2: "major", 3: "minor"}
    mises = []

    for month in QUARTERS.get(quarter, []):
        source = get_month_source(operator, month, year)
        if not source:
            continue

        for i in range(1, 4):
            count = getattr(source, f"mis{i}", 0) or 0
            for _ in range(count):
                mises.append({
                    "type": TYPE_MAP.get(i),
                    "month": month,
                })

    return mises



def list2(request):
    selected_name = get_operator_from_request(request)
    selected_quarter = request.GET.get("quarter", get_current_quarter())
    selected_year = request.GET.get("year", "2026")
    operator = None

    chart_score = None
    quarter_penalties = []
    criteria_data = []
    operators = searchable_operators()
    monthly_marks = []
    quarter_comments = []
    quarter_mises = []
    backgrounds = BackgroundImage.objects.order_by('order')

    MONTH_NAME_TO_NUMBER = {
        "Янв": 1, "Фев": 2, "Мар": 3, "Апр": 4,
        "Май": 5, "Июнь": 6, "Июль": 7, "Авг": 8,
        "Сен": 9, "Окт": 10, "Ноя": 11, "Дек": 12
    }

    if selected_name:
        request.session["selected_operator"] = selected_name
        operator = get_object_or_404(CallData, name=selected_name, is_active=True)
        raw_score = get_quarter_score(operator, selected_quarter, selected_year)
        chart_score = str(raw_score).replace('.', ',') if raw_score is not None else None
        criteria_data = get_criteria_penalties(operator, selected_quarter, selected_year)
        quarter_comments = get_comments_for_quarter(operator, selected_quarter, selected_year)
        quarter_mises = get_mistakes_for_quarter(operator, selected_quarter, selected_year)
        quarter_penalties = get_penalties_per_quarter(operator, selected_year)
        months = get_month_names_for_quarter(selected_quarter)
        for month in months:
            month_num = MONTH_NAME_TO_NUMBER.get(month)
            source = get_month_source(operator, month_num, selected_year)

            if source and source.mark is not None:
                monthly_marks.append(round(float(source.mark), 1))
            else:
                monthly_marks.append(0)

    context = {
        "operator": operator,
        "selected_quarter": selected_quarter,
        "selected_year": selected_year,
        "chart_score": chart_score,
        "month_names": get_month_names_for_quarter(selected_quarter),
        "criteria_data": json.dumps(criteria_data, ensure_ascii=False),
        "operators": operators,
        "monthly_marks": monthly_marks,
        "quarter_comments": json.dumps(quarter_comments),
        "quarter_mises": json.dumps(quarter_mises),
        "quarter_penalties": quarter_penalties,
        "backgrounds": backgrounds,
        "operator_photo_url": operator_photo_url(operator),
    }

    return render(request, "project/list2.html", context)



@login_required(login_url='login')
def update_page(request):
    context = {
        "title":"Update Page"
    }
    return render(request, 'components/update_page.html',context)


# Har bir tugma -> Celery taski. Ishlar bir necha daqiqa davom etadi va
# ilgari veb-so'rov ichida bajarilardi: gunicorn `--timeout` ni oshirib
# yuborib, workerni o'ldirardi (SystemExit — `except Exception` uni
# ushlamaydi) va foydalanuvchi 500 ko'rardi. Endi darhol javob qaytadi.
# Task nomi bo'yicha saqlanadi, obyektning o'zi emas: `getattr` chaqiruv
# paytida bajariladi, ya'ni ro'yxat import tartibiga bog'lanib qolmaydi.
UPDATE_TASKS = {
    "current": ("Обновляем текущий месяц", "update_current_task"),
    "archive": ("Обновляем архив", "archive_update_task"),
    "archive_2025": ("Скачать архив (2025)", "import_archive_2025_task"),
    "records": ("Обновляем архив записей", "download_records_task"),
}


def _update_page(body, status=200):
    return HttpResponse(f"<pre>{body}</pre>", status=status)


# Opened when a button is pressed; it keeps polling `/update/status/<id>/`.
# The `print()` calls inside the task are written to the Celery meta as they
# happen (tasks.capture_log), so the log is visible while the job runs.
_PROGRESS_PAGE = """<!DOCTYPE html>
<html lang="uz"><head><meta charset="utf-8"><title>{title}</title>
<style>
 body {{ margin:0; padding:24px; background:#14171a; color:#e6e8ea;
        font:13px/1.6 ui-monospace,Menlo,Consolas,monospace; }}
 h1 {{ font-size:15px; margin:0 0 4px; }}
 .state {{ display:inline-block; padding:2px 10px; border-radius:99px;
          font-size:12px; border:1px solid #2c3238; color:#9aa4af; }}
 .run {{ color:#fbbf24; border-color:#fbbf24 }}
 .ok  {{ color:#4ade80; border-color:#4ade80 }}
 .err {{ color:#f87171; border-color:#f87171 }}
 pre {{ background:#1c2024; border:1px solid #2c3238; border-radius:8px;
       padding:14px; margin-top:14px; white-space:pre-wrap; word-break:break-word;
       max-height:70vh; overflow:auto; }}
 .id {{ color:#6b7280; font-size:12px; }}
</style></head><body>
<h1>{title}</h1>
<div class="id">id: {task_id}</div>
<div style="margin-top:10px"><span class="state run" id="state">…</span></div>
<pre id="log">…</pre>
<script>
const el = document.getElementById('log'), st = document.getElementById('state');
let stop = false, fails = 0;
async function poll() {{
  if (stop) return;
  try {{
    const r = await fetch('/update/status/{task_id}/', {{headers: {{Accept: 'application/json'}}}});
    if (!r.ok) throw new Error('HTTP ' + r.status);
    if (!(r.headers.get('content-type') || '').includes('application/json'))
      throw new Error('response is not JSON (HTTP ' + r.status + ')');
    const d = await r.json();
    fails = 0;
    if (d.log) {{
      const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
      el.textContent = d.log;
      if (atBottom) el.scrollTop = el.scrollHeight;
    }}
    st.textContent = d.label;
    st.className = 'state ' + d.css;
    if (d.done) {{ stop = true; return; }}
  }} catch (e) {{
    // Do not stay silent: if /update/status/ never answers, the page would
    // sit on its placeholder forever with no hint as to why.
    if (++fails >= 3) {{
      st.textContent = 'status unavailable';
      st.className = 'state err';
      el.textContent = '/update/status/{task_id}/ is not responding: ' + e.message
        + '\\n\\nThe task keeps running on its own — this is only the monitor.'
        + '\\nCheck that urls.py and middleware/block_page.py are deployed'
        + '\\nand that gunicorn has been restarted.';
    }}
  }}
  setTimeout(poll, 1500);
}}
poll();
</script></body></html>"""


_STATE_LABELS = {
    # In Celery, PENDING means "no worker has picked it up yet" (queued, or an
    # unknown id). Labelling it "running" would make a queued task look active.
    "PENDING": ("queued…", "run"),
    "STARTED": ("started…", "run"),
    "PROGRESS": ("in progress…", "run"),
    "RETRY": ("retrying…", "run"),
    "SUCCESS": ("finished", "ok"),
    "FAILURE": ("error", "err"),
}


@login_required(login_url='login')
def update_status(request, task_id):
    """Returns the task state and log — this is what the page polls."""
    result = celery_app.AsyncResult(task_id)
    state = result.state
    label, css = _STATE_LABELS.get(state, (state.lower(), "run"))

    info = result.info
    if state == "FAILURE":
        log = f"❗ {info}"
    elif isinstance(info, dict):
        log = info.get("log", "")
    else:
        log = ""

    return JsonResponse({
        "state": state,
        "label": label,
        "css": css,
        "log": log,
        "done": state in ("SUCCESS", "FAILURE"),
    })


@login_required(login_url='login')
def update_process(request, action):
    entry = UPDATE_TASKS.get(action)
    if entry is None:
        return _update_page("❌ Неизвестная команда.", status=400)

    title, task_name = entry
    try:
        result = getattr(tasks, task_name).delay()
    except Exception as e:
        # We land here if the broker is down, or if the Celery app was never
        # wired up (no celery_app import in myproject/__init__.py).
        return _update_page(
            f"❗ Could not queue the task: {e}\n\n"
            "Check that the Celery broker is running and that\n"
            "myproject/__init__.py has `from myproject.celery import app as celery_app`.",
            status=503,
        )

    return HttpResponse(_PROGRESS_PAGE.format(title=title, task_id=result.id))



@login_required(login_url='login')
@require_http_methods(["GET", "POST"])
def delete_media_folder(request):
    photos_path = os.path.join(settings.MEDIA_ROOT, 'photos')

    try:
        if os.path.exists(photos_path):
            shutil.rmtree(photos_path)
            os.makedirs(photos_path)
            return JsonResponse({'status': 'success', 'message': 'Папка photos удалена и пересоздана.'})
        else:
            return JsonResponse({'status': 'warning', 'message': 'Папка photos не существует.'})
    except Exception as e:
        return HttpResponseServerError(f"Ошибка при удалении: {str(e)}")


@login_required(login_url='login')
@require_http_methods(["GET", "POST"])
def delete_calldata(request):
    try:
        deleted_count, _ = CallData.objects.all().delete()
        return JsonResponse({
            'status': 'success',
            'message': f'Удалено записей: {deleted_count}'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
    
@login_required(login_url='login')
def delete_db(request):
    if not request.user.is_superuser:
        return redirect('adds') 

    context = {
        "title": "Delete datas"
    }
    return render(request, 'components/delete_db.html', context)



def management(request):
    operator_name = get_operator_from_request(request)
    backgrounds = BackgroundImage.objects.order_by('order')
    selected_operator = None
    if operator_name:
        request.session["selected_operator"] = operator_name
        selected_operator = CallData.objects.filter(name=operator_name, is_active=True).first()

    management_documents = Management.objects.all().order_by('-created_at')

    latest_doc = management_documents.first()

    context = {
        "title": "Начальство",
        "selected_operator": selected_operator,
        "management_documents": management_documents,
        "latest_doc": latest_doc,
        'backgrounds': backgrounds,
    }
    return render(request, 'project/management.html', context)


@login_required(login_url='login')
def adds_view(request):
    schedule_form = ScheduleForm()
    management_form = ManagementForm()

    if request.method == 'POST':
        if 'add_schedule' in request.POST:
            schedule_form = ScheduleForm(request.POST, request.FILES)
            if schedule_form.is_valid():
                schedule_form.save()
                return redirect('adds')
        elif 'add_management' in request.POST:
            management_form = ManagementForm(request.POST, request.FILES)
            if management_form.is_valid():
                management_form.save()
                return redirect('adds')

    context = {
        'schedule_form': schedule_form,
        'management_form': management_form,
        'management_docs': Management.objects.order_by('-created_at'),
        'schedule_docs': Schedule.objects.order_by('-created_at'),
    }

    return render(request, 'components/adds.html', context)



def custom_login(request):
    if request.method == "POST":
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', 'adds') 
            return redirect(next_url)
        else:
            messages.error(request, "Неверный логин или пароль")

    return render(request, 'project/login.html')


def custom_logout(request):
    logout(request)
    return redirect('login')



def latest_schedule_redirect(request, code):
    latest = Schedule.objects.filter(code=code).order_by('-created_at').first()
    if latest and latest.pdf_file:
        return redirect(latest.pdf_file.url)
    else:
        return redirect('/')



ALLOWED_HOST = "192.168.42.172:5001"

def is_internal_request(request):
    referer = request.META.get("HTTP_REFERER", "")
    is_admin = request.user.is_authenticated and request.user.is_staff
    return (ALLOWED_HOST in referer) or is_admin



# --- Audio: shifrlangan HLS ------------------------------------------------
# WFM tomonidagi bilan bir xil sxema, faqat avtorizatsiyasiz: bu sahifada
# login yo'q, shuning uchun uchala endpoint ham ochiq.
#
#   index.m3u8   playlist (matn) — MinIO'dagi nusxa o'zgarishsiz uzatiladi;
#                ichidagi `key` va `seg_NNN.ts` nomlari nisbiy, brauzer
#                ularni shu manzilga nisbatan hal qiladi
#   seg_NNN.ts   AES-128 bilan shifrlangan bo'lak
#   key          16 baytlik kalit — MinIO'da emas, bazada
#
# Audioni qaytaradigan bitta URL yo'q: playlist — matn, bo'laklar kalitsiz
# ochilmaydi. Kalit va bo'laklar turli omborlarda saqlanadi.

SEGMENT_NAME_RE = re.compile(r"^seg_\d{3,}\.ts$")


def record_playlist_url(audio_id):
    return f"/record-audio/{audio_id}/index.m3u8"


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def record_playlist(request, audio_id):
    """HLS playlist — hls.js shu yerdan boshlaydi."""
    try:
        raw = storage.read_object(
            storage.playlist_key(storage.key_from_audio_id(audio_id))
        )
    except Exception:
        raise Http404()

    return _no_store(HttpResponse(
        raw, content_type="application/vnd.apple.mpegurl"
    ))


def record_segment(request, audio_id, segment):
    """Shifrlangan bo'lak. Kalitsiz o'ynatib bo'lmaydi."""
    if not SEGMENT_NAME_RE.match(segment):
        raise Http404()

    key = storage.segment_key(storage.key_from_audio_id(audio_id), segment)
    try:
        size = storage.stat_object(key).size
    except Exception:
        raise Http404()

    response = StreamingHttpResponse(
        storage.iter_object(key), content_type="video/mp2t"
    )
    response["Content-Length"] = str(size)
    return _no_store(response)


def record_key(request, audio_id):
    """16 baytlik AES kaliti. MinIO'dan emas, bazadan olinadi."""
    record = (
        Records.objects.filter(
            status=Records.STATUS_DONE,
            audio_key=storage.key_from_audio_id(audio_id),
        )
        .exclude(encryption_key="")
        .only("encryption_key")
        .first()
    )
    if record is None:
        raise Http404()

    return _no_store(HttpResponse(
        bytes.fromhex(record.encryption_key),
        content_type="application/octet-stream",
    ))


def serve_photos_by_code(request, photo):
    if not is_internal_request(request):
        return render(request, '404.html', status=404)

    file_path = os.path.join(settings.MEDIA_ROOT, 'photos', photo)
    if not os.path.exists(file_path):
        raise Http404("Фото не найдено")

    ext = os.path.splitext(photo)[1].lower()
    content_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
    }
    content_type = content_types.get(ext, 'application/octet-stream')

    return FileResponse(open(file_path, 'rb'), content_type=content_type)


def operator_photo_url(operator):
    """The image the page should show for this operator, or None.

    WFM is the only source: the operator is looked up through the
    users-images endpoint and the entry marked `isActive` in their `images`
    array wins. Whoever WFM does not know gets the default avatar — there is
    no second place to look.
    """
    if operator is None:
        return None
    return wfm_images.find_photo_url(operator.name)


def trigger_404_view(request, *args, **kwargs):
    return render(request, '404.html', status=404)


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@require_POST
def log_calendar_open(request):
    try:
        data = json.loads(request.body)

        operator_name = data.get("operator_name")
        api_request_url = data.get("api_request_url")

        CalendarOpenLog.objects.create(
            operator_name=operator_name or "",
            api_request_url=api_request_url or "",
            client_ip=get_client_ip(request),
        )

        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse(
            {"status": "error", "message": str(e)},
            status=400
        )