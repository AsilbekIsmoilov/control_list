from django.contrib import admin

from archive.models import Archive2025

class ArchiveAdmin(admin.ModelAdmin):
    list_display = ('name', 'operator', 'id','mark','month')
    search_fields = ('name',)
    list_filter = ('operator',)
    ordering = ('name',)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.order_by('name')


admin.site.register(Archive2025,ArchiveAdmin)