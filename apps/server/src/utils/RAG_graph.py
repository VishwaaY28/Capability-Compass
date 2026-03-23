import os
import uuid
from datetime import datetime, timezone
from typing import List, Tuple, Optional

from neo4j import GraphDatabase
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from PyPDF2 import PdfReader
from neo4j_graphrag.retrievers import HybridCypherRetriever

# =========================
# Azure & Neo4j Setup
# =========================

credential = DefaultAzureCredential()
key_vault_url = "https://fstodevazureopenai.vault.azure.net/"
key_vault_url_2 = "https://kvcapabilitycompass.vault.azure.net/"
kv_client = SecretClient(vault_url=key_vault_url, credential=credential)
kv_client_2 = SecretClient(vault_url=key_vault_url_2, credential=credential)

AZURE_OPENAI_API_KEY = kv_client.get_secret("llm-api-key").value
AZURE_OPENAI_ENDPOINT = kv_client.get_secret("llm-base-endpoint").value
AZURE_OPENAI_API_VERSION = kv_client.get_secret("llm-mini-version").value
AZURE_OPENAI_CHAT_DEPLOYMENT = kv_client.get_secret("llm-5").value

AZURE_EMBEDDING_KEY = kv_client_2.get_secret("kvEmbeddingCCKey").value
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-ada-002"  # ensure this matches your deployed embedding model
AZURE_EMBEDDING_ENDPOINT = "https://fs-openai-1.openai.azure.com"

NEO4J_URI = "neo4j://127.0.0.1:7687"
NEO4J_USERNAME = "neo4j"
NEO4J_PASSWORD = "87654321"

# Basic checks
assert AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT, "Set Azure OpenAI env vars."
assert NEO4J_URI and NEO4J_USERNAME and NEO4J_PASSWORD, "Set Neo4j env vars."

# Azure OpenAI clients
aoai_client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT
)
aoai_client_2 = AzureOpenAI(
    api_key=AZURE_EMBEDDING_KEY,
    api_version="2023-05-15",
    base_url=f"{AZURE_EMBEDDING_ENDPOINT}/openai/deployments/{AZURE_OPENAI_EMBEDDING_DEPLOYMENT}"
)

# Neo4j driver
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))

# =========================
# Helpers: PDF, Chunking & Embeddings
# =========================

def read_pdf_text(pdf_path: str, max_pages: Optional[int] = None) -> str:
    """
    Extracts text from a PDF using PyPDF2. Optionally limit to first `max_pages`.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")
    if not pdf_path.lower().endswith(".pdf"):
        raise ValueError("Please provide a .pdf file")

    text_parts = []
    with open(pdf_path, "rb") as f:
        reader = PdfReader(f)
        total_pages = len(reader.pages)
        pages_to_read = total_pages if max_pages is None else min(max_pages, total_pages)

        for i in range(pages_to_read):
            page = reader.pages[i]
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            text_parts.append(page_text)

    combined = "\n".join(text_parts)
    combined = combined.replace("\x00", "")  # clean null bytes if any
    return combined.strip()


def simple_chunk_text(text: str, max_chars: int = 1000, overlap: int = 100) -> List[str]:
    """
    Naive chunker by characters, with overlap. For production, consider token-aware chunking.
    """
    text = text.strip()
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end]
        chunks.append(chunk.strip())
        if end == n:
            break
        start = max(0, end - overlap)
    return [c for c in chunks if c]


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embed a list of texts using Azure OpenAI embedding deployment.
    """
    resp = aoai_client_2.embeddings.create(
        model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        input=texts
    )
    # The SDK returns embeddings aligned to input order
    return [d.embedding for d in resp.data]


class _SimpleEmbedder:
    """Tiny adapter to satisfy neo4j_graphrag's EmbedderModel validation.

    It only needs an `embed_query(text)` method that returns a list[float].
    This delegates to the module-level `embed_texts` helper above.
    """

    def embed_query(self, text: str) -> List[float]:
        return embed_texts([text])[0]


