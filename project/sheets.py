import os
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from decimal import Decimal, InvalidOperation
import hashlib
from project.models import CallData, ScoresForMonth
from django.utils import timezone
import re
from dotenv import load_dotenv
from django.conf import settings

# Bare load_dotenv() searches upward from the working directory, which under
# systemd is not the project. Name the file the way settings.py does.
load_dotenv(settings.BASE_DIR / ".env")

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Two ways to hold the service account, because the two deployments differ:
# the server keeps the original JSON next to manage.py, development spreads
# it over .env. The file wins where it exists.
CREDENTIALS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE", str(settings.BASE_DIR / "credentials.json")
)

GOOGLE_ENV_VARS = (
    "GOOGLE_TYPE", "GOOGLE_PROJECT_ID", "GOOGLE_PRIVATE_KEY_ID",
    "GOOGLE_PRIVATE_KEY", "GOOGLE_CLIENT_EMAIL", "GOOGLE_CLIENT_ID",
    "GOOGLE_AUTH_URI", "GOOGLE_TOKEN_URI",
    "GOOGLE_AUTH_PROVIDER_CERT_URL", "GOOGLE_CLIENT_CERT_URL",
    "GOOGLE_UNIVERSE_DOMAIN",
)

_credentials = None


def get_credentials():
    """The Google service account, built on first use.

    This used to be assembled at import time, and `.replace()` on a missing
    GOOGLE_PRIVATE_KEY raised AttributeError while `project.views` was being
    imported — which took every page down, not only the sheet sync. Missing
    credentials now fail where they are used, and say what is missing.
    """
    global _credentials
    if _credentials is not None:
        return _credentials

    if os.path.exists(CREDENTIALS_FILE):
        _credentials = ServiceAccountCredentials.from_json_keyfile_name(
            CREDENTIALS_FILE, SCOPE
        )
        return _credentials

    missing = [name for name in GOOGLE_ENV_VARS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            f"Google hisob ma'lumotlari topilmadi: {CREDENTIALS_FILE} yo'q va "
            ".env da yetishmayapti — " + ", ".join(missing)
        )

    creds_dict = {
        "type": os.getenv("GOOGLE_TYPE"),
        "project_id": os.getenv("GOOGLE_PROJECT_ID"),
        "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
        "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
        "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
        "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_CERT_URL"),
        "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_CERT_URL"),
        "universe_domain": os.getenv("GOOGLE_UNIVERSE_DOMAIN"),
    }
    _credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
    return _credentials

def safe_convert_decimal(value):
    try:
        if not value or value.strip() in ['', '#REF!', '#N/A']:
            return Decimal('0')
        return Decimal(value.replace(',', '.'))
    except (InvalidOperation, AttributeError):
        return Decimal('0')

def safe_convert(value):
    if value == '' or value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None

def is_valid_name(name):
    return bool(extract_code(name))

def _row_has_value(value):
    return value is not None and str(value).strip() != ""


def _merge_operator_rows(numbered_rows):
    """Bir operator kodiga tegishli bir nechta Sheets qatorini birlashtiradi."""
    grouped = {}
    for row_number, row in numbered_rows:
        name = row[0].strip() if row else ""
        operator_code = extract_code(name)
        key = operator_code or f"__row_{row_number}"
        grouped.setdefault(key, []).append((row_number, row))

    prepared = []
    for key, rows in grouped.items():
        # Mark va baholash ustunlari to'liqroq bo'lgan qator asosiy hisoblanadi.
        primary_number, primary = max(
            rows,
            key=lambda item: (
                _row_has_value(item[1][5]) if len(item[1]) > 5 else False,
                sum(_row_has_value(value) for value in item[1][5:]),
            ),
        )
        max_length = max(len(row) for _, row in rows)
        merged = list(primary) + [""] * (max_length - len(primary))

        # Asosiy qatordagi bo'sh group/bl va boshqa qiymatlarni ikkinchi
        # qatordan to'ldiramiz; mavjud bahoni ustidan yozmaymiz.
        for _, row in rows:
            for index, value in enumerate(row):
                if not _row_has_value(merged[index]) and _row_has_value(value):
                    merged[index] = value

        source_rows = sorted(row_number for row_number, _ in rows)
        operator_code = None if key.startswith("__row_") else key
        payload = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
        source_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        prepared.append((merged, source_rows, operator_code, source_hash))

    return prepared

