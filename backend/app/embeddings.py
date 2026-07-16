"""Local multilingual embeddings (Marathi/Hindi/English) via fastembed (ONNX, no torch).

Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 — 384 dims.
Lazy thread-safe singleton: loaded on the FIRST embedding call (NOT at startup —
eager warm-up OOM-crash-looped 1Gi production containers), then cached per process.
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


def release_model() -> None:
    """Drop the cached ONNX model to reclaim RSS on 1Gi containers (it lazily
    reloads on the next embedding call)."""
    import gc

    global _model
    with _lock:
        if _model is not None:
            logger.info("Releasing embedding model to reclaim memory")
            _model = None
    gc.collect()
    try:  # glibc: return freed arenas to the OS (RSS actually drops)
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        logger.debug("malloc_trim unavailable on this platform")
