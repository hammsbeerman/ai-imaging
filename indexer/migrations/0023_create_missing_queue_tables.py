from django.db import migrations


def create_missing_queue_tables(apps, schema_editor):
    existing_tables = set(schema_editor.connection.introspection.table_names())

    QueueHealthSnapshot = apps.get_model("indexer", "QueueHealthSnapshot")
    TaskRunMetric = apps.get_model("indexer", "TaskRunMetric")

    if QueueHealthSnapshot._meta.db_table not in existing_tables:
        schema_editor.create_model(QueueHealthSnapshot)

    if TaskRunMetric._meta.db_table not in existing_tables:
        schema_editor.create_model(TaskRunMetric)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0022_state_only_index_name_cleanup"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(create_missing_queue_tables, noop_reverse),
            ],
            state_operations=[],
        ),
    ]