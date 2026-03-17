from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0020_create_folderhealthsnapshot_table"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name="archivestats",
                    name="text_empty",
                ),
                migrations.RemoveField(
                    model_name="archivestats",
                    name="text_low_quality",
                ),
                migrations.RemoveField(
                    model_name="archivestats",
                    name="text_usable",
                ),
            ],
        ),
        migrations.AlterField(
            model_name="folderhealthsnapshot",
            name="scope",
            field=models.CharField(
                max_length=32,
                default="global",
                db_index=True,
            ),
        ),
    ]