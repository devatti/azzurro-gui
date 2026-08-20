from django.contrib import admin

from .models import HistoricSample, ZCSConfiguration


@admin.register(HistoricSample)
class HistoricSampleAdmin(admin.ModelAdmin):
    list_display = ('thing_key', 'ts', 'created_at')
    list_filter = ('thing_key',)
    date_hierarchy = 'ts'
    search_fields = ('thing_key',)


@admin.register(ZCSConfiguration)
class ZCSConfigurationAdmin(admin.ModelAdmin):
    list_display = ('id', 'url', 'thing_key_enc', 'client_code_enc', 'auth_code_enc', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False