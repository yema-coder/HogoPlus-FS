"""Local multilingual embeddings (Marathi/Hindi/English) via fastembed (ONNX, no torch).

Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 — 384 dims.
Loaded once per process (lazy singleton, warmed at FastAPI startup).
Cache lives inside /app so it survives pod recycles.
"""
import logging
import threading

from app.config import settings

logger = logging.getLogger("hogo.embeddings")

EMBEDDING_DIM = 384

_model = None
_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                logger.info("Loading embedding model %s", settings.embedding_model)
                _model = TextEmbedding(
                    model_name=settings.embedding_model,
                    cache_dir=settings.embedding_cache_dir,
                )
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Synchronous — run via threadpool from async code."""
    return [v.tolist() for v in get_model().embed(texts)]


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]
