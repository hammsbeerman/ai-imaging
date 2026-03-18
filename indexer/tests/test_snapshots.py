from django.test import TestCase

from indexer.models import ArchiveStats, QueueHealthSnapshot
from indexer.tasks_stats import rebuild_archive_stats_task
from indexer.tasks_queue_health import rebuild_queue_health_snapshot_task
from indexer.tasks_folder_health import rebuild_folder_health_snapshot_task


class SnapshotTaskTests(TestCase):
    def test_archive_stats_task_creates_row(self):
        rebuild_archive_stats_task()
        self.assertTrue(ArchiveStats.objects.filter(scope="global").exists())

    def test_queue_health_task_creates_row(self):
        rebuild_queue_health_snapshot_task()
        self.assertTrue(QueueHealthSnapshot.objects.exists())

    def test_folder_health_task_runs_without_error(self):
        rebuild_folder_health_snapshot_task()
        self.assertTrue(True)