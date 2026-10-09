"""
Insura - Build / Rebuild the ChromaDB vector store.

Run once (or whenever LIC_Policy_Details.xlsx changes):

    cd backend
    python build_vector_db.py

The script reads every sheet from the Excel file, converts each row
into a structured text document, and stores all embeddings in ChromaDB
using the local Ollama nomic-embed-text model.
"""

import logging
import os
import sys

import pandas as pd
from langchain_chroma import Chroma
from langchain_core.documents import Document

from embeddings import OllamaEmbedding

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("insura.build_db")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POLICY_FILE = os.path.join(BASE_DIR, "LIC_Policy_Details.xlsx")
DB_PATH = os.path.join(BASE_DIR, "chroma_db")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_policy_documents() -> list[Document]:
    """
    Read every sheet from the Excel workbook.

    Each sheet becomes one Document whose page_content is a structured
    text block combining the sheet (policy) name with a readable table.
    """
    if not os.path.exists(POLICY_FILE):
        logger.error("Policy file not found: %s", POLICY_FILE)
        sys.exit(1)

    logger.info("Reading policy file: %s", POLICY_FILE)
    excel = pd.ExcelFile(POLICY_FILE)
    documents: list[Document] = []

    for sheet_name in excel.sheet_names:
        logger.info("  Processing sheet: %s", sheet_name)
        df = pd.read_excel(POLICY_FILE, sheet_name=sheet_name)

        # Drop completely empty rows / columns to keep embeddings clean
        df.dropna(how="all", inplace=True)
        df.dropna(axis=1, how="all", inplace=True)

        # Convert each row to "Key: Value" pairs for readable embeddings
        rows_text = []
        for _, row in df.iterrows():
            pairs = "  |  ".join(
                f"{col}: {val}"
                for col, val in row.items()
                if pd.notna(val) and str(val).strip()
            )
            if pairs:
                rows_text.append(pairs)

        if not rows_text:
            logger.warning("  Sheet '%s' has no usable data — skipping.", sheet_name)
            continue

        content = (
            f"Policy Name: {sheet_name}\n\n"
            + "\n".join(rows_text)
        )

        documents.append(
            Document(
                page_content=content,
                metadata={"policy": sheet_name},
            )
        )

    logger.info("Loaded %d document(s) from %d sheet(s).", len(documents), len(excel.sheet_names))
    return documents


def build_vector_db(documents: list[Document]) -> None:
    """Embed documents and persist to ChromaDB."""
    if not documents:
        logger.error("No documents to embed. Aborting.")
        sys.exit(1)

    logger.info("Building ChromaDB at: %s", DB_PATH)
    embedding_model = OllamaEmbedding()

    # Chroma.from_documents creates (or overwrites) the store
    Chroma.from_documents(
        documents=documents,
        embedding=embedding_model,
        persist_directory=DB_PATH,
    )
    logger.info("ChromaDB built successfully with %d document(s).", len(documents))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("=== Insura Vector DB Builder ===")
    docs = load_policy_documents()
    build_vector_db(docs)
    logger.info("Done.")
