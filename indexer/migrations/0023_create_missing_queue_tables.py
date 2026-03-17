from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0022_state_only_index_name_cleanup"),
    ]

    operations = [
        migrations.RunSQL(
            """
            CREATE TABLE IF NOT EXISTS indexer_queuehealthsnapshot (
                id BIGSERIAL PRIMARY KEY,
                scope VARCHAR(50) UNIQUE NOT NULL DEFAULT 'global',
                scan_pending_dirs BIGINT NOT NULL DEFAULT 0,
                scan_retrying_dirs BIGINT NOT NULL DEFAULT 0,
                scan_done_dirs BIGINT NOT NULL DEFAULT 0,
                preview_pending BIGINT NOT NULL DEFAULT 0,
                preview_processing BIGINT NOT NULL DEFAULT 0,
                preview_ok BIGINT NOT NULL DEFAULT 0,
                preview_failed BIGINT NOT NULL DEFAULT 0,
                preview_unsupported BIGINT NOT NULL DEFAULT 0,
                text_pending BIGINT NOT NULL DEFAULT 0,
                text_processing BIGINT NOT NULL DEFAULT 0,
                text_ok BIGINT NOT NULL DEFAULT 0,
                text_failed BIGINT NOT NULL DEFAULT 0,
                text_skipped BIGINT NOT NULL DEFAULT 0,
                text_unsupported BIGINT NOT NULL DEFAULT 0,
                metadata_pending BIGINT NOT NULL DEFAULT 0,
                metadata_processing BIGINT NOT NULL DEFAULT 0,
                metadata_ok BIGINT NOT NULL DEFAULT 0,
                metadata_failed BIGINT NOT NULL DEFAULT 0,
                metadata_skipped BIGINT NOT NULL DEFAULT 0,
                metadata_unsupported BIGINT NOT NULL DEFAULT 0,
                embedding_pending BIGINT NOT NULL DEFAULT 0,
                embedding_processing BIGINT NOT NULL DEFAULT 0,
                embedding_ok BIGINT NOT NULL DEFAULT 0,
                embedding_failed BIGINT NOT NULL DEFAULT 0,
                embedding_skipped BIGINT NOT NULL DEFAULT 0,
                embedding_unsupported BIGINT NOT NULL DEFAULT 0,
                embedding_indexed BIGINT NOT NULL DEFAULT 0,
                stuck_preview BIGINT NOT NULL DEFAULT 0,
                stuck_text BIGINT NOT NULL DEFAULT 0,
                stuck_metadata BIGINT NOT NULL DEFAULT 0,
                stuck_embedding BIGINT NOT NULL DEFAULT 0,
                oldest_preview_pending_at TIMESTAMPTZ NULL,
                oldest_preview_processing_at TIMESTAMPTZ NULL,
                oldest_text_pending_at TIMESTAMPTZ NULL,
                oldest_text_processing_at TIMESTAMPTZ NULL,
                oldest_metadata_pending_at TIMESTAMPTZ NULL,
                oldest_metadata_processing_at TIMESTAMPTZ NULL,
                oldest_embedding_pending_at TIMESTAMPTZ NULL,
                oldest_embedding_processing_at TIMESTAMPTZ NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """,
        ),
        migrations.RunSQL(
            """
            CREATE TABLE IF NOT EXISTS indexer_taskrunmetric (
                id BIGSERIAL PRIMARY KEY,
                task_name VARCHAR(100) NOT NULL,
                scope VARCHAR(50) NOT NULL DEFAULT 'global',
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ NOT NULL,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'ok',
                details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """,
        ),
    ]