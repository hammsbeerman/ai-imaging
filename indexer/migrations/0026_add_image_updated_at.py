from django.db import migrations, models


def backfill_updated_at(apps, schema_editor):
    Image = apps.get_model("indexer", "Image")

    for img in Image.objects.all().iterator(chunk_size=1000):
        candidates = [
            getattr(img, "preview_created_at", None),
            getattr(img, "metadata_run_at", None),
            getattr(img, "embedding_run_at", None),
            getattr(img, "text_run_at", None),
            getattr(img, "file_mtime", None),
            getattr(img, "mtime", None),
            getattr(img, "created", None),
        ]
        chosen = next((dt for dt in candidates if dt is not None), None)
        if chosen is not None:
            Image.objects.filter(pk=img.pk).update(updated_at=chosen)


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0025_drop_legacy_archivestats_text_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="image",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True,
                db_index=True,
                null=True,
                blank=True,
            ),
        ),
        migrations.RunPython(backfill_updated_at, migrations.RunPython.noop),
    ]