def update_call_data(row_numbers=None):
    """Google Sheets'dan CallData'ni yangilaydi.

    ``row_numbers`` berilmasa avvalgidek A2:GT diapazonining hammasi olinadi.
    Qator raqamlari berilsa faqat o'sha qatorlar olinadi; bu SYNC_QUEUE worker
    uchun ishlatiladi.
    """

    client = gspread.authorize(get_credentials())

    spreadsheet = client.open('СВОД')
    worksheet = spreadsheet.worksheet('WEB UCHUN')

    is_full_sync = row_numbers is None
    if is_full_sync:
        data = worksheet.get('A2:GT')
        numbered_rows = list(enumerate(data, start=2))
    else:
        normalized_rows = sorted({
            int(row_number)
            for row_number in row_numbers
            if int(row_number) >= 2
        })
        if not normalized_rows:
            return 0

        initial_ranges = [f"A{row_number}:GT{row_number}" for row_number in normalized_rows]
        initial_values = worksheet.batch_get(initial_ranges)
        changed_codes = {
            extract_code(value_range[0][0])
            for value_range in initial_values
            if value_range and value_range[0] and extract_code(value_range[0][0])
        }

        # Bir operator Sheets'da ikki qatorda bo'lishi mumkin. O'zgargan
        # qator kodi bo'yicha uning boshqa qatorlarini ham birga olamiz.
        if changed_codes:
            for sheet_row, name in enumerate(worksheet.col_values(1), start=1):
                if extract_code(name) in changed_codes:
                    normalized_rows.append(sheet_row)
        normalized_rows = sorted(set(normalized_rows))

        ranges = [f"A{row_number}:GT{row_number}" for row_number in normalized_rows]
        value_ranges = worksheet.batch_get(ranges)
        numbered_rows = [
            (row_number, value_range[0] if value_range else [])
            for row_number, value_range in zip(normalized_rows, value_ranges)
        ]

    prepared_rows = _merge_operator_rows(numbered_rows)
    formatted_data = []
    for row, source_rows, operator_code, source_hash in prepared_rows:
        formatted_data.append({
            '_operator_code': operator_code,
            '_source_rows': source_rows,
            '_source_hash': source_hash,
            'name': row[0] if len(row) > 0 else "",
            'bl': row[2] if len(row) > 2 else "",
            'group': row[3] if len(row) > 3 else "",
            'mark': row[5] if len(row) > 5 else "",

            'code1': row[6] if len(row) > 6 else "",
            'code2': row[7] if len(row) > 7 else "",
            'code3': row[8] if len(row) > 8 else "",
            'code4': row[9] if len(row) > 9 else "",
            'code5': row[10] if len(row) > 10 else "",
            'code6': row[11] if len(row) > 11 else "",
            'code7': row[12] if len(row) > 12 else "",
            'code8': row[13] if len(row) > 13 else "",
            'code9': row[14] if len(row) > 14 else "",
            'code10': row[15] if len(row) > 15 else "",

            'call1': row[16] if len(row) > 16 else "",
            'call2': row[17] if len(row) > 17 else "",
            'call3': row[18] if len(row) > 18 else "",
            'call4': row[19] if len(row) > 19 else "",
            'call5': row[20] if len(row) > 20 else "",
            'call6': row[21] if len(row) > 21 else "",
            'call7': row[22] if len(row) > 22 else "",
            'call8': row[23] if len(row) > 23 else "",
            'call9': row[24] if len(row) > 24 else "",
            'call10': row[25] if len(row) > 25 else "",

            'service1': row[26] if len(row) > 26 else "",
            'service2': row[27] if len(row) > 27 else "",
            'service3': row[28] if len(row) > 28 else "",
            'service4': row[29] if len(row) > 29 else "",
            'service5': row[30] if len(row) > 30 else "",
            'service6': row[31] if len(row) > 31 else "",
            'service7': row[32] if len(row) > 32 else "",
            'service8': row[33] if len(row) > 33 else "",
            'service9': row[34] if len(row) > 34 else "",
            'service10': row[35] if len(row) > 35 else "",

            'greeting1': safe_convert(row[36]) if len(row) > 36 else None,
            'greeting2': safe_convert(row[37]) if len(row) > 37 else None,
            'greeting3': safe_convert(row[38]) if len(row) > 38 else None,
            'greeting4': safe_convert(row[39]) if len(row) > 39 else None,
            'greeting5': safe_convert(row[40]) if len(row) > 40 else None,
            'greeting6': safe_convert(row[41]) if len(row) > 41 else None,
            'greeting7': safe_convert(row[42]) if len(row) > 42 else None,
            'greeting8': safe_convert(row[43]) if len(row) > 43 else None,
            'greeting9': safe_convert(row[44]) if len(row) > 44 else None,
            'greeting10': safe_convert(row[45]) if len(row) > 45 else None,

            'hearing1': safe_convert(row[46]) if len(row) > 46 else None,
            'hearing2': safe_convert(row[47]) if len(row) > 47 else None,
            'hearing3': safe_convert(row[48]) if len(row) > 48 else None,
            'hearing4': safe_convert(row[49]) if len(row) > 49 else None,
            'hearing5': safe_convert(row[50]) if len(row) > 50 else None,
            'hearing6': safe_convert(row[51]) if len(row) > 51 else None,
            'hearing7': safe_convert(row[52]) if len(row) > 52 else None,
            'hearing8': safe_convert(row[53]) if len(row) > 53 else None,
            'hearing9': safe_convert(row[54]) if len(row) > 54 else None,
            'hearing10': safe_convert(row[55]) if len(row) > 55 else None,

            'question1': safe_convert(row[56]) if len(row) > 56 else None,
            'question2': safe_convert(row[57]) if len(row) > 57 else None,
            'question3': safe_convert(row[58]) if len(row) > 58 else None,
            'question4': safe_convert(row[59]) if len(row) > 59 else None,
            'question5': safe_convert(row[60]) if len(row) > 60 else None,
            'question6': safe_convert(row[61]) if len(row) > 61 else None,
            'question7': safe_convert(row[62]) if len(row) > 62 else None,
            'question8': safe_convert(row[63]) if len(row) > 63 else None,
            'question9': safe_convert(row[64]) if len(row) > 64 else None,
            'question10': safe_convert(row[65]) if len(row) > 65 else None,

            'interest1': safe_convert(row[66]) if len(row) > 66 else None,
            'interest2': safe_convert(row[67]) if len(row) > 67 else None,
            'interest3': safe_convert(row[68]) if len(row) > 68 else None,
            'interest4': safe_convert(row[69]) if len(row) > 69 else None,
            'interest5': safe_convert(row[70]) if len(row) > 70 else None,
            'interest6': safe_convert(row[71]) if len(row) > 71 else None,
            'interest7': safe_convert(row[72]) if len(row) > 72 else None,
            'interest8': safe_convert(row[73]) if len(row) > 73 else None,
            'interest9': safe_convert(row[74]) if len(row) > 74 else None,
            'interest10': safe_convert(row[75]) if len(row) > 75 else None,

            'cons1': safe_convert(row[76]) if len(row) > 76 else None,
            'cons2': safe_convert(row[77]) if len(row) > 77 else None,
            'cons3': safe_convert(row[78]) if len(row) > 78 else None,
            'cons4': safe_convert(row[79]) if len(row) > 79 else None,
            'cons5': safe_convert(row[80]) if len(row) > 80 else None,
            'cons6': safe_convert(row[81]) if len(row) > 81 else None,
            'cons7': safe_convert(row[82]) if len(row) > 82 else None,
            'cons8': safe_convert(row[83]) if len(row) > 83 else None,
            'cons9': safe_convert(row[84]) if len(row) > 84 else None,
            'cons10': safe_convert(row[85]) if len(row) > 85 else None,

            'polite1': safe_convert(row[86]) if len(row) > 86 else None,
            'polite2': safe_convert(row[87]) if len(row) > 87 else None,
            'polite3': safe_convert(row[88]) if len(row) > 88 else None,
            'polite4': safe_convert(row[89]) if len(row) > 89 else None,
            'polite5': safe_convert(row[90]) if len(row) > 90 else None,
            'polite6': safe_convert(row[91]) if len(row) > 91 else None,
            'polite7': safe_convert(row[92]) if len(row) > 92 else None,
            'polite8': safe_convert(row[93]) if len(row) > 93 else None,
            'polite9': safe_convert(row[94]) if len(row) > 94 else None,
            'polite10': safe_convert(row[95]) if len(row) > 95 else None,

            'speech1': safe_convert(row[96]) if len(row) > 96 else None,
            'speech2': safe_convert(row[97]) if len(row) > 97 else None,
            'speech3': safe_convert(row[98]) if len(row) > 98 else None,
            'speech4': safe_convert(row[99]) if len(row) > 99 else None,
            'speech5': safe_convert(row[100]) if len(row) > 100 else None,
            'speech6': safe_convert(row[101]) if len(row) > 101 else None,
            'speech7': safe_convert(row[102]) if len(row) > 102 else None,
            'speech8': safe_convert(row[103]) if len(row) > 103 else None,
            'speech9': safe_convert(row[104]) if len(row) > 104 else None,
            'speech10': safe_convert(row[105]) if len(row) > 105 else None,

            'note1': safe_convert(row[106]) if len(row) > 106 else None,
            'note2': safe_convert(row[107]) if len(row) > 107 else None,
            'note3': safe_convert(row[108]) if len(row) > 108 else None,
            'note4': safe_convert(row[109]) if len(row) > 109 else None,
            'note5': safe_convert(row[110]) if len(row) > 110 else None,
            'note6': safe_convert(row[111]) if len(row) > 111 else None,
            'note7': safe_convert(row[112]) if len(row) > 112 else None,
            'note8': safe_convert(row[113]) if len(row) > 113 else None,
            'note9': safe_convert(row[114]) if len(row) > 114 else None,
            'note10': safe_convert(row[115]) if len(row) > 115 else None,

            'warning1': safe_convert(row[116]) if len(row) > 116 else None,
            'warning2': safe_convert(row[117]) if len(row) > 117 else None,
            'warning3': safe_convert(row[118]) if len(row) > 118 else None,
            'warning4': safe_convert(row[119]) if len(row) > 119 else None,
            'warning5': safe_convert(row[120]) if len(row) > 120 else None,
            'warning6': safe_convert(row[121]) if len(row) > 121 else None,
            'warning7': safe_convert(row[122]) if len(row) > 122 else None,
            'warning8': safe_convert(row[123]) if len(row) > 123 else None,
            'warning9': safe_convert(row[124]) if len(row) > 124 else None,
            'warning10': safe_convert(row[125]) if len(row) > 125 else None,

            'emotion1': safe_convert(row[126]) if len(row) > 126 else None,
            'emotion2': safe_convert(row[127]) if len(row) > 127 else None,
            'emotion3': safe_convert(row[128]) if len(row) > 128 else None,
            'emotion4': safe_convert(row[129]) if len(row) > 129 else None,
            'emotion5': safe_convert(row[130]) if len(row) > 130 else None,
            'emotion6': safe_convert(row[131]) if len(row) > 131 else None,
            'emotion7': safe_convert(row[132]) if len(row) > 132 else None,
            'emotion8': safe_convert(row[133]) if len(row) > 133 else None,
            'emotion9': safe_convert(row[134]) if len(row) > 134 else None,
            'emotion10': safe_convert(row[135]) if len(row) > 135 else None,

            'solution1': safe_convert(row[136]) if len(row) > 136 else None,
            'solution2': safe_convert(row[137]) if len(row) > 137 else None,
            'solution3': safe_convert(row[138]) if len(row) > 138 else None,
            'solution4': safe_convert(row[139]) if len(row) > 139 else None,
            'solution5': safe_convert(row[140]) if len(row) > 140 else None,
            'solution6': safe_convert(row[141]) if len(row) > 141 else None,
            'solution7': safe_convert(row[142]) if len(row) > 142 else None,
            'solution8': safe_convert(row[143]) if len(row) > 143 else None,
            'solution9': safe_convert(row[144]) if len(row) > 144 else None,
            'solution10': safe_convert(row[145]) if len(row) > 145 else None,

            'dialog1': row[146] if len(row) > 146 else None,
            'dialog2': row[147] if len(row) > 147 else None,
            'dialog3': row[148] if len(row) > 148 else None,
            'dialog4': row[149] if len(row) > 149 else None,
            'dialog5': row[150] if len(row) > 150 else None,
            'dialog6': row[151] if len(row) > 151 else None,
            'dialog7': row[152] if len(row) > 152 else None,
            'dialog8': row[153] if len(row) > 153 else None,
            'dialog9': row[154] if len(row) > 154 else None,
            'dialog10': row[155] if len(row) > 155 else None,

            'comment1': row[187] if len(row) > 187 else "",
            'comment2': row[188] if len(row) > 188 else "",
            'comment3': row[189] if len(row) > 189 else "",
            'comment4': row[190] if len(row) > 190 else "",
            'comment5': row[191] if len(row) > 191 else "",
            'comment6': row[192] if len(row) > 192 else "",
            'comment7': row[193] if len(row) > 193 else "",
            'comment8': row[194] if len(row) > 194 else "",
            'comment9': row[195] if len(row) > 195 else "",
            'comment10': row[196] if len(row) > 196 else "",

            'mis1': safe_convert(row[197]) if len(row) > 197 else None,
            'mis2': safe_convert(row[198]) if len(row) > 198 else None,
            'mis3': safe_convert(row[199]) if len(row) > 199 else None,

            'month': row[201] if len(row) > 201 else None,
        })


    updated_count = 0
    active_ids = []
    for record in formatted_data:
        if not is_valid_name(record['name']):
            print(f"Пропущено: имя без номера — {record['name']}")
            continue

        mark_value = safe_convert_decimal(record['mark'])
        if mark_value == 0:
            mark_value = None
        active_match = CallData.objects.filter(
            operator_code=record['_operator_code'], is_active=True
        ).first()
        lookup = {'pk': active_match.pk} if active_match else {'name': record['name']}
        call_data, created = CallData.objects.update_or_create(
            **lookup,
            defaults={
                'name': record['name'],
                'operator_code': record['_operator_code'],
                'source_rows': record['_source_rows'],
                'source_hash': record['_source_hash'],
                'source_updated_at': timezone.now(),
                'is_active': True,
                'bl': record['bl'],
                'group': record['group'],
                'mark': mark_value,

                'code1': record['code1'],
                'code2': record['code2'],
                'code3': record['code3'],
                'code4': record['code4'],
                'code5': record['code5'],
                'code6': record['code6'],
                'code7': record['code7'],
                'code8': record['code8'],
                'code9': record['code9'],
                'code10': record['code10'],

                'call1': record['call1'],
                'call2': record['call2'],
                'call3': record['call3'],
                'call4': record['call4'],
                'call5': record['call5'],
                'call6': record['call6'],
                'call7': record['call7'],
                'call8': record['call8'],
                'call9': record['call9'],
                'call10': record['call10'],

                'service1': record['service1'],
                'service2': record['service2'],
                'service3': record['service3'],
                'service4': record['service4'],
                'service5': record['service5'],
                'service6': record['service6'],
                'service7': record['service7'],
                'service8': record['service8'],
                'service9': record['service9'],
                'service10': record['service10'],

                'greeting1': record['greeting1'],
                'greeting2': record['greeting2'],
                'greeting3': record['greeting3'],
                'greeting4': record['greeting4'],
                'greeting5': record['greeting5'],
                'greeting6': record['greeting6'],
                'greeting7': record['greeting7'],
                'greeting8': record['greeting8'],
                'greeting9': record['greeting9'],
                'greeting10': record['greeting10'],

                'hearing1': record['hearing1'],
                'hearing2': record['hearing2'],
                'hearing3': record['hearing3'],
                'hearing4': record['hearing4'],
                'hearing5': record['hearing5'],
                'hearing6': record['hearing6'],
                'hearing7': record['hearing7'],
                'hearing8': record['hearing8'],
                'hearing9': record['hearing9'],
                'hearing10': record['hearing10'],

                'question1': record['question1'],
                'question2': record['question2'],
                'question3': record['question3'],
                'question4': record['question4'],
                'question5': record['question5'],
                'question6': record['question6'],
                'question7': record['question7'],
                'question8': record['question8'],
                'question9': record['question9'],
                'question10': record['question10'],

                'interest1': record['interest1'],
                'interest2': record['interest2'],
                'interest3': record['interest3'],
                'interest4': record['interest4'],
                'interest5': record['interest5'],
                'interest6': record['interest6'],
                'interest7': record['interest7'],
                'interest8': record['interest8'],
                'interest9': record['interest9'],
                'interest10': record['interest10'],

                'cons1': record['cons1'],
                'cons2': record['cons2'],
                'cons3': record['cons3'],
                'cons4': record['cons4'],
                'cons5': record['cons5'],
                'cons6': record['cons6'],
                'cons7': record['cons7'],
                'cons8': record['cons8'],
                'cons9': record['cons9'],
                'cons10': record['cons10'],

                'polite1': record['polite1'],
                'polite2': record['polite2'],
                'polite3': record['polite3'],
                'polite4': record['polite4'],
                'polite5': record['polite5'],
                'polite6': record['polite6'],
                'polite7': record['polite7'],
                'polite8': record['polite8'],
                'polite9': record['polite9'],
                'polite10': record['polite10'],

                'speech1': record['speech1'],
                'speech2': record['speech2'],
                'speech3': record['speech3'],
                'speech4': record['speech4'],
                'speech5': record['speech5'],
                'speech6': record['speech6'],
                'speech7': record['speech7'],
                'speech8': record['speech8'],
                'speech9': record['speech9'],
                'speech10': record['speech10'],

                'note1': record['note1'],
                'note2': record['note2'],
                'note3': record['note3'],
                'note4': record['note4'],
                'note5': record['note5'],
                'note6': record['note6'],
                'note7': record['note7'],
                'note8': record['note8'],
                'note9': record['note9'],
                'note10': record['note10'],

                'warning1': record['warning1'],
                'warning2': record['warning2'],
                'warning3': record['warning3'],
                'warning4': record['warning4'],
                'warning5': record['warning5'],
                'warning6': record['warning6'],
                'warning7': record['warning7'],
                'warning8': record['warning8'],
                'warning9': record['warning9'],
                'warning10': record['warning10'],

                'emotion1': record['emotion1'],
                'emotion2': record['emotion2'],
                'emotion3': record['emotion3'],
                'emotion4': record['emotion4'],
                'emotion5': record['emotion5'],
                'emotion6': record['emotion6'],
                'emotion7': record['emotion7'],
                'emotion8': record['emotion8'],
                'emotion9': record['emotion9'],
                'emotion10': record['emotion10'],

                'solution1': record['solution1'],
                'solution2': record['solution2'],
                'solution3': record['solution3'],
                'solution4': record['solution4'],
                'solution5': record['solution5'],
                'solution6': record['solution6'],
                'solution7': record['solution7'],
                'solution8': record['solution8'],
                'solution9': record['solution9'],
                'solution10': record['solution10'],

                'dialog1': safe_convert_decimal(record['dialog1']),
                'dialog2': safe_convert_decimal(record['dialog2']),
                'dialog3': safe_convert_decimal(record['dialog3']),
                'dialog4': safe_convert_decimal(record['dialog4']),
                'dialog5': safe_convert_decimal(record['dialog5']),
                'dialog6': safe_convert_decimal(record['dialog6']),
                'dialog7': safe_convert_decimal(record['dialog7']),
                'dialog8': safe_convert_decimal(record['dialog8']),
                'dialog9': safe_convert_decimal(record['dialog9']),
                'dialog10': safe_convert_decimal(record['dialog10']),

                'comment1': record['comment1'],
                'comment2': record['comment2'],
                'comment3': record['comment3'],
                'comment4': record['comment4'],
                'comment5': record['comment5'],
                'comment6': record['comment6'],
                'comment7': record['comment7'],
                'comment8': record['comment8'],
                'comment9': record['comment9'],
                'comment10': record['comment10'],

                'mis1': record['mis1'],
                'mis2': record['mis2'],
                'mis3': record['mis3'],

                'month': record['month'],
            }
        )
        updated_count += 1
        active_ids.append(call_data.pk)
        if record['_operator_code']:
            CallData.objects.filter(
                operator_code=record['_operator_code']
            ).exclude(pk=call_data.pk).update(is_active=False)



    if is_full_sync:
        CallData.objects.exclude(pk__in=active_ids).update(is_active=False)

    return updated_count

