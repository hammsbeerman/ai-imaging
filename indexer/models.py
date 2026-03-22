from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


class AccessRoot(models.Model):
    name = models.CharField(max_length=200)
    scan_path_root = models.CharField(max_length=1000, unique=True)

    open_folder_unc_base = models.CharField(
        max_length=1000, blank=True, null=True,
        help_text=r"Example: \\files\vmstore\Archive\Customers"
    )
    open_folder_smb_base = models.CharField(
        max_length=1000, blank=True, null=True,
        help_text="Example: smb://files/vmstore/Archive/Customers"
    )

    def __str__(self):
        return self.name


class UserAccessRoot(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    root = models.ForeignKey(AccessRoot, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("user", "root")

    def __str__(self):
        return f"{self.user.username} -> {self.root.name}"


class IndexerSettings(models.Model):
    enabled = models.BooleanField(default=True)

    scan_path = models.CharField(max_length=1000, default="/mnt/archive")

    index_batch_size = models.IntegerField(default=50)
    enrich_batch_size = models.IntegerField(default=200)

    scan_interval_seconds = models.IntegerField(default=900)
    index_interval_seconds = models.IntegerField(default=10)
    enrich_interval_seconds = models.IntegerField(default=60)

    preview_size = models.IntegerField(default=512)

    open_folder_unc_base = models.CharField(
        max_length=1000, blank=True, null=True,
        help_text=r"Example: \\files\vmstore\Archive"
    )
    open_folder_smb_base = models.CharField(
        max_length=1000, blank=True, null=True,
        help_text="Example: smb://files/vmstore/Archive"
    )

    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Indexer Settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class PreviewStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    OK = "ok", "OK"
    FAILED = "failed", "Failed"
    UNSUPPORTED = "unsupported", "Unsupported"


class ProcessingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    OK = "ok", "OK"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    UNSUPPORTED = "unsupported", "Unsupported"


class Image(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    path = models.TextField(unique=True)
    filename = models.CharField(max_length=500)

    size = models.BigIntegerField(null=True, blank=True)
    ext = models.CharField(max_length=20, blank=True, null=True)
    mtime = models.DateTimeField(blank=True, null=True)

    text = models.TextField(blank=True, null=True)

    indexed = models.BooleanField(default=False, db_index=True)
    skip_index = models.BooleanField(default=False, db_index=True)

    root = models.ForeignKey(AccessRoot, null=True, blank=True, on_delete=models.SET_NULL)

    created = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    file_ext = models.CharField(max_length=20, blank=True, default="", db_index=True)
    mime_type = models.CharField(max_length=120, blank=True, default="")
    preview_path = models.TextField(blank=True, default="")
    thumb_path = models.TextField(blank=True, default="")
    preview_status = models.CharField(
        max_length=20,
        choices=PreviewStatus.choices,
        default=PreviewStatus.PENDING,
        db_index=True,
    )
    preview_error = models.TextField(blank=True, default="")
    preview_source = models.CharField(max_length=50, blank=True, default="")
    preview_created_at = models.DateTimeField(null=True, blank=True)

    text_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
    )
    text_error = models.TextField(blank=True, default="")
    extracted_text = models.TextField(blank=True, default="")

    embedding_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
    )
    embedding_error = models.TextField(blank=True, default="")

    metadata_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
    )
    metadata_error = models.TextField(blank=True, default="")

    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    folder_tokens = models.TextField(blank=True, default="")
    customer_name = models.CharField(max_length=255, blank=True, db_index=True, default="")
    job_type = models.CharField(max_length=100, blank=True, default="")
    preview_version = models.IntegerField(default=1)
    text_version = models.IntegerField(default=1)
    embedding_version = models.IntegerField(default=1)
    metadata_version = models.IntegerField(default=1)

    image_width = models.IntegerField(null=True, blank=True)
    image_height = models.IntegerField(null=True, blank=True)

    captured_at = models.DateTimeField(null=True, blank=True)

    camera_make = models.CharField(max_length=120, blank=True, default="")
    camera_model = models.CharField(max_length=120, blank=True, default="")

    gps_lat = models.FloatField(null=True, blank=True)
    gps_lon = models.FloatField(null=True, blank=True)
    dpi_x = models.FloatField(null=True, blank=True)
    dpi_y = models.FloatField(null=True, blank=True)

    file_size = models.BigIntegerField(null=True, blank=True)
    file_mtime = models.DateTimeField(null=True, blank=True)
    file_ctime = models.DateTimeField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)

    extracted_text_clean = models.TextField(blank=True, default="")
    text_source = models.CharField(max_length=50, blank=True, default="", db_index=True)
    text_engine = models.CharField(max_length=50, blank=True, default="")
    text_confidence = models.FloatField(null=True, blank=True)
    text_length = models.IntegerField(default=0)
    text_language = models.CharField(max_length=20, blank=True, default="")
    text_run_at = models.DateTimeField(null=True, blank=True)

    metadata_run_at = models.DateTimeField(null=True, blank=True)
    aspect_ratio = models.FloatField(null=True, blank=True)
    orientation = models.CharField(max_length=20, blank=True, default="", db_index=True)
    color_mode = models.CharField(max_length=20, blank=True, default="")
    bit_depth = models.IntegerField(null=True, blank=True)
    page_count = models.IntegerField(null=True, blank=True)

    exif_date_taken = models.DateTimeField(null=True, blank=True)

    project_name = models.CharField(max_length=255, blank=True, default="")
    probable_job_number = models.CharField(max_length=100, blank=True, default="", db_index=True)
    relative_dir = models.TextField(blank=True, default="")
    folder_depth = models.IntegerField(null=True, blank=True)

    embedding_run_at = models.DateTimeField(null=True, blank=True)

    phash = models.CharField(max_length=32, blank=True, default="", db_index=True)
    duplicate_group = models.CharField(max_length=64, blank=True, default="", db_index=True)
    is_primary_duplicate = models.BooleanField(default=False, db_index=True)

    visual_cluster_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    similarity_anchor = models.BooleanField(default=False, db_index=True)

    duplicate_checked_at = models.DateTimeField(null=True, blank=True)
    clustered_at = models.DateTimeField(null=True, blank=True)

    near_duplicate_count = models.IntegerField(default=0)
    similar_image_count = models.IntegerField(default=0)

    folder = models.ForeignKey(
        "Folder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="images",
    )

    class Meta:
        indexes = [
            models.Index(fields=["skip_index", "preview_status", "id"], name="img_prev_q_idx"),
            models.Index(fields=["skip_index", "text_status", "preview_status", "id"], name="img_text_q_idx"),
            models.Index(fields=["skip_index", "embedding_status", "preview_status", "id"], name="img_embed_q_idx"),
            models.Index(fields=["skip_index", "metadata_status", "id"], name="img_meta_q_idx"),
            models.Index(fields=["indexed", "skip_index", "id"], name="img_index_q_idx"),
            models.Index(fields=["root", "customer_name"], name="img_root_cust_idx"),
            models.Index(fields=["root", "probable_job_number"], name="img_root_job_idx"),
            models.Index(fields=["root", "folder", "id"], name="img_root_folder_idx"),
            models.Index(fields=["duplicate_group", "is_primary_duplicate"], name="img_dupe_grp_idx"),
        ]

    def __str__(self):
        return self.filename