def init_schema(dims: int, similarity: str = "cosine", index_name: str = "chunk_embedding_idx"):
    """
    Creates unique constraints and a vector index on :Chunk(embedding).
    Works across Neo4j 5.x variants:
      - Tries the modern 'CREATE VECTOR INDEX ...' DDL first.
      - Falls back to the (deprecated) 'db.index.vector.createNodeIndex' procedure.
      - Ignores 'already exists' errors to remain idempotent.
    """
    with driver.session() as session:
        # Constraints (idempotent)
        session.run("""
            CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
            FOR (c:Chunk) REQUIRE c.id IS UNIQUE
        """).consume()

        session.run("""
            CREATE CONSTRAINT doc_id_unique IF NOT EXISTS
            FOR (d:Document) REQUIRE d.id IS UNIQUE
        """).consume()

        # Check if an index with the same name already exists
        existing = session.run("""
            SHOW INDEXES
            YIELD name, type, entityType, labelsOrTypes, properties, options
            WHERE name = $name
            RETURN name, type, entityType, labelsOrTypes, properties, options
        """, name=index_name).data()

        if not existing:
            # Try NEW DDL first
            try:
                session.run(f"""
                    CREATE VECTOR INDEX {index_name} IF NOT EXISTS
                    FOR (c:Chunk) ON (c.embedding)
                    OPTIONS {{
                      indexConfig: {{
                        `vector.dimensions`: $dims,
                        `vector.similarity_function`: $similarity
                      }}
                    }}
                """, dims=dims, similarity=similarity).consume()
                return
            except Exception as e_native:
                # Fall back to the (deprecated) procedure API
                try:
                    session.run("""
                        CALL db.index.vector.createNodeIndex(
                            $name, $label, $prop, $dims, $similarity
                        )
                    """, name=index_name, label="Chunk", prop="embedding",
                         dims=dims, similarity=similarity).consume()
                    return
                except Exception as e_proc:
                    msg = str(e_proc)
                    # Swallow 'already exists' messages
                    if ("EquivalentSchemaRuleAlreadyExistsException" in msg
                        or "already exists" in msg):
                        return
                    raise RuntimeError(
                        "Failed to create vector index using both native and procedure methods.\n"
                        f"Native error: {e_native}\nProcedure error: {e_proc}"
                    )


# =========================
# Ingestion
# =========================

def ingest_document(title: str, source: str, full_text: str,
                    chunk_size: int = 1000, overlap: int = 100) -> Tuple[str, List[str]]:
    """
    Splits a document into chunks, embeds them, and writes to Neo4j as:
    (d:Document {id, title, source})-[:HAS_CHUNK]->(c:Chunk {id, text, embedding, source, createdAt})
    Returns document id and chunk ids.
    """
    chunks = simple_chunk_text(full_text, max_chars=chunk_size, overlap=overlap)
    if not chunks:
        return "", []

    # Embed chunks
    embeddings = embed_texts(chunks)
    dims = len(embeddings[0])
    init_schema(dims)

    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with driver.session() as session:
        # Upsert Document
        session.run("""
            MERGE (d:Document {id: $doc_id})
            ON CREATE SET d.title = $title, d.source = $source, d.createdAt = $now
            ON MATCH SET d.title = coalesce(d.title, $title)
        """, doc_id=doc_id, title=title, source=source, now=now).consume()

        chunk_ids = []
        for text, emb in zip(chunks, embeddings):
            cid = str(uuid.uuid4())
            chunk_ids.append(cid)
            session.run("""
                MERGE (c:Chunk {id: $cid})
                ON CREATE SET
                    c.text = $text,
                    c.embedding = $embedding,
                    c.source = $source,
                    c.createdAt = $now
                MERGE (d:Document {id: $doc_id})
                MERGE (d)-[:HAS_CHUNK]->(c)
            """, cid=cid, text=text, embedding=emb, source=source, now=now, doc_id=doc_id).consume()

    return doc_id, chunk_ids


# =========================
# Retrieval
# =========================

def retrieve_top_k(query: str, k: int = 5) -> List[Tuple[str, str, float]]:
    """
    Vector search for the top-k most similar chunks to the query.

    Returns list of tuples: (chunk_id, chunk_text, score)
    """
    try:
        embedder = _SimpleEmbedder()
        retrieval_query = "RETURN node, score"
        retriever = HybridCypherRetriever(
            driver,
            "chunk_embedding_idx",
            "chunk_fulltext_idx",
            retrieval_query,
            embedder,
        )
        raw = retriever.get_search_results(query_text=query, top_k=k)
        rows: List[Tuple[str, str, float]] = []
        for rec in raw.records:
            node = rec.get("node") if "node" in rec.keys() else None
            score = rec.get("score") if "score" in rec.keys() else None

            nid = None
            text = None
            try:
                if isinstance(node, dict):
                    nid = node.get("id") or node.get("elementId") or node.get("element_id")
                    text = node.get("text") or node.get("content") or str(node)
                else:
                    # Fallback: attempt attribute/dict access
                    try:
                        nid = node.get("id")
                    except Exception:
                        nid = getattr(node, "id", None)
                    try:
                        text = node.get("text")
                    except Exception:
                        text = getattr(node, "text", None) or str(node)
            except Exception:
                # best-effort fallback
                nid = rec.get("id") or rec.get("elementId")
                text = str(node)

            rows.append((nid, text, float(score) if score is not None else 0.0))
        return rows
    except Exception:
        q_emb = embed_texts([query])[0]

        with driver.session() as session:
            try:
                result = session.run("""
                    CALL db.index.vector.queryNodes('chunk_embedding_idx', $k, $embedding)
                    YIELD node, score
                    RETURN node.id AS id, node.text AS text, score
                    ORDER BY score DESC
                """, k=k, embedding=q_emb)
            except Exception as e:
                raise RuntimeError(
                    "Vector search failed. Ensure Neo4j is 5.12+ with vector indexes enabled "
                    "and that the index exists. Original error: " + str(e)
                )

            rows = [(r["id"], r["text"], r["score"]) for r in result]
        return rows


