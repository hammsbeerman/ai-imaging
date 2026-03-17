from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("indexer", "0016_homepage_snapshots"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="folderhealthsnapshot",
            options={},
        ),

        migrations.RemoveIndex(
            model_name="folderhealthsnapshot",
            name="fhealth_scope_root_idx",
        ),

        migrations.RenameIndex(
            model_name="folderhealthsnapshot",
            old_name="fhealth_scope_rank_idx",
            new_name="indexer_fol_scope_aef252_idx",
        ),

        migrations.RemoveField(
            model_name="folderhealthsnapshot",
            name="folder_name",
        ),

        migrations.RemoveField(
            model_name="folderhealthsnapshot",
            name="folder_path",
        ),

        migrations.RemoveField(
            model_name="folderhealthsnapshot",
            name="metadata_pending",
        ),

        migrations.RemoveField(
            model_name="folderhealthsnapshot",
            name="preview_pending",
        ),

        migrations.RemoveField(
            model_name="folderhealthsnapshot",
            name="root",
        ),

        migrations.AddField(
            model_name="folderhealthsnapshot",
            name="missing_preview",
            field=models.IntegerField(default=0),
        ),

        migrations.AddField(
            model_name="folderhealthsnapshot",
            name="root_id",
            field=models.IntegerField(default=0),
            preserve_default=False,
        ),

        migrations.AddField(
            model_name="folderhealthsnapshot",
            name="text_failed",
            field=models.IntegerField(default=0),
        ),

        migrations.AlterField(
            model_name="folderhealthsnapshot",
            name="file_count",
            field=models.IntegerField(),
        ),

        migrations.AlterField(
            model_name="folderhealthsnapshot",
            name="folder",
            field=models.TextField(default=""),
            preserve_default=False,
        ),

        migrations.AlterField(
            model_name="folderhealthsnapshot",
            name="health_score",
            field=models.FloatField(default=0),
        ),

        migrations.AlterField(
            model_name="folderhealthsnapshot",
            name="rank",
            field=models.IntegerField(),
        ),

        migrations.AlterField(
            model_name="folderhealthsnapshot",
            name="scope",
            field=models.CharField(max_length=32),
        ),
    ]