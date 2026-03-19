from django.contrib import admin

from .models import Image, AccessRoot, UserAccessRoot, IndexerSettings
from .models_documents import Document, DocumentPage
from .models_mail import InboundEmail, InboundEmailAttachment


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ("filename", "indexed", "ext", "size", "root", "text_status", "preview_status")
    search_fields = ("filename", "path", "text", "extracted_text_clean", "sha256")
    list_filter = ("indexed", "ext", "root", "text_status", "preview_status")


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


class DocumentPageInline(admin.TabularInline):
    model = DocumentPage
    extra = 0
    readonly_fields = ("page_number", "width", "height", "created_at", "updated_at")
    show_change_link = True


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "original_filename",
        "document_type",
        "invoice_vendor",
        "review_status",
        "sync_status",
        "confidence_score",
        "is_duplicate",
        "updated_at",
    )
    search_fields = (
        "original_filename",
        "source_path",
        "extracted_text_search",
        "invoice_vendor",
        "invoice_number",
        "sha256",
    )
    list_filter = ("document_type", "review_status", "sync_status", "is_duplicate")
    readonly_fields = ("created_at", "updated_at", "synced_at")
    inlines = [DocumentPageInline]


class InboundEmailAttachmentInline(admin.TabularInline):
    model = InboundEmailAttachment
    extra = 0
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(InboundEmail)
class InboundEmailAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "from_email", "received_at", "status", "created_at")
    search_fields = ("subject", "from_email", "from_name", "body_text", "source_message_id")
    list_filter = ("status", "mailbox")
    inlines = [InboundEmailAttachmentInline]
