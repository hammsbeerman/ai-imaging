from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

client = QdrantClient("localhost", port=6333)
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