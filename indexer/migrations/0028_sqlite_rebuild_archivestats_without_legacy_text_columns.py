from django.db import migrations


def rebuild_archivestats_sqlite(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return

    ArchiveStats = apps.get_model("indexer", "ArchiveStats")
    table = ArchiveStats._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            c.name
            for c in schema_editor.connection.introspection.get_table_description(cursor, table)
        }

    legacy_columns = {"text_empty", "text_low_quality", "text_usable"}
    if not (legacy_columns & existing_columns):
        return

    keep_columns = [
        "id",
        "scope",
        "total_files",
        "indexed_files",
        "preview_ok",
        "preview_pending",
        "preview_processing",
        "preview_failed",
        "preview_unsupported",
        "text_ok",
        "text_pending",
        "text_processing",
        "text_failed",
        "text_skipped",
        "text_native_pdf",
        "text_ocr_image",
        "text_high_conf",
        "text_mid_conf",
        "text_low_conf",
        "metadata_ok",
        "metadata_pending",
        "metadata_processing",
        "metadata_failed",
        "metadata_skipped",
        "embedding_ok",
        "embedding_pending",
        "embedding_processing",
        "embedding_failed",
        "embedding_skipped",
        "duplicate_groups",
        "duplicate_items",
        "updated_at",
    ]

    keep_columns = [c for c in keep_columns if c in existing_columns]
    cols_sql = ", ".join(f'"{c}"' for c in keep_columns)

    schema_editor.execute(f'ALTER TABLE "{table}" RENAME TO "{table}_old";')

    schema_editor.execute(
        f'''
        CREATE TABLE "{table}" (
            "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
            "scope" varchar(32) NOT NULL UNIQUE,
            "total_files" bigint NOT NULL DEFAULT 0,
            "indexed_files" bigint NOT NULL DEFAULT 0,
            "preview_ok" bigint NOT NULL DEFAULT 0,
            "preview_pending" bigint NOT NULL DEFAULT 0,
            "preview_processing" bigint NOT NULL DEFAULT 0,
            "preview_failed" bigint NOT NULL DEFAULT 0,
            "preview_unsupported" bigint NOT NULL DEFAULT 0,
            "text_ok" bigint NOT NULL DEFAULT 0,
            "text_pending" bigint NOT NULL DEFAULT 0,
            "text_processing" bigint NOT NULL DEFAULT 0,
            "text_failed" bigint NOT NULL DEFAULT 0,
            "text_skipped" bigint NOT NULL DEFAULT 0,
            "text_native_pdf" bigint NOT NULL DEFAULT 0,
            "text_ocr_image" bigint NOT NULL DEFAULT 0,
            "text_high_conf" bigint NOT NULL DEFAULT 0,
            "text_mid_conf" bigint NOT NULL DEFAULT 0,
            "text_low_conf" bigint NOT NULL DEFAULT 0,
            "metadata_ok" bigint NOT NULL DEFAULT 0,
            "metadata_pending" bigint NOT NULL DEFAULT 0,
            "metadata_processing" bigint NOT NULL DEFAULT 0,
            "metadata_failed" bigint NOT NULL DEFAULT 0,
            "metadata_skipped" bigint NOT NULL DEFAULT 0,
            "embedding_ok" bigint NOT NULL DEFAULT 0,
            "embedding_pending" bigint NOT NULL DEFAULT 0,
            "embedding_processing" bigint NOT NULL DEFAULT 0,
            "embedding_failed" bigint NOT NULL DEFAULT 0,
            "embedding_skipped" bigint NOT NULL DEFAULT 0,
            "duplicate_groups" bigint NOT NULL DEFAULT 0,
            "duplicate_items" bigint NOT NULL DEFAULT 0,
            "updated_at" datetime NOT NULL
        );
        '''
    )

    if keep_columns:
        schema_editor.execute(
            f'''
            INSERT INTO "{table}" ({cols_sql})
            SELECT {cols_sql}
            FROM "{table}_old";
            '''
        )

    schema_editor.execute(f'DROP TABLE "{table}_old";')
    schema_editor.execute(
        f'CREATE INDEX IF NOT EXISTS "indexer_arc_scope_idx" ON "{table}" ("scope");'
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0027_alter_image_updated_at"),
    ]

    operations = [
        migrations.RunPython(rebuild_archivestats_sqlite, noop_reverse),
    ]