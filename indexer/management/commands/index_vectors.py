from django.core.management.base import BaseCommand
from indexer.index_images import run_index
import time


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=1000)
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--sleep", type=int, default=5)

    def handle(self, *args, **kwargs):
        batch = kwargs["batch"]
        loop = kwargs["loop"]
        sleep_s = kwargs["sleep"]

        while True:
            run_index(batch_size=batch)
            if not loop:
                break
            time.sleep(sleep_s)