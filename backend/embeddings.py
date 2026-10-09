"""
Insura - Shared Ollama Embedding class.

Extracted from rag.py / build_vector_db.py to avoid duplication.
Used by both modules.
"""

import logging

import ollama

logger = logging.getLogger("insura.embeddings")

EMBEDDING_MODEL = "nomic-embed-text"


class OllamaEmbedding:
    """
    LangChain-compatible embedding class backed by a local Ollama model.

    Implements the two methods expected by LangChain / ChromaDB:
      - embed_documents(texts)  -> list[list[float]]
      - embed_query(text)       -> list[float]
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for i, text in enumerate(texts):
            try:
                response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text)
                embeddings.append(response["embedding"])
            except Exception as exc:
                logger.error(
                    "Failed to embed document %d/%d: %s", i + 1, len(texts), exc
                )
                raise
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        try:
            response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text)
            return response["embedding"]
        except Exception as exc:
            logger.error("Failed to embed query: %s", exc)
            raise
