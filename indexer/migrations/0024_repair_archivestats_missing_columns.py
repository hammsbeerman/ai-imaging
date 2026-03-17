from django.db import migrations


def add_missing_archivestats_columns(apps, schema_editor):
    ArchiveStats = apps.get_model("indexer", "ArchiveStats")
    table = ArchiveStats._meta.db_table

    existing_columns = {
        c.name for c in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), table
        )
    }

    wanted_fields = [
        "preview_processing",
        "text_processing",
        "metadata_processing",
        "embedding_processing",
        "text_native_pdf",
        "text_ocr_image",
        "text_high_conf",
        "text_mid_conf",
        "text_low_conf",
    ]

    for field_name in wanted_fields:
        if field_name in existing_columns:
            continue
        field = ArchiveStats._meta.get_field(field_name)
        schema_editor.add_field(ArchiveStats, field)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0023_create_missing_queue_tables"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_missing_archivestats_columns, noop_reverse),
            ],
            state_operations=[],
        ),
    ]