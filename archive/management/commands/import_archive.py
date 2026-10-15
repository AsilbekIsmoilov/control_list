from django.core.management.base import BaseCommand

import gspread
from project.models import CallData
from archive.models import Archive2025
from project.sheets import (
    get_credentials,
    safe_convert,
    safe_convert_decimal,
    is_valid_name,
    correct_name_from_calldata,
)


class Command(BaseCommand):
    help = "Import Archive 2025 from Google Sheets"

    def handle(self, *args, **options):
        self.stdout.write("Archive2025 import boshlandi...")

        existing_months = set(
            Archive2025.objects.values_list("month", flat=True).distinct()
        )

        client = gspread.authorize(get_credentials())
        spreadsheet = client.open("ЛК сайт")
        worksheet = spreadsheet.worksheet("Архив (2025)")
        data = worksheet.get("A2:GT")

        for row in data:
            original_name = row[0].strip() if len(row) > 0 else None
            name = correct_name_from_calldata(original_name)

            if not is_valid_name(name):
                self.stdout.write(f"❌ FIO noto‘g‘ri: {name}")
                continue

            month = row[201].strip() if len(row) > 201 else None
            if not month or month in existing_months:
                continue

            operator, _ = CallData.objects.get_or_create(name=name)

            Archive2025.objects.create(
                operator=operator,
                name=name,
                month=month,
                mark=safe_convert_decimal(row[5]) or None,
                bl=row[2] if len(row) > 2 else "",
                group=row[3] if len(row) > 3 else "",

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
                mis3=safe_convert(row[199]) if len(row) > 199 else None,
            )

            self.stdout.write(f"✅ Yozildi: {name} ({month})")

        self.stdout.write(self.style.SUCCESS("Archive2025 import tugadi ✅"))