class ScanDir(models.Model):
    """
    Directory queue for incremental scanning.
    Each scan_task run processes a small batch of ScanDir rows.
    """
    path = models.CharField(max_length=1500, unique=True, db_index=True)
    done = models.BooleanField(default=False, db_index=True)

    attempts = models.IntegerField(default=0)
    retry_at = models.DateTimeField(default=timezone.now, db_index=True)

    last_error = models.TextField(blank=True, null=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["done", "retry_at", "updated"]
        indexes = [
            models.Index(fields=["done", "retry_at", "updated"], name="scandir_queue_idx"),
        ]

    def __str__(self):
        return self.path


class TaskLog(models.Model):
    created = models.DateTimeField(default=timezone.now, db_index=True)
    task = models.CharField(max_length=50, db_index=True)
    level = models.CharField(max_length=10, default="INFO")
    message = models.TextField()

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.created} [{self.task}] {self.level}: {self.message[:60]}"


class AssetLink(models.Model):
    parent = models.ForeignKey(
        "Image",
        on_delete=models.CASCADE,
        related_name="asset_links",
    )
    linked_image = models.ForeignKey(
        "Image",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="used_in_documents",
    )
    linked_path = models.TextField()
    raw_path = models.TextField(blank=True, default="")
    source = models.CharField(max_length=30, blank=True, default="")
    exists = models.BooleanField(default=False)
    missing = models.BooleanField(default=False)
    xml_file = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["source"]),
            models.Index(fields=["exists"]),
            models.Index(fields=["missing"]),
        ]

    def __str__(self):
        return f"{self.parent_id} -> {self.linked_path}"


