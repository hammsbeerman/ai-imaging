from django.core.management.base import BaseCommand
from indexer.parallel_index import run_index_parallel
import time


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=500)
        parser.add_argument("--workers", type=int, default=2)
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--sleep", type=int, default=2)

    def handle(self, *args, **kwargs):
        batch = kwargs["batch"]
        workers = kwargs["workers"]
        loop = kwargs["loop"]
        sleep_s = kwargs["sleep"]

        while True:
            run_index_parallel(batch_size=batch, workers=workers)
            if not loop:
                break
            time.sleep(sleep_s)