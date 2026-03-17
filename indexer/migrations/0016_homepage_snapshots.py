from django.db import migrations, models
import django.db.models.deletion


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
            name="text_empty",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_low_quality",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="archivestats",
            name="text_usable",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name="archivestats",
            index=models.Index(fields=["scope"], name="archstats_scope_idx"),
        ),
        migrations.CreateModel(
            name="FolderHealthSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(db_index=True, default="global", max_length=50)),
                ("folder_path", models.TextField(blank=True, default="")),
                ("folder_name", models.CharField(blank=True, default="", max_length=255)),
                ("file_count", models.IntegerField(default=0)),
                ("preview_failed", models.IntegerField(default=0)),
                ("preview_pending", models.IntegerField(default=0)),
                ("metadata_failed", models.IntegerField(default=0)),
                ("metadata_pending", models.IntegerField(default=0)),
                ("duplicate_count", models.IntegerField(default=0)),
                ("health_score", models.IntegerField(default=0)),
                ("rank", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("folder", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="health_snapshots", to="indexer.folder")),
                ("root", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="folder_health_snapshots", to="indexer.accessroot")),
            ],
            options={
                "ordering": ["rank", "folder_path"],
            },
        ),
        migrations.AddIndex(
            model_name="folderhealthsnapshot",
            index=models.Index(fields=["scope", "rank"], name="fhealth_scope_rank_idx"),
        ),
        migrations.AddIndex(
            model_name="folderhealthsnapshot",
            index=models.Index(fields=["scope", "root"], name="fhealth_scope_root_idx"),
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
    ]
