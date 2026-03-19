from django.conf import settings
from django.db import models

from indexer.models import Image


class Document(models.Model):
    REVIEW_PENDING = "pending"
    REVIEW_APPROVED = "approved"
    REVIEW_NEEDS_REVIEW = "needs_review"
    REVIEW_STATUS_CHOICES = [
        (REVIEW_PENDING, "Pending"),
        (REVIEW_APPROVED, "Approved"),
        (REVIEW_NEEDS_REVIEW, "Needs Review"),
    ]

    SYNC_PENDING = "pending"
    SYNC_PROCESSING = "processing"
    SYNC_OK = "ok"
    SYNC_ERROR = "error"
    SYNC_STATUS_CHOICES = [
        (SYNC_PENDING, "Pending"),
        (SYNC_PROCESSING, "Processing"),
        (SYNC_OK, "OK"),
        (SYNC_ERROR, "Error"),
    ]

    image = models.OneToOneField(
        Image,
        on_delete=models.CASCADE,
        related_name="document",
    )

    original_filename = models.CharField(max_length=500, blank=True, default="")
    source_path = models.TextField(blank=True, default="")
    file_ext = models.CharField(max_length=20, blank=True, default="", db_index=True)
    mime_type = models.CharField(max_length=120, blank=True, default="")
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    page_count = models.IntegerField(null=True, blank=True)

    title = models.CharField(max_length=500, blank=True, default="")
    document_type = models.CharField(max_length=120, blank=True, default="", db_index=True)
    correspondent = models.CharField(max_length=255, blank=True, default="", db_index=True)
    document_date = models.DateField(null=True, blank=True)

    ocr_text = models.TextField(blank=True, default="")
    ocr_text_preview = models.TextField(blank=True, default="")
    extracted_text_clean = models.TextField(blank=True, default="")
    extracted_text_search = models.TextField(blank=True, default="")
    extracted_text_summary = models.TextField(blank=True, default="")

    text_source = models.CharField(max_length=50, blank=True, default="", db_index=True)
    text_engine = models.CharField(max_length=50, blank=True, default="")
    text_confidence = models.FloatField(null=True, blank=True)
    text_length = models.IntegerField(default=0)
    text_language = models.CharField(max_length=20, blank=True, default="")

    detected_emails = models.JSONField(default=list, blank=True)
    detected_phones = models.JSONField(default=list, blank=True)
    detected_dates = models.JSONField(default=list, blank=True)
    detected_money = models.JSONField(default=list, blank=True)
    detected_keywords = models.JSONField(default=list, blank=True)

    invoice_number = models.CharField(max_length=128, blank=True, default="", db_index=True)
    invoice_total = models.CharField(max_length=64, blank=True, default="")
    invoice_due_date = models.CharField(max_length=64, blank=True, default="")
    invoice_vendor = models.CharField(max_length=255, blank=True, default="", db_index=True)

    duplicate_group = models.CharField(max_length=64, blank=True, default="", db_index=True)
    is_duplicate = models.BooleanField(default=False, db_index=True)

    confidence_score = models.FloatField(default=0)

    review_status = models.CharField(
        max_length=16,
        choices=REVIEW_STATUS_CHOICES,
        default=REVIEW_PENDING,
        db_index=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_documents",
    )

    sync_status = models.CharField(
        max_length=16,
        choices=SYNC_STATUS_CHOICES,
        default=SYNC_PENDING,
        db_index=True,
    )
    synced_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["document_type", "review_status"], name="doc_type_rev_idx"),
            models.Index(fields=["sync_status", "review_status"], name="doc_sync_rev_idx"),
            models.Index(fields=["duplicate_group", "is_duplicate"], name="doc_dupe_grp_idx"),
            models.Index(fields=["invoice_vendor", "invoice_number"], name="doc_inv_vendor_idx"),
        ]

    def __str__(self):
        return self.title or self.original_filename or f"Document {self.pk}"


class DocumentPage(models.Model):
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    page_number = models.PositiveIntegerField()
    text_raw = models.TextField(blank=True, default="")
    extracted_text_clean = models.TextField(blank=True, default="")
    extracted_text_search = models.TextField(blank=True, default="")
    text_summary = models.TextField(blank=True, default="")
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_number"]
        unique_together = [("document", "page_number")]

    def __str__(self):
        return f"Document {self.document_id} page {self.page_number}"
