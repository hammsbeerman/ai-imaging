from celery import shared_task

from indexer.models_documents import Document
from indexer.models_mail import InboundEmail
from indexer.services.mail_attachments import ingest_message_attachments
from indexer.services.mail_imap import connect_imap, fetch_unread_uids, import_email_from_uid, mark_uid_seen
from indexer.tasks_documents import sync_document_from_image_task
from indexer.tasks_text import extract_text_task


@shared_task
def fetch_imap_emails():
    client, mailbox = connect_imap()
    processed = 0
    errors = 0

    try:
        uids = fetch_unread_uids(client)
        for uid in uids:
            imported = None
            try:
                imported = import_email_from_uid(client, mailbox, uid)
                if not imported:
                    mark_uid_seen(client, uid)
                    continue

                email_obj, msg = imported
                attachments = ingest_message_attachments(email_obj, msg)

                for att in attachments:
                    if not att.image_id:
                        continue
                    extract_text_task.delay(str(att.image_id))
                    sync_document_from_image_task.delay(str(att.image_id))

                email_obj.status = InboundEmail.STATUS_PENDING
                email_obj.processing_error = ""
                email_obj.save(update_fields=["status", "processing_error", "updated_at"])

                mark_uid_seen(client, uid)
                processed += 1
            except Exception as exc:
                errors += 1
                if imported and isinstance(imported, tuple):
                    email_obj = imported[0]
                    email_obj.status = InboundEmail.STATUS_ERROR
                    email_obj.processing_error = str(exc)
                    email_obj.save(update_fields=["status", "processing_error", "updated_at"])
    finally:
        try:
            client.close()
        except Exception:
            pass
        client.logout()

    return {"processed": processed, "errors": errors}


@shared_task
def relink_email_documents_task(email_id: int):
    email_obj = InboundEmail.objects.prefetch_related("attachments__image", "attachments__document").get(pk=email_id)
    linked = 0
    linked_docs = []

    for att in email_obj.attachments.all():
        if not att.image_id:
            continue
        doc = Document.objects.filter(image_id=att.image_id).first()
        if doc and att.document_id != doc.id:
            att.document = doc
            att.save(update_fields=["document"])
            linked += 1
        if doc:
            linked_docs.append(doc)

    if linked_docs and all(doc.sync_status == Document.SYNC_OK for doc in linked_docs):
        email_obj.status = InboundEmail.STATUS_PROCESSED
        email_obj.processing_error = ""
        email_obj.save(update_fields=["status", "processing_error", "updated_at"])
    elif email_obj.attachments.exists():
        email_obj.status = InboundEmail.STATUS_PENDING
        email_obj.save(update_fields=["status", "updated_at"])

    return {"email_id": email_id, "linked": linked}
