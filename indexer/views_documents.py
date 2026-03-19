from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from indexer.forms_documents import DocumentQuickEditForm
from indexer.models_documents import Document
from indexer.tasks_documents import reprocess_document_task


@login_required
def document_inbox(request):
    q = (request.GET.get("q") or "").strip()
    filter_type = (request.GET.get("filter") or "pending").strip()
    dup_group = (request.GET.get("dup_group") or "").strip()

    docs = Document.objects.select_related("image", "reviewed_by")

    if q:
        docs = docs.filter(
            Q(original_filename__icontains=q)
            | Q(extracted_text_search__icontains=q)
            | Q(invoice_vendor__icontains=q)
            | Q(invoice_number__icontains=q)
            | Q(correspondent__icontains=q)
        )

    if dup_group:
        docs = docs.filter(duplicate_group=dup_group)
    elif filter_type == "duplicates":
        docs = docs.filter(is_duplicate=True)
    elif filter_type == "errors":
        docs = docs.filter(sync_status=Document.SYNC_ERROR)
    elif filter_type == "invoices":
        docs = docs.filter(document_type="invoice")
    elif filter_type == "approved":
        docs = docs.filter(review_status=Document.REVIEW_APPROVED)
    elif filter_type == "pending":
        docs = docs.filter(review_status=Document.REVIEW_PENDING)

    docs = docs.order_by("-confidence_score", "-updated_at")[:200]
    return render(request, "indexer/documents/inbox.html", {
        "documents": docs,
        "q": q,
        "filter_type": filter_type,
        "dup_group": dup_group,
    })


@login_required
def document_detail(request, pk):
    doc = get_object_or_404(
        Document.objects.select_related("image", "reviewed_by").prefetch_related("pages", "email_attachments__email"),
        pk=pk,
    )
    dup_docs = []
    if doc.is_duplicate and doc.duplicate_group:
        dup_docs = list(
            Document.objects.filter(duplicate_group=doc.duplicate_group)
            .exclude(pk=doc.pk)
            .order_by("-updated_at")[:20]
        )
    form = DocumentQuickEditForm(instance=doc)
    return render(request, "indexer/documents/detail.html", {"doc": doc, "form": form, "dup_docs": dup_docs})


@login_required
def document_quick_edit(request, pk):
    if request.method != "POST":
        return HttpResponse(status=405)

    doc = get_object_or_404(Document, pk=pk)
    form = DocumentQuickEditForm(request.POST, instance=doc)
    if form.is_valid():
        obj = form.save(commit=False)
        if obj.review_status in {Document.REVIEW_APPROVED, Document.REVIEW_NEEDS_REVIEW}:
            obj.reviewed_at = timezone.now()
            obj.reviewed_by = request.user
        obj.save()
        form = DocumentQuickEditForm(instance=obj)
        return render(request, "indexer/documents/_edit_panel.html", {"doc": obj, "form": form, "saved": True})

    return render(request, "indexer/documents/_edit_panel.html", {"doc": doc, "form": form, "saved": False}, status=400)


@login_required
def document_approve(request, pk):
    if request.method != "POST":
        return HttpResponse(status=405)
    doc = get_object_or_404(Document, pk=pk)
    doc.review_status = Document.REVIEW_APPROVED
    doc.reviewed_at = timezone.now()
    doc.reviewed_by = request.user
    doc.save(update_fields=["review_status", "reviewed_at", "reviewed_by", "updated_at"])
    return render(request, "indexer/documents/_review_badge.html", {"doc": doc})


@login_required
def document_needs_review(request, pk):
    if request.method != "POST":
        return HttpResponse(status=405)
    doc = get_object_or_404(Document, pk=pk)
    doc.review_status = Document.REVIEW_NEEDS_REVIEW
    doc.reviewed_at = timezone.now()
    doc.reviewed_by = request.user
    doc.save(update_fields=["review_status", "reviewed_at", "reviewed_by", "updated_at"])
    return render(request, "indexer/documents/_review_badge.html", {"doc": doc})


@login_required
def document_reprocess(request, pk):
    if request.method != "POST":
        return HttpResponse(status=405)
    doc = get_object_or_404(Document, pk=pk)
    reprocess_document_task.delay(doc.id)
    return HttpResponse("<div class='small text-success mt-2'>Reprocess queued.</div>")