# =========================
# Generation
# =========================

def generate_answer(query: str, contexts: List[Tuple[str, str, float]], max_context_chars: int = 3500) -> str:
    """
    Assemble a grounded prompt from top-k contexts and call Azure OpenAI chat to generate an answer.
    Includes chunk ids for traceability.
    """
    # Concatenate contexts (trim if too long)
    context_blocks = []
    total = 0
    for cid, ctext, score in contexts:
        block = f"[ChunkID: {cid} | Score: {score:.4f}]\n{ctext}\n"
        if total + len(block) > max_context_chars:
            break
        context_blocks.append(block)
        total += len(block)

    system_msg = (
        "You are an assistant that answers strictly based on the provided context chunks.\n"
        "If the answer cannot be found in the context, say you don't know.\n"
        "Cite chunk IDs that support each key point."
    )
    user_msg = (
        f"Query:\n{query}\n\n"
        f"Context Chunks:\n" +
        "\n---\n".join(context_blocks)
    )

    resp = aoai_client.chat.completions.create(
        model=AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]
    )
    return resp.choices[0].message.content.strip()


# =========================
# CLI: Ask user for PDF & Query
# =========================

def prompt_for_pdf() -> str:
    pdf_path = "policy.pdf"
    if not pdf_path:
        raise ValueError("No PDF path provided.")
    return pdf_path


def prompt_for_metadata(default_title: str, default_source: str) -> Tuple[str, str]:
    title = input(f"Document title [{default_title}]: ").strip()
    source = input(f"Document source [{default_source}]: ").strip()
    return (title or default_title, source or default_source)


def prompt_for_query() -> str:
    q = input("\nNow enter your query about this document: ").strip()
    if not q:
        raise ValueError("Empty query. Please provide a question.")
    return q


# =========================
# Example Usage
# =========================

def main():
    print("=== PDF → Neo4j RAG Ingestion & QA ===")

    # # 1) Ask for PDF path
    # try:
    #     pdf_path = prompt_for_pdf()
    #     print(f"Reading PDF: {pdf_path}")
    #     pdf_text = read_pdf_text(pdf_path)
    #     if not pdf_text:
    #         print("No text extracted from the PDF. Aborting.")
    #         return
    # except Exception as e:
    #     print(f"Error reading PDF: {e}")
    #     return
    #
    # # 2) Ask for title/source metadata
    # guessed_title = os.path.splitext(os.path.basename(pdf_path))[0]
    # default_source = f"file://{os.path.abspath(pdf_path)}"
    # title, source = prompt_for_metadata(default_title=guessed_title, default_source=default_source)
    #
    # # 3) Ingest into Neo4j
    # try:
    #     print("Ingesting document into Neo4j...")
    #     doc_id, chunk_ids = ingest_document(
    #         title=title,
    #         source=source,
    #         full_text=pdf_text,
    #         chunk_size=1000,
    #         overlap=100
    #     )
    #     print(f" - Ingested '{title}' with {len(chunk_ids)} chunks (doc_id={doc_id})")
    # except Exception as e:
    #     print(f"Ingestion error: {e}")
    #     return

    # 4) Query loop
    try:
        user_query = prompt_for_query()
        print("\nRetrieving contexts...")
        contexts = retrieve_top_k(user_query, k=5)
        for cid, ctext, score in contexts:
            print(f"  >> Chunk {cid[:8]}..., score={score:.4f}")

        print("\nGenerating answer...")
        answer = generate_answer(user_query, contexts)
        print("\n=== ANSWER ===")
        print(answer)
    except Exception as e:
        print(f"Retrieval/Generation error: {e}")


if __name__ == "__main__":
    main()