class Folder(models.Model):
    root = models.ForeignKey(
        "AccessRoot",
        on_delete=models.CASCADE,
        related_name="folders",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )

    path = models.TextField(db_index=True)
    rel_path = models.TextField(blank=True, default="", db_index=True)

    name = models.CharField(max_length=255, db_index=True)
    depth = models.IntegerField(default=0, db_index=True)

    file_count = models.IntegerField(default=0)
    image_count = models.IntegerField(default=0)

    preview_image = models.ForeignKey(
        "Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    has_children = models.BooleanField(default=False)

    customer_name = models.CharField(max_length=255, blank=True, default="")
    probable_job_number = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("root", "path")]
        ordering = ["path"]
        indexes = [
            models.Index(fields=["root", "parent", "name"]),
            models.Index(fields=["root", "depth"]),
            models.Index(fields=["root", "has_children"]),
        ]

    def __str__(self):
        return self.rel_path or self.name or self.path


class ArchiveStats(models.Model):
    scope = models.CharField(max_length=32, unique=True, default="global")

    total_files = models.BigIntegerField(default=0)
    indexed_files = models.BigIntegerField(default=0)

    # Preview
    preview_ok = models.BigIntegerField(default=0)
    preview_pending = models.BigIntegerField(default=0)
    preview_processing = models.BigIntegerField(default=0)
    preview_failed = models.BigIntegerField(default=0)
    preview_unsupported = models.BigIntegerField(default=0)

    # Text pipeline
    text_ok = models.BigIntegerField(default=0)
    text_pending = models.BigIntegerField(default=0)
    text_processing = models.BigIntegerField(default=0)
    text_failed = models.BigIntegerField(default=0)
    text_skipped = models.BigIntegerField(default=0)

    # Text source / quality
    text_native_pdf = models.BigIntegerField(default=0)
    text_ocr_image = models.BigIntegerField(default=0)
    text_high_conf = models.BigIntegerField(default=0)
    text_mid_conf = models.BigIntegerField(default=0)
    text_low_conf = models.BigIntegerField(default=0)

    # Metadata
    metadata_ok = models.BigIntegerField(default=0)
    metadata_pending = models.BigIntegerField(default=0)
    metadata_processing = models.BigIntegerField(default=0)
    metadata_failed = models.BigIntegerField(default=0)
    metadata_skipped = models.BigIntegerField(default=0)

    # Embedding
    embedding_ok = models.BigIntegerField(default=0)
    embedding_pending = models.BigIntegerField(default=0)
    embedding_processing = models.BigIntegerField(default=0)
    embedding_failed = models.BigIntegerField(default=0)
    embedding_skipped = models.BigIntegerField(default=0)

    # Duplicates
    duplicate_groups = models.BigIntegerField(default=0)
    duplicate_items = models.BigIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["scope"]),
        ]

    def __str__(self):
        return self.scope


class FolderHealthSnapshot(models.Model):
    scope = models.CharField(max_length=32, default="global", db_index=True)
    root_id = models.IntegerField()
    folder = models.TextField()

    file_count = models.IntegerField()

    preview_failed = models.IntegerField(default=0)
    text_failed = models.IntegerField(default=0)
    metadata_failed = models.IntegerField(default=0)

    missing_preview = models.IntegerField(default=0)
    duplicate_count = models.IntegerField(default=0)

    health_score = models.FloatField(default=0)
    rank = models.IntegerField()

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["scope", "rank"]),
        ]

    def __str__(self):
        return f"{self.scope} :: {self.folder}"


