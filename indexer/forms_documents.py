from django import forms

from indexer.models_documents import Document


class DocumentQuickEditForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = [
            "title",
            "document_type",
            "correspondent",
            "invoice_vendor",
            "invoice_number",
            "invoice_total",
            "invoice_due_date",
            "review_status",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "document_type": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "correspondent": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "invoice_vendor": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "invoice_number": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "invoice_total": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "invoice_due_date": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "review_status": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }
