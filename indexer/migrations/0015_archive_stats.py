from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0014_image_img_prev_q_idx_image_img_text_q_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArchiveStats",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(default="global", max_length=50, unique=True)),
                ("total_files", models.BigIntegerField(default=0)),
                ("indexed_files", models.BigIntegerField(default=0)),
                ("preview_ok", models.BigIntegerField(default=0)),
                ("preview_pending", models.BigIntegerField(default=0)),
                ("preview_failed", models.BigIntegerField(default=0)),
                ("preview_unsupported", models.BigIntegerField(default=0)),
                ("text_ok", models.BigIntegerField(default=0)),
                ("text_pending", models.BigIntegerField(default=0)),
                ("text_failed", models.BigIntegerField(default=0)),
                ("text_skipped", models.BigIntegerField(default=0)),
                ("metadata_ok", models.BigIntegerField(default=0)),
                ("metadata_pending", models.BigIntegerField(default=0)),
                ("metadata_failed", models.BigIntegerField(default=0)),
                ("metadata_skipped", models.BigIntegerField(default=0)),
                ("embedding_ok", models.BigIntegerField(default=0)),
                ("embedding_pending", models.BigIntegerField(default=0)),
                ("embedding_failed", models.BigIntegerField(default=0)),
                ("embedding_skipped", models.BigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]