class QueueHealthSnapshot(models.Model):
    scope = models.CharField(max_length=50, unique=True, default="global")

    scan_pending_dirs = models.BigIntegerField(default=0)
    scan_retrying_dirs = models.BigIntegerField(default=0)
    scan_done_dirs = models.BigIntegerField(default=0)

    preview_pending = models.BigIntegerField(default=0)
    preview_processing = models.BigIntegerField(default=0)
    preview_ok = models.BigIntegerField(default=0)
    preview_failed = models.BigIntegerField(default=0)
    preview_unsupported = models.BigIntegerField(default=0)

    text_pending = models.BigIntegerField(default=0)
    text_processing = models.BigIntegerField(default=0)
    text_ok = models.BigIntegerField(default=0)
    text_failed = models.BigIntegerField(default=0)
    text_skipped = models.BigIntegerField(default=0)
    text_unsupported = models.BigIntegerField(default=0)

    metadata_pending = models.BigIntegerField(default=0)
    metadata_processing = models.BigIntegerField(default=0)
    metadata_ok = models.BigIntegerField(default=0)
    metadata_failed = models.BigIntegerField(default=0)
    metadata_skipped = models.BigIntegerField(default=0)
    metadata_unsupported = models.BigIntegerField(default=0)

    embedding_pending = models.BigIntegerField(default=0)
    embedding_processing = models.BigIntegerField(default=0)
    embedding_ok = models.BigIntegerField(default=0)
    embedding_failed = models.BigIntegerField(default=0)
    embedding_skipped = models.BigIntegerField(default=0)
    embedding_unsupported = models.BigIntegerField(default=0)
    embedding_indexed = models.BigIntegerField(default=0)

    stuck_preview = models.BigIntegerField(default=0)
    stuck_text = models.BigIntegerField(default=0)
    stuck_metadata = models.BigIntegerField(default=0)
    stuck_embedding = models.BigIntegerField(default=0)

    oldest_preview_pending_at = models.DateTimeField(null=True, blank=True)
    oldest_preview_processing_at = models.DateTimeField(null=True, blank=True)
    oldest_text_pending_at = models.DateTimeField(null=True, blank=True)
    oldest_text_processing_at = models.DateTimeField(null=True, blank=True)
    oldest_metadata_pending_at = models.DateTimeField(null=True, blank=True)
    oldest_metadata_processing_at = models.DateTimeField(null=True, blank=True)
    oldest_embedding_pending_at = models.DateTimeField(null=True, blank=True)
    oldest_embedding_processing_at = models.DateTimeField(null=True, blank=True)

    ops_queue_depth = models.BigIntegerField(default=0)
    preview_queue_depth = models.BigIntegerField(default=0)
    scan_queue_depth = models.BigIntegerField(default=0)
    ocr_queue_depth = models.BigIntegerField(default=0)
    mail_queue_depth = models.BigIntegerField(default=0)
    control_queue_depth = models.BigIntegerField(default=0)
    embedding_queue_depth = models.BigIntegerField(default=0)
    metadata_queue_depth = models.BigIntegerField(default=0)
    text_queue_depth = models.BigIntegerField(default=0)

    queue_snapshot_error = models.TextField(blank=True, default="")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["scope"])]

    def __str__(self):
        return self.scope


class TaskRunMetric(models.Model):
    task_name = models.CharField(max_length=100, db_index=True)
    scope = models.CharField(max_length=50, default="global", db_index=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    duration_ms = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default="ok", db_index=True)
    details_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-finished_at"]
        indexes = [
            models.Index(fields=["task_name", "scope", "-finished_at"]),
            models.Index(fields=["status", "-finished_at"]),
        ]

    def __str__(self):
        return f"{self.task_name} [{self.scope}] {self.status} {self.duration_ms}ms"


# Additional document/email models
from .models_documents import *  # noqa
from .models_mail import *  # noqa


