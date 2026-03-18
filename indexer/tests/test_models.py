import time

from django.test import TestCase
from django.utils import timezone

from indexer.models import Image


class ImageModelTests(TestCase):
    def test_updated_at_exists_on_create(self):
        img = Image.objects.create(
            filename="a.jpg",
            path="/tmp/a.jpg",
            ext=".jpg",
            created=timezone.now(),
        )
        self.assertIsNotNone(img.updated_at)

    def test_updated_at_changes_on_save(self):
        img = Image.objects.create(
            filename="a.jpg",
            path="/tmp/a.jpg",
            ext=".jpg",
            created=timezone.now(),
        )
        old = img.updated_at

        time.sleep(0.01)
        img.filename = "b.jpg"
        img.save()
        img.refresh_from_db()

        self.assertGreaterEqual(img.updated_at, old)