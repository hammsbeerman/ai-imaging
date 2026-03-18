from django.utils import timezone
from indexer.models import Image


def make_image(**kwargs):
    defaults = {
        "filename": "test.jpg",
        "path": "/tmp/test.jpg",
        "ext": ".jpg",
        "created": timezone.now(),
        "updated_at": timezone.now(),
    }
    defaults.update(kwargs)
    return Image.objects.create(**defaults)