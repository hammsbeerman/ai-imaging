from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0015_archive_stats"),
    ]

    operations = [
        migrations.AddField(
            model_name="archivestats",
            name="duplicate_groups",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="duplicate_items",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="embedding_processing",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="metadata_processing",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="preview_processing",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_high_conf",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_low_conf",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_mid_conf",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_native_pdf",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_ocr_image",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_processing",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="image",
            name="preview_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("ok", "OK"),
                    ("failed", "Failed"),
                    ("unsupported", "Unsupported"),
                ],
                db_index=True,
                default="pending",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="QueueHealthSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(default="global", max_length=50, unique=True)),
                ("scan_pending_dirs", models.BigIntegerField(default=0)),
                ("scan_retrying_dirs", models.BigIntegerField(default=0)),
                ("scan_done_dirs", models.BigIntegerField(default=0)),
                ("preview_pending", models.BigIntegerField(default=0)),
                ("preview_processing", models.BigIntegerField(default=0)),
                ("preview_ok", models.BigIntegerField(default=0)),
                ("preview_failed", models.BigIntegerField(default=0)),
                ("preview_unsupported", models.BigIntegerField(default=0)),
                ("text_pending", models.BigIntegerField(default=0)),
                ("text_processing", models.BigIntegerField(default=0)),
                ("text_ok", models.BigIntegerField(default=0)),
                ("text_failed", models.BigIntegerField(default=0)),
                ("text_skipped", models.BigIntegerField(default=0)),
                ("text_unsupported", models.BigIntegerField(default=0)),
                ("metadata_pending", models.BigIntegerField(default=0)),
                ("metadata_processing", models.BigIntegerField(default=0)),
                ("metadata_ok", models.BigIntegerField(default=0)),
                ("metadata_failed", models.BigIntegerField(default=0)),
                ("metadata_skipped", models.BigIntegerField(default=0)),
                ("metadata_unsupported", models.BigIntegerField(default=0)),
                ("embedding_pending", models.BigIntegerField(default=0)),
                ("embedding_processing", models.BigIntegerField(default=0)),
                ("embedding_ok", models.BigIntegerField(default=0)),
                ("embedding_failed", models.BigIntegerField(default=0)),
                ("embedding_skipped", models.BigIntegerField(default=0)),
                ("embedding_unsupported", models.BigIntegerField(default=0)),
                ("embedding_indexed", models.BigIntegerField(default=0)),
                ("stuck_preview", models.BigIntegerField(default=0)),
                ("stuck_text", models.BigIntegerField(default=0)),
                ("stuck_metadata", models.BigIntegerField(default=0)),
                ("stuck_embedding", models.BigIntegerField(default=0)),
                ("oldest_preview_pending_at", models.DateTimeField(blank=True, null=True)),
                ("oldest_preview_processing_at", models.DateTimeField(blank=True, null=True)),
                ("oldest_text_pending_at", models.DateTimeField(blank=True, null=True)),
                ("oldest_text_processing_at", models.DateTimeField(blank=True, null=True)),
                ("oldest_metadata_pending_at", models.DateTimeField(blank=True, null=True)),
                ("oldest_metadata_processing_at", models.DateTimeField(blank=True, null=True)),
                ("oldest_embedding_pending_at", models.DateTimeField(blank=True, null=True)),
                ("oldest_embedding_processing_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [models.Index(fields=["scope"], name="indexer_que_scope_4a36c0_idx")],
            },
        ),
        migrations.CreateModel(
            name="TaskRunMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task_name", models.CharField(db_index=True, max_length=100)),
                ("scope", models.CharField(db_index=True, default="global", max_length=50)),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField()),
                ("duration_ms", models.IntegerField(default=0)),
                ("status", models.CharField(db_index=True, default="ok", max_length=20)),
                ("details_json", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-finished_at"],
                "indexes": [
                    models.Index(fields=["task_name", "scope", "-finished_at"], name="indexer_tas_task_na_26ad84_idx"),
                    models.Index(fields=["status", "-finished_at"], name="indexer_tas_status_dd5115_idx"),
                ],
            },
        ),
    ]
