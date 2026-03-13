from django.apps import AppConfig


class IndexerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'indexer'

    def ready(self):
        from indexer.qdrant import ensure_collection
        try:
            ensure_collection()
        except Exception:
            pass
