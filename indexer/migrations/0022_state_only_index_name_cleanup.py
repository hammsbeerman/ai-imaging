from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0021_cleanup_archivestats_and_folderhealth"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameIndex(
                    model_name="queuehealthsnapshot",
                    old_name="indexer_que_scope_4a36c0_idx",
                    new_name="indexer_que_scope_facb26_idx",
                ),
                migrations.RenameIndex(
                    model_name="taskrunmetric",
                    old_name="indexer_tas_task_na_26ad84_idx",
                    new_name="indexer_tas_task_na_f0302f_idx",
                ),
                migrations.RenameIndex(
                    model_name="taskrunmetric",
                    old_name="indexer_tas_status_dd5115_idx",
                    new_name="indexer_tas_status_bea78a_idx",
                ),
            ],
        ),
    ]