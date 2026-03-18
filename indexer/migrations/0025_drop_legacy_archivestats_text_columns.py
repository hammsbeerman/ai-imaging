from django.db import migrations


def drop_legacy_archivestats_columns(apps, schema_editor):
    ArchiveStats = apps.get_model("indexer", "ArchiveStats")
    table = ArchiveStats._meta.db_table
    vendor = schema_editor.connection.vendor

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            c.name
            for c in schema_editor.connection.introspection.get_table_description(cursor, table)
        }

    legacy_columns = ["text_empty", "text_low_quality", "text_usable"]
    cols_to_drop = [c for c in legacy_columns if c in existing_columns]

    if not cols_to_drop:
        return

    if vendor == "postgresql":
        for col in cols_to_drop:
            schema_editor.execute(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "{col}";')
        return

    if vendor == "sqlite":
        return


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0024_repair_archivestats_missing_columns"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_archivestats_columns, noop_reverse),
    ]