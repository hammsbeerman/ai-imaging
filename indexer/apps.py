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

        # Ensure extra model modules are loaded by Django's app registry.
        from indexer import models_documents  # noqa: F401
        from indexer import models_mail  # noqa: F401
