from celery import shared_task
from django.db import close_old_connections

from indexer.models import Image
from indexer.models_documents import Document
from indexer.services.document_sync import is_supported_document_image, sync_document_from_image


@shared_task
def sync_document_from_image_task(image_id: str):
    close_old_connections()
    image = Image.objects.get(id=image_id)
    if not is_supported_document_image(image):
        return {"status": "skipped", "id": str(image_id), "reason": "unsupported_ext"}
    doc = sync_document_from_image(image)

    email_attachment = image.email_attachments.select_related("email").order_by("id").first()
    if email_attachment and email_attachment.email_id:
        from indexer.tasks_mail import relink_email_documents_task
        relink_email_documents_task.delay(email_attachment.email_id)

    return {"status": doc.sync_status, "id": str(image_id), "document_id": doc.id}


@shared_task
def queue_missing_document_sync_task(batch_size: int = 500, chunk_size: int = 50):
    close_old_connections()

    ids = []
    for image in Image.objects.filter(skip_index=False).order_by("id").iterator(chunk_size=chunk_size):
        if not is_supported_document_image(image):
            continue
        doc = getattr(image, "document", None)
        if doc is None:
            ids.append(str(image.id))
        else:
            synced_at = doc.synced_at
            needs_sync = False
            if synced_at is None:
                needs_sync = True
            elif image.updated_at and image.updated_at > synced_at:
                needs_sync = True
            elif image.text_run_at and image.text_run_at > synced_at:
                needs_sync = True
            if needs_sync:
                ids.append(str(image.id))
        if len(ids) >= batch_size:
            break

    for image_id in ids:
        sync_document_from_image_task.delay(image_id)

    return {"selected": len(ids)}


@shared_task
def reprocess_document_task(document_id: int):
    close_old_connections()
    doc = Document.objects.select_related("image").get(pk=document_id)
    from indexer.tasks_text import extract_text_task

    doc.sync_status = Document.SYNC_PENDING
    doc.processing_error = ""
    doc.save(update_fields=["sync_status", "processing_error", "updated_at"])

    image = doc.image
    image.text_status = "pending"
    image.text_error = ""
    image.save(update_fields=["text_status", "text_error"])

    extract_text_task.delay(str(image.id))
    return {"status": "queued", "document_id": doc.id, "image_id": str(image.id)}
