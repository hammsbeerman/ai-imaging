import os
import torch
from PIL import Image as PILImage, UnidentifiedImageError
from PIL.Image import DecompressionBombError
import indexer.pillow_limits

# Prevent oneDNN/MKLDNN conv backend from throwing "could not create a primitive"
torch.backends.mkldnn.enabled = False

# Optional: tune for your VM (adjust up/down)
torch.set_num_threads(2)
torch.set_num_interop_threads(2)

import open_clip
from PIL import Image, ImageFile, UnidentifiedImageError

ImageFile.LOAD_TRUNCATED_IMAGES = True

device = "cpu"

model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-B-32",
    pretrained="laion2b_s34b_b79k"
)
model = model.to(device)
model.eval()


def embed_image(path: str) -> list[float]:
    try:
        with PILImage.open(path) as im:
            im = im.convert("RGB")
            image_input = preprocess(im).unsqueeze(0)

        # Keep it simple: CPU unless you explicitly configured CUDA
        image_input = image_input.to(device)

        model.eval()
        with torch.no_grad():
            emb = model.encode_image(image_input)

        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb[0].detach().cpu().tolist()

    except DecompressionBombError as e:
        raise RuntimeError(f"Embedding blocked oversized image: {e}")
    except UnidentifiedImageError as e:
        raise RuntimeError(f"unidentified image: {path}") from e
    except OSError as e:
        raise RuntimeError(f"image read error: {path}: {e}") from e