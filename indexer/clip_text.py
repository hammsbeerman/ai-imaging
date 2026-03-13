import torch
import open_clip
from indexer.clip_embedder import model, preprocess, device  # reuse model instance

tokenizer = open_clip.get_tokenizer("ViT-B-32")

def embed_text(text: str) -> list[float]:
    tokens = tokenizer([text]).to(device)
    with torch.no_grad():
        emb = model.encode_text(tokens)
    emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb[0].cpu().tolist()