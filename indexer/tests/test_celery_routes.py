from django.test import SimpleTestCase
from media_index.celery import app


class CeleryRouteTests(SimpleTestCase):
    def _queue_name(self, task_name):
        route = app.amqp.router.route({}, task_name, args=(), kwargs={})
        queue = route["queue"]
        return getattr(queue, "name", queue)

    def test_archive_stats_routes_to_ops(self):
        self.assertEqual(
            self._queue_name("indexer.tasks_stats.rebuild_archive_stats_task"),
            "ops",
        )

    def test_queue_health_routes_to_ops(self):
        self.assertEqual(
            self._queue_name("indexer.tasks_queue_health.rebuild_queue_health_snapshot_task"),
            "ops",
        )

    def test_folder_health_routes_to_ops(self):
        self.assertEqual(
            self._queue_name("indexer.tasks_folder_health.rebuild_folder_health_snapshot_task"),
            "ops",
        )