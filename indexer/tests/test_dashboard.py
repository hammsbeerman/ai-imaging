from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from indexer.models import ArchiveStats, QueueHealthSnapshot, FolderHealthSnapshot, Image


class DashboardViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="admin",
            password="testpass123",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)

    def test_ui_home_renders_without_snapshots(self):
        response = self.client.get("/ui/")
        self.assertEqual(response.status_code, 200)

    def test_ui_home_renders_with_snapshots(self):
        now = timezone.now()

        ArchiveStats.objects.create(scope="global", updated_at=now)
        QueueHealthSnapshot.objects.create(scope="global", updated_at=now)
        FolderHealthSnapshot.objects.create(
            scope="global",
            root_id=1,
            folder="/test",
            file_count=1,
            preview_failed=0,
            text_failed=0,
            metadata_failed=0,
            missing_preview=0,
            duplicate_count=0,
            health_score=0,
            rank=1,
            updated_at=now,
        )

        response = self.client.get("/ui/")
        self.assertEqual(response.status_code, 200)

    def test_ui_home_with_recent_previews(self):
        Image.objects.create(
            filename="test.jpg",
            path="/tmp/test.jpg",
            ext=".jpg",
            created=timezone.now(),
            updated_at=timezone.now(),
            preview_created_at=timezone.now(),
        )

        response = self.client.get("/ui/")
        self.assertEqual(response.status_code, 200)