def extract_code(name):
    if not isinstance(name, str):
        return None
    match = re.search(r'\((\d+)\)', name)
    return match.group(1) if match else None

def correct_name_from_calldata(name_from_sheet):
    if not isinstance(name_from_sheet, str):
        return None

    sheet_code = extract_code(name_from_sheet)
    if not sheet_code:
        return name_from_sheet

    operator = CallData.objects.filter(is_active=True, operator_code=sheet_code).first()
    if operator:
        print(f"🔎 Найден правильный оператор для кода {sheet_code}: {operator.name}")
        return operator.name
    else:
        print(f"⚠️ Оператор с кодом {sheet_code} не найден. Оставляем исходное ФИО.")
        return name_from_sheet

def get_archive():
    print("Проверка существующих месяцев в БД...")
    client = gspread.authorize(get_credentials())
    spreadsheet = client.open('ЛК сайт')
    worksheet = spreadsheet.worksheet('Архив')
    data = worksheet.get('A2:GT')

    for source_row, row in enumerate(data, start=2):
        original_name = row[0].strip() if len(row) > 0 else None
        name = correct_name_from_calldata(original_name)
        if not is_valid_name(name):
            print(f"ФИО без номера — {name}")
            continue

        month = row[201].strip() if len(row) > 201 else None
        if not month:
            print(f"Пропущено: отсутствует месяц для {name}")
            continue

        mark = row[5].strip() if len(row) > 5 else None
        mark_decimal = safe_convert_decimal(mark)
        if mark_decimal == 0:
            mark_decimal = None

        bl = row[2] if len(row) > 2 else ""
        group = row[3] if len(row) > 3 else ""

        operator_code = extract_code(name)
        operator = (
            CallData.objects.filter(
                is_active=True, operator_code=operator_code
            ).first()
            or CallData.objects.filter(operator_code=operator_code).first()
            or CallData.objects.filter(name=name).first()
        )
        if not operator:
            print(f"Оператор с именем '{name}' не найден в CallData. Создаём нового оператора.")
            operator = CallData.objects.create(
                name=name, operator_code=operator_code, bl="", group="", is_active=True
            )

        source_payload = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        archive_values = dict(
            name=name,
            operator_code=operator_code,
            source_row=source_row,
            source_hash=hashlib.sha256(source_payload.encode("utf-8")).hexdigest(),
            source_updated_at=timezone.now(),
            operator=operator,
            mark=mark_decimal,
            group=group,
            bl=bl,
            month=month,
            code1=row[6] if len(row) > 6 else "",
            code2=row[7] if len(row) > 7 else "",
            code3=row[8] if len(row) > 8 else "",
            code4=row[9] if len(row) > 9 else "",
            code5=row[10] if len(row) > 10 else "",
            code6=row[11] if len(row) > 11 else "",
            code7=row[12] if len(row) > 12 else "",
            code8=row[13] if len(row) > 13 else "",
            code9=row[14] if len(row) > 14 else "",
            code10=row[15] if len(row) > 15 else "",
            call1=row[16] if len(row) > 16 else "",
            call2=row[17] if len(row) > 17 else "",
            call3=row[18] if len(row) > 18 else "",
            call4=row[19] if len(row) > 19 else "",
            call5=row[20] if len(row) > 20 else "",
            call6=row[21] if len(row) > 21 else "",
            call7=row[22] if len(row) > 22 else "",
            call8=row[23] if len(row) > 23 else "",
            call9=row[24] if len(row) > 24 else "",
            call10=row[25] if len(row) > 25 else "",
            service1=row[26] if len(row) > 26 else "",
            service2=row[27] if len(row) > 27 else "",
            service3=row[28] if len(row) > 28 else "",
            service4=row[29] if len(row) > 29 else "",
            service5=row[30] if len(row) > 30 else "",
            service6=row[31] if len(row) > 31 else "",
            service7=row[32] if len(row) > 32 else "",
            service8=row[33] if len(row) > 33 else "",
            service9=row[34] if len(row) > 34 else "",
            service10=row[35] if len(row) > 35 else "",
            greeting1=safe_convert(row[36]) if len(row) > 36 else None,
            greeting2=safe_convert(row[37]) if len(row) > 37 else None,
            greeting3=safe_convert(row[38]) if len(row) > 38 else None,
            greeting4=safe_convert(row[39]) if len(row) > 39 else None,
            greeting5=safe_convert(row[40]) if len(row) > 40 else None,
            greeting6=safe_convert(row[41]) if len(row) > 41 else None,
            greeting7=safe_convert(row[42]) if len(row) > 42 else None,
            greeting8=safe_convert(row[43]) if len(row) > 43 else None,
            greeting9=safe_convert(row[44]) if len(row) > 44 else None,
            greeting10=safe_convert(row[45]) if len(row) > 45 else None,
            hearing1=safe_convert(row[46]) if len(row) > 46 else None,
            hearing2=safe_convert(row[47]) if len(row) > 47 else None,
            hearing3=safe_convert(row[48]) if len(row) > 48 else None,
            hearing4=safe_convert(row[49]) if len(row) > 49 else None,
            hearing5=safe_convert(row[50]) if len(row) > 50 else None,
            hearing6=safe_convert(row[51]) if len(row) > 51 else None,
            hearing7=safe_convert(row[52]) if len(row) > 52 else None,
            hearing8=safe_convert(row[53]) if len(row) > 53 else None,
            hearing9=safe_convert(row[54]) if len(row) > 54 else None,
            hearing10=safe_convert(row[55]) if len(row) > 55 else None,
            question1=safe_convert(row[56]) if len(row) > 56 else None,
            question2=safe_convert(row[57]) if len(row) > 57 else None,
            question3=safe_convert(row[58]) if len(row) > 58 else None,
            question4=safe_convert(row[59]) if len(row) > 59 else None,
            question5=safe_convert(row[60]) if len(row) > 60 else None,
            question6=safe_convert(row[61]) if len(row) > 61 else None,
            question7=safe_convert(row[62]) if len(row) > 62 else None,
            question8=safe_convert(row[63]) if len(row) > 63 else None,
            question9=safe_convert(row[64]) if len(row) > 64 else None,
            question10=safe_convert(row[65]) if len(row) > 65 else None,
            interest1=safe_convert(row[66]) if len(row) > 66 else None,
            interest2=safe_convert(row[67]) if len(row) > 67 else None,
            interest3=safe_convert(row[68]) if len(row) > 68 else None,
            interest4=safe_convert(row[69]) if len(row) > 69 else None,
            interest5=safe_convert(row[70]) if len(row) > 70 else None,
            interest6=safe_convert(row[71]) if len(row) > 71 else None,
            interest7=safe_convert(row[72]) if len(row) > 72 else None,
            interest8=safe_convert(row[73]) if len(row) > 73 else None,
            interest9=safe_convert(row[74]) if len(row) > 74 else None,
            interest10=safe_convert(row[75]) if len(row) > 75 else None,
            cons1=safe_convert(row[76]) if len(row) > 76 else None,
            cons2=safe_convert(row[77]) if len(row) > 77 else None,
            cons3=safe_convert(row[78]) if len(row) > 78 else None,
            cons4=safe_convert(row[79]) if len(row) > 79 else None,
            cons5=safe_convert(row[80]) if len(row) > 80 else None,
            cons6=safe_convert(row[81]) if len(row) > 81 else None,
            cons7=safe_convert(row[82]) if len(row) > 82 else None,
            cons8=safe_convert(row[83]) if len(row) > 83 else None,
            cons9=safe_convert(row[84]) if len(row) > 84 else None,
            cons10=safe_convert(row[85]) if len(row) > 85 else None,
            polite1=safe_convert(row[86]) if len(row) > 86 else None,
            polite2=safe_convert(row[87]) if len(row) > 87 else None,
            polite3=safe_convert(row[88]) if len(row) > 88 else None,
            polite4=safe_convert(row[89]) if len(row) > 89 else None,
            polite5=safe_convert(row[90]) if len(row) > 90 else None,
            polite6=safe_convert(row[91]) if len(row) > 91 else None,
            polite7=safe_convert(row[92]) if len(row) > 92 else None,
            polite8=safe_convert(row[93]) if len(row) > 93 else None,
            polite9=safe_convert(row[94]) if len(row) > 94 else None,
            polite10=safe_convert(row[95]) if len(row) > 95 else None,
            speech1=safe_convert(row[96]) if len(row) > 96 else None,
            speech2=safe_convert(row[97]) if len(row) > 97 else None,
            speech3=safe_convert(row[98]) if len(row) > 98 else None,
            speech4=safe_convert(row[99]) if len(row) > 99 else None,
            speech5=safe_convert(row[100]) if len(row) > 100 else None,
            speech6=safe_convert(row[101]) if len(row) > 101 else None,
            speech7=safe_convert(row[102]) if len(row) > 102 else None,
            speech8=safe_convert(row[103]) if len(row) > 103 else None,
            speech9=safe_convert(row[104]) if len(row) > 104 else None,
            speech10=safe_convert(row[105]) if len(row) > 105 else None,
            note1=safe_convert(row[106]) if len(row) > 106 else None,
            note2=safe_convert(row[107]) if len(row) > 107 else None,
            note3=safe_convert(row[108]) if len(row) > 108 else None,
            note4=safe_convert(row[109]) if len(row) > 109 else None,
            note5=safe_convert(row[110]) if len(row) > 110 else None,
            note6=safe_convert(row[111]) if len(row) > 111 else None,
            note7=safe_convert(row[112]) if len(row) > 112 else None,
            note8=safe_convert(row[113]) if len(row) > 113 else None,
            note9=safe_convert(row[114]) if len(row) > 114 else None,
            note10=safe_convert(row[115]) if len(row) > 115 else None,
            warning1=safe_convert(row[116]) if len(row) > 116 else None,
            warning2=safe_convert(row[117]) if len(row) > 117 else None,
            warning3=safe_convert(row[118]) if len(row) > 118 else None,
            warning4=safe_convert(row[119]) if len(row) > 119 else None,
            warning5=safe_convert(row[120]) if len(row) > 120 else None,
            warning6=safe_convert(row[121]) if len(row) > 121 else None,
            warning7=safe_convert(row[122]) if len(row) > 122 else None,
            warning8=safe_convert(row[123]) if len(row) > 123 else None,
            warning9=safe_convert(row[124]) if len(row) > 124 else None,
            warning10=safe_convert(row[125]) if len(row) > 125 else None,
            emotion1=safe_convert(row[126]) if len(row) > 126 else None,
            emotion2=safe_convert(row[127]) if len(row) > 127 else None,
            emotion3=safe_convert(row[128]) if len(row) > 128 else None,
            emotion4=safe_convert(row[129]) if len(row) > 129 else None,
            emotion5=safe_convert(row[130]) if len(row) > 130 else None,
            emotion6=safe_convert(row[131]) if len(row) > 131 else None,
            emotion7=safe_convert(row[132]) if len(row) > 132 else None,
            emotion8=safe_convert(row[133]) if len(row) > 133 else None,
            emotion9=safe_convert(row[134]) if len(row) > 134 else None,
            emotion10=safe_convert(row[135]) if len(row) > 135 else None,
            solution1=safe_convert(row[136]) if len(row) > 136 else None,
            solution2=safe_convert(row[137]) if len(row) > 137 else None,
            solution3=safe_convert(row[138]) if len(row) > 138 else None,
            solution4=safe_convert(row[139]) if len(row) > 139 else None,
            solution5=safe_convert(row[140]) if len(row) > 140 else None,
            solution6=safe_convert(row[141]) if len(row) > 141 else None,
            solution7=safe_convert(row[142]) if len(row) > 142 else None,
            solution8=safe_convert(row[143]) if len(row) > 143 else None,
            solution9=safe_convert(row[144]) if len(row) > 144 else None,
            solution10=safe_convert(row[145]) if len(row) > 145 else None,
            dialog1=safe_convert_decimal(row[146]) if len(row) > 146 else None,
            dialog2=safe_convert_decimal(row[147]) if len(row) > 147 else None,
            dialog3=safe_convert_decimal(row[148]) if len(row) > 148 else None,
            dialog4=safe_convert_decimal(row[149]) if len(row) > 149 else None,
            dialog5=safe_convert_decimal(row[150]) if len(row) > 150 else None,
            dialog6=safe_convert_decimal(row[151]) if len(row) > 151 else None,
            dialog7=safe_convert_decimal(row[152]) if len(row) > 152 else None,
            dialog8=safe_convert_decimal(row[153]) if len(row) > 153 else None,
            dialog9=safe_convert_decimal(row[154]) if len(row) > 154 else None,
            dialog10=safe_convert_decimal(row[155]) if len(row) > 155 else None,
            comment1=row[187] if len(row) > 187 else "",
            comment2=row[188] if len(row) > 188 else "",
            comment3=row[189] if len(row) > 189 else "",
            comment4=row[190] if len(row) > 190 else "",
            comment5=row[191] if len(row) > 191 else "",
            comment6=row[192] if len(row) > 192 else "",
            comment7=row[193] if len(row) > 193 else "",
            comment8=row[194] if len(row) > 194 else "",
            comment9=row[195] if len(row) > 195 else "",
            comment10=row[196] if len(row) > 196 else "",
            mis1=safe_convert(row[197]) if len(row) > 197 else None,
            mis2=safe_convert(row[198]) if len(row) > 198 else None,
            mis3=safe_convert(row[199]) if len(row) > 199 else None
        )

        archive_record = ScoresForMonth.objects.filter(source_row=source_row).first()
        if archive_record is None:
            # Legacy imports do not have source_row. Match once using stable fields.
            archive_record = ScoresForMonth.objects.filter(
                source_row__isnull=True,
                operator_code=operator_code,
                month=month,
            ).first()

        if archive_record is None:
            ScoresForMonth.objects.create(**archive_values)
            action = "created"
        else:
            for field, value in archive_values.items():
                setattr(archive_record, field, value)
            archive_record.save(update_fields=list(archive_values))
            action = "updated"
        print(f"Archive record {action}: {name} ({month})")
    print("Импорт завершён.")



