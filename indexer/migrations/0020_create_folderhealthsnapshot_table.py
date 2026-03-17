from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0019_merge_0018_and_0016_queue_health_and_metrics"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.CreateModel(
                    name="FolderHealthSnapshot",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("scope", models.CharField(max_length=32, default="global", db_index=True)),
                        ("root_id", models.IntegerField()),
                        ("folder", models.TextField()),
                        ("file_count", models.IntegerField()),
                        ("preview_failed", models.IntegerField(default=0)),
                        ("text_failed", models.IntegerField(default=0)),
                        ("metadata_failed", models.IntegerField(default=0)),
                        ("missing_preview", models.IntegerField(default=0)),
                        ("duplicate_count", models.IntegerField(default=0)),
                        ("health_score", models.FloatField(default=0)),
                        ("rank", models.IntegerField()),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "indexes": [
                            models.Index(fields=["scope", "rank"], name="indexer_fol_scope_aef252_idx"),
                        ],
                    },
                ),
            ],
            state_operations=[],
        ),
    ]