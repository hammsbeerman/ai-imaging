from django.contrib import admin
from .models import Image, AccessRoot, UserAccessRoot, IndexerSettings


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ("filename", "indexed", "ext", "size", "root")
    search_fields = ("filename", "path", "text")
    list_filter = ("indexed", "ext", "root")


@admin.register(AccessRoot)
class AccessRootAdmin(admin.ModelAdmin):
    list_display = ("name", "scan_path_root")
    search_fields = ("name", "scan_path_root")


@admin.register(UserAccessRoot)
class UserAccessRootAdmin(admin.ModelAdmin):
    list_display = ("user", "root")
    search_fields = ("user__username", "root__name")


@admin.register(IndexerSettings)
class IndexerSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "enabled",
        "scan_path",
        "index_batch_size",
        "enrich_batch_size",
        "scan_interval_seconds",
        "index_interval_seconds",
        "enrich_interval_seconds",
        "preview_size",
        "updated",
    )