from django.db import models


class InboundEmail(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PROCESSED = "processed"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_ERROR, "Error"),
    ]

    source_message_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    imap_uid = models.CharField(max_length=64, blank=True, default="", db_index=True)
    mailbox = models.CharField(max_length=255, blank=True, default="INBOX", db_index=True)

    from_name = models.CharField(max_length=255, blank=True, default="")
    from_email = models.CharField(max_length=255, blank=True, default="", db_index=True)
    to_emails = models.TextField(blank=True, default="")
    subject = models.CharField(max_length=500, blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    processing_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "received_at"], name="mail_status_recv_idx"),
            models.Index(fields=["from_email", "received_at"], name="mail_from_recv_idx"),
        ]

    def __str__(self):
        return self.subject or self.from_email or f"Email {self.pk}"


class InboundEmailAttachment(models.Model):
    email = models.ForeignKey(
        InboundEmail,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    filename = models.CharField(max_length=500, blank=True, default="")
    content_type = models.CharField(max_length=255, blank=True, default="")
    file_size = models.BigIntegerField(null=True, blank=True)

    image = models.ForeignKey(
        "indexer.Image",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_attachments",
    )
    document = models.ForeignKey(
        "indexer.Document",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="email_attachments",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.filename or f"Attachment {self.pk}"
