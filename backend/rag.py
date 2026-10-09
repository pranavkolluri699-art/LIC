"""
Insura - RAG (Retrieval-Augmented Generation) module.

Loads the ChromaDB vector store once at module import time and exposes
a single public function:  retrieve_policy(question) -> str
"""

import logging
import os

from langchain_chroma import Chroma

from embeddings import OllamaEmbedding

logger = logging.getLogger("insura.rag")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "chroma_db")

# ---------------------------------------------------------------------------
# Load vector store
# ---------------------------------------------------------------------------

_vector_db: Chroma | None = None


def _get_db() -> Chroma:
    """Lazy-load the vector store so startup failures are surfaced clearly."""
    global _vector_db
    if _vector_db is None:
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(
                f"ChromaDB not found at '{DB_PATH}'. "
                "Run build_vector_db.py first."
            )
        logger.info("Loading ChromaDB from: %s", DB_PATH)
        _vector_db = Chroma(
            persist_directory=DB_PATH,
            embedding_function=OllamaEmbedding(),
        )
        logger.info("ChromaDB loaded successfully.")
    return _vector_db


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

TOP_K = 3  # number of chunks to retrieve


def retrieve_policy(question: str) -> str:
    """
    Search the vector store for the most relevant policy chunks.

    Returns the concatenated text of the top-K results, or an empty
    string if retrieval fails (caller handles the missing-context case).
    """
    if not question.strip():
        return ""

    try:
        db = _get_db()
        docs = db.similarity_search(question, k=TOP_K)

        if not docs:
            logger.info("No relevant policy chunks found for: %s", question)
            return ""

        context = "\n\n".join(doc.page_content for doc in docs)
        logger.info(
            "Retrieved %d policy chunk(s) for query: %s",
            len(docs),
            question,
        )
        return context

    except FileNotFoundError as exc:
        logger.error("ChromaDB unavailable: %s", exc)
        return ""

    except Exception as exc:
        logger.exception("Unexpected RAG error: %s", exc)
        return ""
