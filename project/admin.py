import os  
from django.contrib import admin
from .models import *
from django.utils.html import format_html
from urllib.parse import quote  


@admin.action(description="Скрыть: не показывать в поиске и не слать в WFM")
def hide_operators(modeladmin, request, queryset):
    modeladmin.message_user(request, f"Скрыто: {queryset.update(is_excluded=True)}")


@admin.action(description="Показать снова")
def unhide_operators(modeladmin, request, queryset):
    modeladmin.message_user(request, f"Возвращено: {queryset.update(is_excluded=False)}")


class CallDataAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'get_photo_preview', 'bl', 'group', 'mark', 'month',
        'is_active', 'is_excluded',
    )
    list_filter = ('is_excluded', 'is_active')
    list_editable = ('is_excluded',)
    actions = (hide_operators, unhide_operators)
    search_fields = ('name',)
    ordering = ('name',)
    def get_photo_preview(self, obj):
        if obj.photo:
            filename = os.path.basename(obj.photo.name)
            url = f"/secure-photo/{quote(filename)}"
            return format_html(f'<img src="{url}" style="max-height:100px;"/>')
        return "-"
    
    get_photo_preview.short_description = "Фото"

class ScoresForMonthAdmin(admin.ModelAdmin):
    list_display = ('name', 'operator', 'id','mark','month') 
    search_fields = ('name',)  
    list_filter = ('operator',)
    ordering = ('name',)  

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.order_by('name')

class ManagementAdmin(admin.ModelAdmin):
    list_display = ['title','pdf_file','created_at']


class ScheduleAdmin(admin.ModelAdmin):
        list_display = ['code','title','pdf_file','created_at']

class BackgroundImageAdmin(admin.ModelAdmin):
    list_display = ['id', 'image', 'order']
    ordering = ['order']


class RecordsAdmin(admin.ModelAdmin):
     list_display = ['call_code','operator','status','attempts','audio_key','created_at']
     list_filter = ['status']
     search_fields = ['call_code']
     readonly_fields = ['audio_key','created_at']

     # Audio tiklab bo'lmaydi (manba API eski qo'ng'iroqlarni bermaydi),
     # shuning uchun admin orqali tasodifiy o'chirish yopiq.
     def has_delete_permission(self, request, obj=None):
         return False

admin.site.register(CallData, CallDataAdmin)
admin.site.register(ScoresForMonth,ScoresForMonthAdmin)

admin.site.register(Schedule,ScheduleAdmin)
admin.site.register(Management,ManagementAdmin)
admin.site.register(BackgroundImage,BackgroundImageAdmin)
admin.site.register(Records,RecordsAdmin)


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ip_address",
        "method",
        "path",
        "created_at",
    )

    list_filter = (
        "method",
        "path",
        "created_at",
    )

    search_fields = (
        "ip_address",
        "path",
    )

    ordering = ("-created_at",)

    readonly_fields = (
        "ip_address",
        "method",
        "path",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False



@admin.register(CalendarOpenLog)
class CalendarOpenLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "operator_name",
        "client_ip",
        "short_url",
        "opened_at",
    )

    search_fields = (
        "operator_name",
        "client_ip",
    )

    list_filter = (
        "opened_at",
    )

    ordering = ("-opened_at",)

    list_per_page = 50

    readonly_fields = (
        "operator_name",
        "client_ip",
        "api_request_url",
        "opened_at",
    )

    def short_url(self, obj):
        if obj.api_request_url:
            return obj.api_request_url[:50] + "..."
        return "-"
    short_url.short_description = "API URL"