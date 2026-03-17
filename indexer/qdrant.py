from urllib.parse import urlparse
from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

_qdrant_url = getattr(settings, "QDRANT_URL", "http://127.0.0.1:6333")
_parsed = urlparse(_qdrant_url)

client = QdrantClient(
    host=_parsed.hostname or "127.0.0.1",
    port=_parsed.port or 6333,
)

COLLECTION = "images"

def ensure_collection():
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION not in existing:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=512, distance=Distance.COSINE),
        )

def upsert_vector(image_id: str, vector, payload=None):
    if hasattr(vector, "tolist"):
        vector = vector.tolist()

    client.upsert(
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=str(image_id),
                vector=vector,
                payload=payload or {},
            )
        ],
    )