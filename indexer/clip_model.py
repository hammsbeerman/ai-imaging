# indexer/clip_model.py

import open_clip

_model = None
_preprocess = None
_tokenizer = None


def get_model():
    """
    Lazy-load CLIP model once per process.
    """
    global _model, _preprocess, _tokenizer

    if _model is None:
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32",
            pretrained="openai",
            device="cpu",
        )
        model.eval()

        _model = model
        _preprocess = preprocess
        _tokenizer = open_clip.get_tokenizer("ViT-B-32")

    return _model, _preprocess, _tokenizer