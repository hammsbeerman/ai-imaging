from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from indexer.models_mail import InboundEmail
from indexer.tasks_documents import reprocess_document_task


@login_required
def email_inbox(request):
    q = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    emails = InboundEmail.objects.prefetch_related("attachments__document", "attachments__image")

    if q:
        emails = emails.filter(
            Q(subject__icontains=q)
            | Q(from_email__icontains=q)
            | Q(from_name__icontains=q)
            | Q(body_text__icontains=q)
        )

    if status_filter:
        emails = emails.filter(status=status_filter)

    emails = emails.order_by("-received_at", "-created_at")[:100]
    return render(request, "indexer/mail/inbox.html", {
        "emails": emails,
        "q": q,
        "status_filter": status_filter,
    })


@login_required
def email_detail(request, pk):
    email_obj = get_object_or_404(
        InboundEmail.objects.prefetch_related("attachments__document", "attachments__image"),
        pk=pk,
    )
    return render(request, "indexer/mail/detail.html", {"email_obj": email_obj})


@login_required
def email_reprocess_documents(request, pk):
    if request.method != "POST":
        return HttpResponse(status=405)

    email_obj = get_object_or_404(InboundEmail.objects.prefetch_related("attachments__document"), pk=pk)
    queued = 0
    for att in email_obj.attachments.all():
        if att.document_id:
            reprocess_document_task.delay(att.document_id)
            queued += 1
    return render(request, "indexer/mail/_reprocess_result.html", {"email_obj": email_obj, "queued": queued})
