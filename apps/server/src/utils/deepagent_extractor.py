"""
DeepAgent-based capability model extractor.

This module handles PDF/document parsing and capability model extraction
using DeepAgent with man-in-the-middle callback streaming.

Includes performance optimizations:
- Larger chunk sizes (1500 chars) to reduce LLM processing overhead
- Extraction result caching based on file hash to avoid re-processing identical documents
"""

import os
import json
import logging
import asyncio
import tempfile
import hashlib
import time
from typing import Any, List, Dict, AsyncGenerator, Optional
from pathlib import Path
from datetime import datetime
from deepagents import create_deep_agent
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from unstructured import partition
from langchain_openai import AzureChatOpenAI
from langchain_core.callbacks.base import BaseCallbackHandler
from openai import AzureOpenAI
from config.azure_clients import get_azure_chat_openai_client, get_azure_embedding_client, get_azure_config

logger = logging.getLogger(__name__)

# Module-level cache for Azure LLM clients to avoid repeated initialization
_azure_llm_cache = {
    "llm": None,
    "embedder": None
}

# Module-level cache for extraction results to avoid re-processing identical documents
# Cache structure: {file_hash: {extraction_data, timestamp, config_hash}}
_extraction_cache = {}
_cache_dir = Path("extraction_cache")


def _compute_file_hash(file_path: str) -> str:
    """
    Compute SHA256 hash of a file for cache key generation.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Hexadecimal hash string
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files efficiently
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.warning(f"Failed to compute file hash: {e}")
        return None


def _compute_config_hash(
    vertical: Optional[str],
    subvertical: Optional[str],
    extraction_depth: str,
    capability: Optional[str] = None,
) -> str:
    """
    Compute hash of extraction configuration parameters.

    Args:
        vertical: Vertical name
        subvertical: SubVertical name
        extraction_depth: Extraction depth level
        capability: Optional user-provided capability name override. Included
            in the hash so that the same document re-extracted under a
            different capability name produces a distinct cache entry.

    Returns:
        Hexadecimal hash string
    """
    config_str = (
        f"{vertical or ''}|{subvertical or ''}|{extraction_depth}|{capability or ''}"
    )
    return hashlib.sha256(config_str.encode()).hexdigest()


def _get_cached_extraction(file_hash: str, config_hash: str) -> Optional[Dict]:
    """
    Retrieve cached extraction result if available and valid.
    
    Args:
        file_hash: Hash of the input file
        config_hash: Hash of extraction configuration
        
    Returns:
        Cached extraction data or None if not found/invalid
    """
    try:
        # Check in-memory cache first
        cache_key = f"{file_hash}_{config_hash}"
        if cache_key in _extraction_cache:
            cached = _extraction_cache[cache_key]
            logger.info(f"[CACHE HIT] Found cached extraction in memory (timestamp: {cached.get('timestamp')})")
            return cached.get("extraction_data")
        
        # Check disk cache
        _cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = _cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            with cache_file.open("r", encoding="utf-8") as f:
                cached = json.load(f)
                # Cache entries are valid indefinitely unless file changes
                logger.info(f"[CACHE HIT] Found cached extraction on disk (timestamp: {cached.get('timestamp')})")
                # Load into memory cache for faster subsequent access
                _extraction_cache[cache_key] = cached
                return cached.get("extraction_data")
        
        logger.info("[CACHE MISS] No cached extraction found")
        return None
        
    except Exception as e:
        logger.warning(f"Failed to retrieve cached extraction: {e}")
        return None


def _safe_write_ingestion_log(**kwargs) -> None:
    """
    Persist an ingestion run record to the JSONL log file.

    Failures are swallowed (and logged) so that ingestion logging never
    breaks the extraction pipeline.
    """
    try:
        from utils.ingestion_logger import build_run_entry, write_ingestion_log
        write_ingestion_log(build_run_entry(**kwargs))
    except Exception as exc:  # pragma: no cover - logging must never crash extraction
        logger.warning(f"[INGESTION_LOG] Failed to write ingestion log: {exc}", exc_info=True)


def _validate_document_against_ontology(chunks: List[Dict]) -> Dict:
    """
    Pre-LLM gate: score the document chunks against the FIBO ontology.

    Returns:
        {
          "available":      <bool>  — ontology service usable
          "relevance":      <DocumentRelevance.to_dict() or {}>,
          "ontology_meta":  <metadata snapshot used in this run>,
          "focus_prompt":   <str — prompt fragment to inject into the agent
                              system prompt, empty if no concepts hit>,
          "is_relevant":    <bool — final accept/reject>,
          "rejection_reason": <str | None>,
          "error":          <str | None>,
        }

    On any internal failure the document is treated as *relevant* (i.e. we
    fall back to the previous "extract everything" behaviour) so an outage
    in the ontology service never blocks ingestion. The downstream
    post-extraction guardrail is still in place as a safety net.
    """
    try:
        from utils.ontology import get_ontology_service
        ontology = get_ontology_service()
    except Exception as exc:
        logger.warning(f"[Ontology] Document gate unavailable, allowing through: {exc}", exc_info=True)
        return {
            "available": False,
            "relevance": {},
            "ontology_meta": {},
            "focus_prompt": "",
            "is_relevant": True,
            "rejection_reason": None,
            "error": str(exc),
        }

    relevance = ontology.score_document(chunks)
    focus_prompt = ontology.build_extraction_focus(relevance.top_concepts)

    logger.info(
        "[Ontology] Document gate: relevant=%s top_score=%.3f doc_threshold=%.3f "
        "top_concepts=[%s]",
        relevance.is_relevant,
        relevance.aggregate_score,
        relevance.doc_threshold,
        ", ".join(
            f"{h.concept_label}({h.best_chunk_score:.2f})"
            for h in relevance.top_concepts
        ) or "<none>",
    )

    return {
        "available": True,
        "relevance": relevance.to_dict(),
        "ontology_meta": ontology.metadata(),
        "focus_prompt": focus_prompt,
        "is_relevant": relevance.is_relevant,
        "rejection_reason": relevance.rejection_reason,
        "error": None,
    }


def _apply_ontology_guardrail(
    extracted_data: Dict,
    capability_name: Optional[str] = None,
    document_top_concept_iris: Optional[List[str]] = None,
) -> Dict:
    """
    Run the FIBO ontology guardrail over the extracted processes and return:

        {
          "annotated_data":   <model with processes filtered + ontology_alignment metadata>,
          "ontology_meta":    <ontology descriptor>,
          "guardrail_summary":<full guardrail outcome incl. candidates/accepted/rejected>,
          "accepted":         <list[GuardrailMatch.to_dict()]>,
          "rejected":         <list[GuardrailMatch.to_dict()]>,
          "available":        <bool — whether the ontology service was usable>,
          "error":            <str | None>,
        }

    On any internal failure the original ``extracted_data`` is returned
    unmodified so the rest of the pipeline still works.
    """
    try:
        from utils.ontology import get_ontology_service
        ontology = get_ontology_service()
    except Exception as exc:
        logger.warning(f"[Ontology] Guardrail unavailable, skipping: {exc}", exc_info=True)
        return {
            "annotated_data": extracted_data,
            "ontology_meta": {},
            "guardrail_summary": {"applied": False, "reason": "ontology_unavailable"},
            "accepted": [],
            "rejected": [],
            "available": False,
            "error": str(exc),
        }

    processes = extracted_data.get("processes", []) or []
    # Pass the capability name as scoring context so processes inherit the
    # document's dominant theme (e.g. "Securities Clearing and Settlement"
    # → its child processes are scored against settlement-related concepts
    # instead of accidentally matching unrelated "...management" labels).
    cap_ctx = capability_name or extracted_data.get("name") or ""
    result = ontology.apply_guardrail(
        processes,
        capability_context=cap_ctx,
        document_top_concept_iris=document_top_concept_iris,
    )
    annotated = ontology.annotate_model(extracted_data, result)

    accepted = [m.to_dict() for m in result.accepted]
    rejected = [m.to_dict() for m in result.rejected]
    candidates = [m.to_dict() for m in result.candidates]

    logger.info(
        "[Ontology] capability='%s' candidates=%d accepted=%d rejected=%d threshold=%.2f max=%d",
        capability_name or extracted_data.get("name") or "?",
        len(candidates),
        len(accepted),
        len(rejected),
        result.threshold,
        result.max_processes,
    )

    return {
        "annotated_data": annotated,
        "ontology_meta": result.ontology_meta,
        "guardrail_summary": {
            "applied": True,
            "threshold": result.threshold,
            "max_processes": result.max_processes,
            "candidate_count": len(candidates),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "candidates": candidates,
            "accepted": accepted,
            "rejected": rejected,
        },
        "accepted": accepted,
        "rejected": rejected,
        "available": True,
        "error": None,
    }


def _save_extraction_to_cache(file_hash: str, config_hash: str, extraction_data: Dict):
    """
    Save extraction result to cache (both memory and disk).
    
    Args:
        file_hash: Hash of the input file
        config_hash: Hash of extraction configuration
        extraction_data: The extracted capability model data
    """
    try:
        cache_key = f"{file_hash}_{config_hash}"
        cached_entry = {
            "extraction_data": extraction_data,
            "timestamp": datetime.now().isoformat(),
            "file_hash": file_hash,
            "config_hash": config_hash
        }
        
        # Save to memory cache
        _extraction_cache[cache_key] = cached_entry
        
        # Save to disk cache
        _cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = _cache_dir / f"{cache_key}.json"
        
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(cached_entry, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[CACHE SAVE] Saved extraction to cache: {cache_file}")
        
    except Exception as e:
        logger.warning(f"Failed to save extraction to cache: {e}")



class StreamingCallbackHandler(BaseCallbackHandler):
    """
    Man-in-the-middle callback handler that captures LLM streaming events
    and converts them to a format suitable for frontend consumption.
    """
    
    def __init__(self):
        self.tokens = []
        self.current_json = ""
        self.extraction_data = None
        
    async def on_llm_start(self, serialized, input_list, **kwargs):
        """Called when LLM starts processing."""
        logger.info(f"LLM processing started")
        
    async def on_llm_new_token(self, token: str, **kwargs):
        """Called for each new token streamed from the LLM."""
        self.tokens.append(token)
        # Try to accumulate valid JSON
        self.current_json += token
        
    async def on_llm_end(self, response, **kwargs):
        """Called when LLM completes."""
        logger.info(f"LLM processing completed")


def load_document(path: str, chunk_size: int = 1500, chunk_overlap: int = 100) -> List[Dict]:
    """
    Load .pdf/.docx/.txt and return chunk dicts: [{"text": "...", "metadata": {...}}]
    
    Args:
        path: File path to load
        chunk_size: Character size for text chunks (increased to 1500 for better performance)
        chunk_overlap: Overlap between chunks (increased to 100 for better context)
        
    Returns:
        List of chunk dictionaries with text and metadata
    """
    ext = os.path.splitext(path)[1].lower()
    
    if ext == ".pdf":
        loader = PyPDFLoader(path)
    elif ext == ".docx":
        loader = Docx2txtLoader(path)
    elif ext == ".txt":
        loader = TextLoader(path, encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=["\n\n", "\n", " ", ""])
    splits = splitter.split_documents(docs)

    out: List[Dict] = []
    for d in splits:
        md = dict(d.metadata) if d.metadata else {}
        if "page" not in md and "page_number" in md:
            md["page"] = md["page_number"]
        out.append({"text": d.page_content, "metadata": md})
    return out


def write_json(path: str, data: dict) -> str:
    """
    Write data to a JSON file using capability name if available, otherwise use generic name.
    
    Args:
        path: Target file path
        data: Dictionary to write (capability model with 'name' field)

    Returns:
        Actual path where file was written
    """
    abs_target = Path(path).expanduser().resolve()
    abs_target.parent.mkdir(parents=True, exist_ok=True)
    
    # Use capability name if available in data, otherwise use default
    capability_name = data.get("name", "extracted_capability_model")
    # Sanitize capability name to be filesystem-safe
    safe_name = "".join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in capability_name).strip()
    
    candidate = abs_target.with_name(f"{safe_name}.json")
    
    # If file already exists, add a counter
    counter = 2
    while candidate.exists():
        candidate = abs_target.with_name(f"{safe_name}_{counter}.json")
        counter += 1
        
    with candidate.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"JSON written to {candidate}")
    return str(candidate)


def save_document_chunks(chunks: List[Dict], filename: str, chunks_dir: str = "document_chunks") -> str:
    """
    Save document chunks to a JSON file in the document chunks folder.
    
    Args:
        chunks: List of chunk dictionaries with 'text', 'metadata', and 'embedding' keys
        filename: Base filename for the chunks file (without extension)
        chunks_dir: Directory to save chunks (default: 'document_chunks')
        
    Returns:
        Actual path where chunks file was written
    """
    chunks_path = Path(chunks_dir)
    chunks_path.mkdir(parents=True, exist_ok=True)
    
    # Use the filename as-is for meaningful chunk filenames
    candidate = chunks_path / f"{filename}_chunks.json"
    
    # If file already exists, add a counter
    counter = 2
    while candidate.exists():
        candidate = chunks_path / f"{filename}_chunks_{counter}.json"
        counter += 1
    
    chunks_data = {
        "metadata": {
            "total_chunks": len(chunks),
            "chunk_size": len(chunks[0]["text"]) if chunks else 0,
            "created_at": datetime.now().isoformat(),
            "source_file": filename
        },
        "chunks": chunks
    }
    
    with candidate.open("w", encoding="utf-8") as f:
        json.dump(chunks_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Document chunks saved to {candidate}")
    return str(candidate)


EXTRACTION_INSTRUCTIONS = """
You are an expert Enterprise Architecture Consultant. Your job is to read a source document and produce a
normalized, ID-stable capability model with explicit relationships.

OUTPUT CONTRACT (must be STRICT JSON; no markdown; no commentary):

  {
  "id": 1,
  "name": "",
  "description": "",
  "vertical": "",
  "subvertical": "",
  "processes": [
    {
      "id": 1,
      "name": "",
      "level": "",
      "description": "",
      "category": "",
      "reference": "Reference content chunks for this process",
      "subprocesses": [
        {
          "id": 1,
          "name": "",
          "description": "",
          "category": "",
          "data_entities": [
            {
              "data_entity_id": 1,
              "data_entity_name": "",
              "data_entity_description": "",
              "data_elements": [
                {
                  "data_element_id": 1,
                  "data_element_name": "",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 2,
                  "data_element_name": "",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 3,
                  "data_element_name": "",
                  "data_element_description": ""
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}

REQUIREMENTS:
- Preserve relationships using explicit IDs
- Prefer nouns for Capabilities and Processes; Subprocesses are action-centric but concise.
- Data Entities are business nouns; Data Elements are atomic attributes on entities with datatypes.
- Add reference chunks from the document for the processes.
- Return only the JSON object (no extra text, no markdown).
"""


def _get_azure_llm():
    """
    Get Azure OpenAI LLM instances with caching to avoid repeated initialization.
    
    Returns:
        Tuple of (AzureChatOpenAI instance, AzureOpenAI embedding instance)
    """
    global _azure_llm_cache
    
    # Return cached instances if available
    if _azure_llm_cache["llm"] is not None and _azure_llm_cache["embedder"] is not None:
        logger.debug("Using cached Azure LLM clients")
        return _azure_llm_cache["llm"], _azure_llm_cache["embedder"]
    
    try:
        llm = get_azure_chat_openai_client()
        llm_embedd = get_azure_embedding_client()
        
        # Cache for future use
        _azure_llm_cache["llm"] = llm
        _azure_llm_cache["embedder"] = llm_embedd
        
        logger.info("Initialized and cached Azure LLM clients")
        return llm, llm_embedd
        
    except Exception as e:
        logger.error(f"Failed to retrieve Azure LLM: {e}")
        raise



def embed_chunks(chunks: List[Dict]) -> List[Dict]:
    """
    Embed document chunks using Azure OpenAI embedding service.
    
    NOTE: Only embed if embeddings are actually needed for downstream processing.
    If chunks are only sent to LLM, this step can be skipped to improve performance.
    
    Args:
        chunks: List of chunk dictionaries with 'text' and 'metadata' keys
        
    Returns:
        List of chunk dictionaries with 'embedding' added to each
    """
    try:
        _, llm_embedd = _get_azure_llm()
        
        texts = [chunk.get("text", "") for chunk in chunks]
        
        if not texts:
            return chunks
        
        resp = llm_embedd.embeddings.create(
            model="text-embedding-ada-002",
            input=texts
        )
        
        embeddings = [d.embedding for d in resp.data]
        
        for chunk, embedding in zip(chunks, embeddings):
            chunk["embedding"] = embedding
        
        logger.info(f"Embedded {len(chunks)} chunks")
        return chunks
        
    except Exception as e:
        logger.error(f"Failed to embed chunks: {e}")
        raise


def skip_embedding_chunks(chunks: List[Dict]) -> List[Dict]:
    """
    Skip embedding chunks to improve performance when embeddings are not needed.
    
    Args:
        chunks: List of chunk dictionaries
        
    Returns:
        Same chunks list (unmodified)
    """
    logger.info(f"Skipped embedding {len(chunks)} chunks - not required for LLM extraction")
    return chunks

def build_extraction_agent(pre_loaded_chunks: List[Dict]):
    """
    Build and configure the DeepAgent for capability extraction.
    
    Args:
        pre_loaded_chunks: Pre-loaded document chunks to avoid agent calling load_document
    
    Returns:
        Configured DeepAgent instance with tools and system prompt
    """
    def get_cached_chunks(path: str = None) -> List[Dict]:
        """Returns pre-loaded chunks instead of loading from disk"""
        return pre_loaded_chunks
    
    llm, _ = _get_azure_llm()
    agent = create_deep_agent(
        model=llm,
        tools=[get_cached_chunks, write_json],
        system_prompt=EXTRACTION_INSTRUCTIONS,
    )
    return agent


def _build_depth_instruction(extraction_depth: str) -> str:
    """
    Build depth-specific extraction instructions based on the requested level.
    
    Args:
        extraction_depth: One of "capability", "process", "subprocess", "data_entity", "data_element"
        
    Returns:
        Additional instructions string to append to the base extraction prompt
    """
    depth_map = {
        "capability": {
            "instruction": "DEPTH=CAPABILITY ONLY: Extract ONLY capability-level fields (id, name, description, vertical, subvertical). Set processes to empty []."
        },
        "process": {
            "instruction": "DEPTH=PROCESS: Extract Capability and Processes. For each process include id, name, level, description, category. Set all subprocesses arrays to empty []."
        },
        "subprocess": {
            "instruction": "DEPTH=SUBPROCESS: Extract Capability, Processes, and SubProcesses. For each subprocess include id, name, description, category. Set all data_entities arrays to empty []."
        },
        "data_entity": {
            "instruction": "DEPTH=DATA_ENTITY: Extract Capability, Processes, SubProcesses, and DataEntities. For each data entity include id, name, description. Set all data_elements arrays to empty []."
        },
        "data_element": {
            "instruction": "DEPTH=DATA_ELEMENT (MAXIMUM): Extract all levels completely: Capability -> Processes -> SubProcesses -> DataEntities -> DataElements."
        }
    }
    
    depth_config = depth_map.get(extraction_depth, depth_map["data_element"])
    
    return f"""

⚠️ STRICT EXTRACTION DEPTH CONSTRAINT: {extraction_depth.upper()}
{depth_config['instruction']}
DO NOT EXTRACT DEEPER THAN THIS LEVEL. VIOLATING THIS CONSTRAINT WILL CAUSE IMPORT FAILURES.
"""


def _enforce_depth(data: Dict, extraction_depth: str) -> Dict:
    """
    Post-process extracted data to strictly enforce the requested depth.
    Trims any data that goes deeper than the requested level.
    This is a hard guarantee regardless of what the LLM returned.

    Depth hierarchy:
        capability < process < subprocess < data_entity < data_element
    """
    DEPTH_ORDER = ["capability", "process", "subprocess", "data_entity", "data_element"]
    depth_idx = DEPTH_ORDER.index(extraction_depth) if extraction_depth in DEPTH_ORDER else len(DEPTH_ORDER) - 1

    result = {k: v for k, v in data.items() if k != "processes"}

    if depth_idx < 1:
        # capability only — no processes
        result["processes"] = []
        return result

    trimmed_processes = []
    for proc in data.get("processes", []):
        p = {k: v for k, v in proc.items() if k != "subprocesses"}

        if depth_idx < 2:
            # process only — no subprocesses
            p["subprocesses"] = []
            trimmed_processes.append(p)
            continue

        trimmed_subs = []
        for sp in proc.get("subprocesses", []):
            s = {k: v for k, v in sp.items() if k != "data_entities"}

            if depth_idx < 3:
                # subprocess only — no data entities
                s["data_entities"] = []
                trimmed_subs.append(s)
                continue

            trimmed_entities = []
            for de in sp.get("data_entities", []):
                e = {k: v for k, v in de.items() if k != "data_elements"}

                if depth_idx < 4:
                    # data_entity only — no data elements
                    e["data_elements"] = []
                else:
                    # data_element — keep everything
                    e["data_elements"] = de.get("data_elements", [])

                trimmed_entities.append(e)

            s["data_entities"] = trimmed_entities
            trimmed_subs.append(s)

        p["subprocesses"] = trimmed_subs
        trimmed_processes.append(p)

    result["processes"] = trimmed_processes
    return result


async def extract_capability_model(
    file_path: str,
    output_dir: Optional[str] = None,
    vertical: Optional[str] = None,
    subvertical: Optional[str] = None,
    extraction_depth: str = "data_element",
    skip_embeddings: bool = True
) -> AsyncGenerator[Dict, None]:
    """
    Extract capability model from a document using DeepAgent.
    
    Streams progress updates as the extraction proceeds, allowing the frontend
    to show real-time feedback during LLM processing.
    
    Performance optimizations:
    - Caching: Identical files with same config return cached results instantly
    - Larger chunks: 1500 chars (vs 500) reduces LLM processing overhead by ~66%
    
    Args:
        file_path: Path to the document file (.pdf, .docx, .txt)
        output_dir: Directory to save extracted JSON (optional)
        vertical: Manual vertical name override (optional, uses LLM value if not provided)
        subvertical: Manual subvertical name override (optional, uses LLM value if not provided)
        extraction_depth: Level to extract to - "capability", "process", "subprocess", "data_entity", "data_element"
        skip_embeddings: Whether to skip embedding chunks (default True for performance)
        
    Yields:
        Dictionary events with status and data:
        - {"status": "started", "filename": "..."}
        - {"status": "cache_hit", "data": {...cached model...}}
        - {"status": "loading", "progress": 0-100}
        - {"status": "extracting", "progress": 0-100}
        - {"status": "success", "data": {...extracted model...}, "output_path": "..."}
        - {"status": "error", "error": "error message"}
    """
    
    start_time = time.time()
    file_hash: Optional[str] = None
    run_config = {
        "vertical": vertical,
        "subvertical": subvertical,
        "extraction_depth": extraction_depth,
        "skip_embeddings": skip_embeddings,
    }

    try:
        # Log received parameters for verification - use repr() to see True None vs "None" string
        logger.info(f"[Extractor] Received parameters - file: {file_path}, vertical: {repr(vertical)}, subvertical: {repr(subvertical)}, extraction_depth: {repr(extraction_depth)}")
        
        # Validate file exists
        if not os.path.exists(file_path):
            _safe_write_ingestion_log(
                source_file=os.path.basename(file_path),
                file_hash=None,
                config=run_config,
                status="error",
                ontology={},
                guardrail={"applied": False, "reason": "file_not_found"},
                error=f"File not found: {file_path}",
                duration_ms=(time.time() - start_time) * 1000.0,
            )
            yield {
                "status": "error",
                "error": f"File not found: {file_path}"
            }
            return
        
        yield {
            "status": "started",
            "filename": os.path.basename(file_path)
        }
        
        # Check cache first
        file_hash = _compute_file_hash(file_path)
        config_hash = _compute_config_hash(vertical, subvertical, extraction_depth)
        
        if file_hash and config_hash:
            cached_result = _get_cached_extraction(file_hash, config_hash)
            if cached_result:
                logger.info("[CACHE] Returning cached extraction result - skipping LLM processing")
                # Enforce depth on cached result too
                cached_result = _enforce_depth(cached_result, extraction_depth)

                # Apply ontology guardrail to cached output as well so downstream
                # consumers get the same shape on every run.
                guardrail = _apply_ontology_guardrail(cached_result, capability_name=cached_result.get("name"))
                cached_result = guardrail["annotated_data"]

                yield {
                    "status": "cache_hit",
                    "progress": 90,
                    "message": "Retrieved from cache (instant)",
                    "data": cached_result,
                    "cached": True,
                    "ontology": guardrail["ontology_meta"],
                    "guardrail": guardrail["guardrail_summary"],
                }

                # Still need to return output_path and chunks_path for compatibility
                source_filename = Path(file_path).stem
                output_dir = "Json_Documents"
                output_path = os.path.join(output_dir, "extracted_capability_model.json")

                final_status = (
                    "success"
                    if (not guardrail["available"]) or guardrail["accepted"]
                    else "ontology_rejected"
                )

                _safe_write_ingestion_log(
                    source_file=os.path.basename(file_path),
                    file_hash=file_hash,
                    config=run_config,
                    status=final_status,
                    ontology=guardrail["ontology_meta"],
                    guardrail=guardrail["guardrail_summary"],
                    accepted_processes=guardrail["accepted"],
                    rejected_processes=guardrail["rejected"],
                    capability_name=cached_result.get("name"),
                    duration_ms=(time.time() - start_time) * 1000.0,
                    cached=True,
                )

                yield {
                    "status": "success",
                    "progress": 100,
                    "message": "Extraction complete (from cache)",
                    "data": cached_result,
                    "output_path": output_path,
                    "cached": True,
                    "ontology": guardrail["ontology_meta"],
                    "guardrail": guardrail["guardrail_summary"],
                }
                return
        
        # Step 1: Load and chunk the document ONCE, before agent creation
        yield {
            "status": "loading",
            "progress": 10,
            "message": "Loading document..."
        }
        
        chunks = load_document(file_path)
        chunk_count = len(chunks)
        logger.info(f"[Extractor] Loaded {chunk_count} chunks from document (chunk_size=1500 for performance)")
        
        yield {
            "status": "loading",
            "progress": 25,
            "message": f"Loaded {chunk_count} document chunks (optimized size)"
        }
        
        yield {
            "status": "loading",
            "progress": 30,
            "message": "Processing document chunks..."
        }
        
        # Skip expensive embedding step if not needed for extraction
        if skip_embeddings:
            chunks = skip_embedding_chunks(chunks)
        else:
            chunks = embed_chunks(chunks)
        
        logger.info(f"[Extractor] Processed {chunk_count} chunks (embeddings={'skipped' if skip_embeddings else 'enabled'})")
        
        source_filename = Path(file_path).stem
        chunks_output_path = save_document_chunks(chunks, source_filename)
        logger.info(f"Chunks saved to: {chunks_output_path}")

        yield {
            "status": "loading",
            "progress": 35,
            "message": f"Saved {chunk_count} chunks to document_chunks folder"
        }

        # ------------------------------------------------------------------
        # Step 1.5 — DOCUMENT-LEVEL ONTOLOGY GATE (pre-LLM)
        # ------------------------------------------------------------------
        # Before paying for an LLM call we ask: does this document actually
        # talk about anything FIBO knows about? If the best concept-vs-chunk
        # score is below COMPASS_DOC_RELEVANCE_THRESHOLD we reject the
        # document right here. If it passes, the top FIBO concepts are
        # injected into the agent's system prompt to keep extraction on rails.
        yield {
            "status": "validating_document",
            "progress": 38,
            "message": "Validating document against FIBO ontology...",
        }

        doc_gate = _validate_document_against_ontology(chunks)

        if doc_gate["available"] and not doc_gate["is_relevant"]:
            top_concepts = doc_gate["relevance"].get("top_concepts", [])
            top_label = top_concepts[0]["concept_label"] if top_concepts else "<no concept>"
            top_score = top_concepts[0]["best_chunk_score"] if top_concepts else 0.0
            doc_threshold = doc_gate["relevance"].get("doc_threshold", 0.0)
            logger.info(
                "[Extractor] Document rejected by FIBO gate: %s",
                doc_gate.get("rejection_reason"),
            )

            _safe_write_ingestion_log(
                source_file=os.path.basename(file_path),
                file_hash=file_hash,
                config=run_config,
                status="document_rejected",
                ontology=doc_gate["ontology_meta"],
                guardrail={
                    "applied": False,
                    "reason": "rejected_by_document_gate",
                    "rejection_reason": doc_gate.get("rejection_reason"),
                },
                accepted_processes=[],
                rejected_processes=[],
                capability_name=None,
                duration_ms=(time.time() - start_time) * 1000.0,
                cached=False,
                extras={
                    "document_relevance": doc_gate["relevance"],
                    "chunks_path": chunks_output_path,
                    "chunk_count": chunk_count,
                },
            )

            yield {
                "status": "document_rejected",
                "progress": 100,
                "message": (
                    f"Document does not align with the FIBO ontology "
                    f"(top match: '{top_label}' score={top_score:.3f}, "
                    f"threshold={doc_threshold:.3f}). "
                    f"Skipping LLM extraction."
                ),
                "ontology": doc_gate["ontology_meta"],
                "document_relevance": doc_gate["relevance"],
                "ontology_status": "document_rejected",
                "data": None,
            }
            return

        if doc_gate["available"]:
            top_concepts = doc_gate["relevance"].get("top_concepts", [])
            top_label = top_concepts[0]["concept_label"] if top_concepts else "<no concept>"
            top_score = top_concepts[0]["best_chunk_score"] if top_concepts else 0.0
            yield {
                "status": "document_validated",
                "progress": 40,
                "message": (
                    f"Document passes FIBO gate. Top concept: "
                    f"'{top_label}' (score={top_score:.3f}). "
                    f"Extraction will be constrained to {len(top_concepts)} "
                    f"FIBO concept(s)."
                ),
                "ontology": doc_gate["ontology_meta"],
                "document_relevance": doc_gate["relevance"],
            }

        # Step 2: Build extraction instructions based on depth
        yield {
            "status": "extracting",
            "progress": 42,
            "message": "Initializing extraction agent..."
        }

        depth_instructions = _build_depth_instruction(extraction_depth)
        focus_instructions = doc_gate.get("focus_prompt") or ""
        agent_instructions = EXTRACTION_INSTRUCTIONS + focus_instructions + depth_instructions
        
        # Create agent with pre-loaded chunks (prevents agent from re-loading document)
        agent = build_extraction_agent(chunks)
        # Update the agent's system prompt with depth instructions
        agent.system_prompt = agent_instructions
        
        output_dir = "Json_Documents"
        output_path = os.path.join(output_dir, "extracted_capability_model.json")
        
        # Step 3: Build task - NO longer ask agent to load_document since it's pre-loaded
        yield {
            "status": "extracting",
            "progress": 50,
            "message": "Processing with LLM (this may take a moment)..."
        }
        
        # Build task WITHOUT load_document tool call - chunks are already provided
        task_parts = [
            "The document has been pre-loaded and chunked. The chunks are available to you via the get_cached_chunks tool.",
            "Your task:",
            "1) Call tool=get_cached_chunks (no parameters needed) to retrieve the pre-loaded chunks.",
            "2) Analyze all chunks and construct the JSON capability model per OUTPUT CONTRACT.",
            "\nMANDATORY CONFIGURATION (MUST FOLLOW):",
        ]
        
        if vertical:
            task_parts.append(f"- VERTICAL NAME: Set to '{vertical}' (user-provided, do not override)")
        if subvertical:
            task_parts.append(f"- SUBVERTICAL NAME: Set to '{subvertical}' (user-provided, do not override)")
        
        task_parts.append(f"- EXTRACTION DEPTH: {extraction_depth} (STRICT - do not extract beyond this level)")
        task_parts.append(f"\n3) Call tool=write_json with path=`{output_path}` and the JSON object.")
        
        task = "\n".join(task_parts)
        
        logger.info(f"[Extractor] Agent task:\n{task}")
        logger.info(f"[Extractor] Configuration - vertical: {repr(vertical)}, subvertical: {repr(subvertical)}, depth: {repr(extraction_depth)}")
        
        # Step 4: Run agent synchronously (agent.invoke is already blocking)
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": task}]})
        except Exception as e:
            logger.error(f"[Extractor] Agent execution failed: {e}", exc_info=True)
            _safe_write_ingestion_log(
                source_file=os.path.basename(file_path),
                file_hash=file_hash,
                config=run_config,
                status="error",
                ontology={},
                guardrail={"applied": False, "reason": "agent_execution_failed"},
                error=f"Agent execution failed: {str(e)}",
                duration_ms=(time.time() - start_time) * 1000.0,
            )
            yield {
                "status": "error",
                "error": f"Agent execution failed: {str(e)}"
            }
            return
        
        logger.info(f"[Extractor] Agent execution completed")
        
        yield {
            "status": "extracting",
            "progress": 75,
            "message": "Extracting JSON from LLM response..."
        }
        
        # Step 5: Extract JSON from response
        final_msg = result["messages"][-1].content if "messages" in result else str(result)
        
        # Try to parse JSON from the response
        extracted_data = None
        
        # Try direct JSON parse
        try:
            extracted_data = json.loads(final_msg)
            logger.info("[Extractor] Successfully parsed JSON from agent response")
        except json.JSONDecodeError:
            # Try to find JSON in the response (between { and })
            import re
            json_match = re.search(r'\{.*\}', final_msg, re.DOTALL)
            if json_match:
                try:
                    extracted_data = json.loads(json_match.group())
                    logger.info("[Extractor] Successfully extracted JSON from agent response text")
                except json.JSONDecodeError:
                    pass
        
        if not extracted_data:
            logger.error(f"[Extractor] Failed to parse JSON from response: {final_msg[:500]}")
            _safe_write_ingestion_log(
                source_file=os.path.basename(file_path),
                file_hash=file_hash,
                config=run_config,
                status="error",
                ontology={},
                guardrail={"applied": False, "reason": "json_parse_failed"},
                error="Failed to extract valid JSON from LLM response",
                duration_ms=(time.time() - start_time) * 1000.0,
                extras={"raw_response_preview": final_msg[:500]},
            )
            yield {
                "status": "error",
                "error": "Failed to extract valid JSON from LLM response",
                "raw_response": final_msg[:500]  # Send first 500 chars for debugging
            }
            return
        
        # Step 6: Apply manual overrides if provided
        if vertical:
            extracted_data["vertical"] = vertical
        if subvertical:
            extracted_data["subvertical"] = subvertical
        
        # Step 6b: Enforce extraction depth by trimming data beyond the requested level
        extracted_data = _enforce_depth(extracted_data, extraction_depth)
        logger.info(f"[Extractor] Enforced depth '{extraction_depth}' on extracted data")

        # Step 6c: Save raw (pre-guardrail) extraction to cache so re-runs can
        # apply the guardrail again without paying for the LLM call.
        if file_hash and config_hash:
            try:
                _save_extraction_to_cache(file_hash, config_hash, extracted_data)
                logger.info("[CACHE] Saved extraction result to cache for future reuse")
            except Exception as cache_exc:
                logger.warning(f"[CACHE] Failed to save extraction: {cache_exc}")

        # Step 6d: Apply FIBO ontology guardrail. Only quality-aligned processes
        # survive (default: at most 1 process per document, configurable via
        # the COMPASS_GUARDRAIL_THRESHOLD / COMPASS_GUARDRAIL_MAX_PROCESSES
        # environment variables).
        yield {
            "status": "validating",
            "progress": 80,
            "message": "Validating extracted processes against FIBO ontology...",
        }

        # Pass Stage 1's top concept IRIs so the guardrail can run a
        # hierarchy-consistency check (matched concept must live in the
        # same sub-tree as something the document gate flagged).
        doc_top_iris = [
            c.get("concept_iri")
            for c in (doc_gate.get("relevance", {}).get("top_concepts") or [])
            if c.get("concept_iri")
        ]
        guardrail = _apply_ontology_guardrail(
            extracted_data,
            capability_name=extracted_data.get("name"),
            document_top_concept_iris=doc_top_iris,
        )
        extracted_data = guardrail["annotated_data"]

        yield {
            "status": "ontology_applied",
            "progress": 90,
            "message": (
                "Ontology guardrail unavailable; passing all processes through."
                if not guardrail["available"]
                else f"FIBO guardrail kept {len(guardrail['accepted'])}/"
                     f"{guardrail['guardrail_summary'].get('candidate_count', 0)} processes "
                     f"(threshold={guardrail['guardrail_summary'].get('threshold')}, "
                     f"max={guardrail['guardrail_summary'].get('max_processes')})"
            ),
            "ontology": guardrail["ontology_meta"],
            "guardrail": guardrail["guardrail_summary"],
        }

        # Step 7: Save the (guardrail-filtered) extracted data
        final_path = write_json(output_path, extracted_data)
        logger.info(f"[Extractor] Saved extracted model to: {final_path}")

        # Step 8: Re-save chunks with the actual capability name now that we have it
        capability_name = extracted_data.get("name", "capability")
        safe_capability_name = "".join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in capability_name).strip()
        chunks_output_path = save_document_chunks(chunks, safe_capability_name)
        logger.info(f"[Extractor] Re-saved chunks with capability name to: {chunks_output_path}")

        final_status = (
            "success"
            if (not guardrail["available"]) or guardrail["accepted"]
            else "ontology_rejected"
        )

        _safe_write_ingestion_log(
            source_file=os.path.basename(file_path),
            file_hash=file_hash,
            config=run_config,
            status=final_status,
            ontology=guardrail["ontology_meta"],
            guardrail=guardrail["guardrail_summary"],
            accepted_processes=guardrail["accepted"],
            rejected_processes=guardrail["rejected"],
            capability_name=extracted_data.get("name"),
            duration_ms=(time.time() - start_time) * 1000.0,
            cached=False,
            extras={
                "output_path": final_path,
                "chunks_path": chunks_output_path,
                "chunk_count": chunk_count,
                "document_relevance": doc_gate.get("relevance", {}),
                "document_gate_available": doc_gate.get("available"),
            },
        )

        yield {
            "status": "success",
            "progress": 100,
            "message": (
                "Extraction complete"
                if final_status == "success"
                else "Extraction complete but no process passed the FIBO ontology guardrail"
            ),
            "data": extracted_data,
            "output_path": final_path,
            "chunks_path": chunks_output_path,
            "chunk_count": chunk_count,
            "cached": False,
            "ontology": guardrail["ontology_meta"],
            "guardrail": guardrail["guardrail_summary"],
            "document_relevance": doc_gate.get("relevance", {}),
            "ontology_status": final_status,
        }

    except Exception as e:
        logger.error(f"Extraction failed: {type(e).__name__}: {e}", exc_info=True)
        _safe_write_ingestion_log(
            source_file=os.path.basename(file_path) if file_path else "unknown",
            file_hash=file_hash,
            config=run_config,
            status="error",
            ontology={},
            guardrail={"applied": False, "reason": "unhandled_exception"},
            error=f"{type(e).__name__}: {e}",
            duration_ms=(time.time() - start_time) * 1000.0,
        )
        yield {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }


# ---------------------------------------------------------------------------
# Human-in-the-Loop (HITL) — per-stage extraction primitives
#
# The streaming `extract_capability_model` runs every stage end-to-end. The
# Compass UI now drives ingestion as a 3-step wizard so a human can review
# the FIBO document gate, then the raw LLM extraction, then the guardrail
# before anything lands in Neo4j. Each helper below corresponds to one of
# those stages and is a plain async function (no streaming) so the upload
# routes can drive them from a session state machine.
# ---------------------------------------------------------------------------


def prepare_chunks_and_gate(
    file_path: str,
    extraction_depth: str = "data_element",
    skip_embeddings: bool = True,
) -> Dict:
    """Stage 1 of the HITL flow: load chunks, save them, run FIBO document gate.

    Does NOT call the LLM. Returns everything the UI needs to decide whether
    to proceed to extraction:

        {
          "filename":          basename of the source document,
          "file_hash":         sha256 of the raw bytes (used for caching),
          "chunks":            list[{"text", "metadata"}] — kept in memory
                                 so step 2 can pass it straight to the agent,
          "chunk_count":       int,
          "chunks_path":       on-disk JSON (also used by import-to-graph),
          "doc_gate":          full payload from `_validate_document_against_ontology`,
          "is_relevant":       bool — short-circuit for step 2,
          "rejection_reason":  optional human-readable reason,
          "evidence_chunks":   list[{ "text", "score", "concept_label",
                                       "concept_iri", "chunk_index" }] — the
                                  passed/matching chunks the user is shown
                                  in step 1.
        }

    The chunks file is persisted now (rather than at the end of the run) so
    the user can always re-import or inspect it.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    file_hash = _compute_file_hash(file_path)

    chunks = load_document(file_path)
    chunk_count = len(chunks)

    if skip_embeddings:
        chunks = skip_embedding_chunks(chunks)
    else:
        chunks = embed_chunks(chunks)

    source_filename = Path(file_path).stem
    chunks_path = save_document_chunks(chunks, source_filename)

    doc_gate = _validate_document_against_ontology(chunks)
    relevance = doc_gate.get("relevance") or {}
    top_concepts = relevance.get("top_concepts") or []
    chunk_threshold = relevance.get("chunk_threshold", 0.0)

    evidence_chunks = _build_evidence_chunks(
        top_concepts, chunks, chunk_threshold
    )

    logger.info(
        "[HITL Stage 1] '%s': %d chunks, gate=%s, top_concepts=%d, evidence=%d",
        os.path.basename(file_path),
        chunk_count,
        doc_gate.get("is_relevant"),
        len(top_concepts),
        len(evidence_chunks),
    )

    return {
        "filename": os.path.basename(file_path),
        "file_hash": file_hash,
        "chunks": chunks,
        "chunk_count": chunk_count,
        "chunks_path": chunks_path,
        "doc_gate": doc_gate,
        "is_relevant": bool(doc_gate.get("is_relevant")),
        "rejection_reason": doc_gate.get("rejection_reason"),
        "evidence_chunks": evidence_chunks,
        "extraction_depth": extraction_depth,
    }


def _build_evidence_chunks(
    top_concepts: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    chunk_threshold: float,
) -> List[Dict[str, Any]]:
    """Pick the document chunks that drove each top FIBO concept's score.

    The UI's step 1 shows the user *why* the document was accepted. For
    each top concept we surface the chunk that scored highest against it
    (its ``best_chunk_index``), with score, the matched chunk text, and a
    short excerpt. Duplicates are de-duplicated by ``(chunk_index, concept_iri)``
    so a chunk is only shown once.
    """
    evidence: List[Dict[str, Any]] = []
    seen: set = set()

    for hit in top_concepts:
        chunk_idx = hit.get("best_chunk_index")
        concept_iri = hit.get("concept_iri")
        if chunk_idx is None or chunk_idx < 0 or chunk_idx >= len(chunks):
            continue
        key = (chunk_idx, concept_iri)
        if key in seen:
            continue
        seen.add(key)

        chunk = chunks[chunk_idx]
        text = (chunk.get("text") or "").strip()
        evidence.append({
            "chunk_index": chunk_idx,
            "concept_iri": concept_iri,
            "concept_label": hit.get("concept_label"),
            "concept_definition": hit.get("concept_definition"),
            "score": hit.get("best_chunk_score"),
            "matched_via": hit.get("matched_via"),
            "matched_synonym": hit.get("matched_synonym"),
            "passes_chunk_threshold": (
                hit.get("best_chunk_score") is not None
                and hit.get("best_chunk_score") >= chunk_threshold
            ),
            "chunk_threshold": chunk_threshold,
            "page": (chunk.get("metadata") or {}).get("page"),
            "text": text,
            "excerpt": (text[:600] + "...") if len(text) > 600 else text,
        })

    return evidence


def run_llm_extraction(
    chunks: List[Dict],
    doc_gate: Dict,
    vertical: Optional[str] = None,
    subvertical: Optional[str] = None,
    extraction_depth: str = "data_element",
    file_hash: Optional[str] = None,
    capability: Optional[str] = None,
) -> Dict:
    """Stage 2 of the HITL flow: run the DeepAgent extractor on the chunks.

    Returns the *raw* extracted model BEFORE the FIBO post-extraction
    guardrail is applied. The UI shows this to the user for approval; the
    guardrail is applied in stage 3 only after the user clicks "Next".

    A best-effort cache lookup uses the file_hash + config_hash pair so a
    repeat run on the same document doesn't re-pay for the LLM call.

    When ``capability`` is provided the LLM is instructed to use that as
    the capability name, and the resulting model's ``name`` is forced to
    match so downstream process/subprocess extraction is scoped to that
    capability instead of one the LLM might guess from the document.
    """
    capability_clean = (capability or "").strip() or None
    config_hash = _compute_config_hash(
        vertical, subvertical, extraction_depth, capability_clean,
    )

    if file_hash and config_hash:
        cached = _get_cached_extraction(file_hash, config_hash)
        if cached:
            logger.info("[HITL Stage 2] Cache hit — returning cached extraction")
            cached = _enforce_depth(cached, extraction_depth)
            if vertical:
                cached["vertical"] = vertical
            if subvertical:
                cached["subvertical"] = subvertical
            if capability_clean:
                cached["name"] = capability_clean
            return cached

    depth_instructions = _build_depth_instruction(extraction_depth)
    focus_instructions = (doc_gate.get("focus_prompt") or "")
    agent_instructions = EXTRACTION_INSTRUCTIONS + focus_instructions + depth_instructions

    agent = build_extraction_agent(chunks)
    agent.system_prompt = agent_instructions

    output_dir = "Json_Documents"
    output_path = os.path.join(output_dir, "extracted_capability_model.json")

    task_parts = [
        "The document has been pre-loaded and chunked. The chunks are available to you via the get_cached_chunks tool.",
        "Your task:",
        "1) Call tool=get_cached_chunks (no parameters needed) to retrieve the pre-loaded chunks.",
        "2) Analyze all chunks and construct the JSON capability model per OUTPUT CONTRACT.",
        "\nMANDATORY CONFIGURATION (MUST FOLLOW):",
    ]
    if vertical:
        task_parts.append(f"- VERTICAL NAME: Set to '{vertical}' (user-provided, do not override)")
    if subvertical:
        task_parts.append(f"- SUBVERTICAL NAME: Set to '{subvertical}' (user-provided, do not override)")
    if capability_clean:
        task_parts.append(
            f"- CAPABILITY NAME: Set the top-level `name` field to '{capability_clean}' "
            f"(user-provided, do not override). All processes and subprocesses you "
            f"extract MUST belong to this capability — only include processes that are "
            f"clearly part of '{capability_clean}'."
        )
    task_parts.append(
        f"- EXTRACTION DEPTH: {extraction_depth} (STRICT - do not extract beyond this level)"
    )
    task_parts.append(f"\n3) Call tool=write_json with path=`{output_path}` and the JSON object.")
    task = "\n".join(task_parts)

    logger.info(
        f"[HITL Stage 2] Running LLM agent (depth={extraction_depth}, "
        f"capability={capability_clean!r})"
    )
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    final_msg = result["messages"][-1].content if "messages" in result else str(result)

    extracted_data: Optional[Dict] = None
    try:
        extracted_data = json.loads(final_msg)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", final_msg, re.DOTALL)
        if match:
            try:
                extracted_data = json.loads(match.group())
            except json.JSONDecodeError:
                pass

    if not extracted_data:
        raise ValueError(
            "Failed to extract valid JSON from LLM response. "
            f"First 500 chars: {final_msg[:500]}"
        )

    if vertical:
        extracted_data["vertical"] = vertical
    if subvertical:
        extracted_data["subvertical"] = subvertical
    if capability_clean:
        extracted_data["name"] = capability_clean

    extracted_data = _enforce_depth(extracted_data, extraction_depth)

    if file_hash and config_hash:
        try:
            _save_extraction_to_cache(file_hash, config_hash, extracted_data)
        except Exception as cache_exc:
            logger.warning(f"[HITL Stage 2] Failed to cache extraction: {cache_exc}")

    return extracted_data


def apply_guardrail_to_extraction(
    extracted_data: Dict,
    doc_gate: Optional[Dict] = None,
    document_top_concept_iris: Optional[List[str]] = None,
) -> Dict:
    """Stage 3 of the HITL flow: apply the FIBO guardrail to the extraction.

    ``document_top_concept_iris`` may be passed directly; if not, they are
    extracted from ``doc_gate.relevance.top_concepts`` (Stage 1 output).

    Returns:
        {
          "annotated_data":   <model trimmed to accepted processes only>,
          "ontology":         <ontology metadata>,
          "guardrail":        <full guardrail summary>,
          "accepted":         <list[GuardrailMatch.to_dict()]>,
          "rejected":         <list[GuardrailMatch.to_dict()]>,
          "ontology_status":  "success" | "ontology_rejected",
          "available":        <bool — whether the ontology service was usable>,
        }
    """
    if document_top_concept_iris is None:
        relevance = (doc_gate or {}).get("relevance") or {}
        document_top_concept_iris = [
            c.get("concept_iri")
            for c in (relevance.get("top_concepts") or [])
            if c.get("concept_iri")
        ]

    guardrail = _apply_ontology_guardrail(
        extracted_data,
        capability_name=extracted_data.get("name"),
        document_top_concept_iris=document_top_concept_iris,
    )

    annotated_data = guardrail["annotated_data"]
    final_status = (
        "success"
        if (not guardrail["available"]) or guardrail["accepted"]
        else "ontology_rejected"
    )

    return {
        "annotated_data": annotated_data,
        "ontology": guardrail["ontology_meta"],
        "guardrail": guardrail["guardrail_summary"],
        "accepted": guardrail["accepted"],
        "rejected": guardrail["rejected"],
        "ontology_status": final_status,
        "available": guardrail["available"],
    }


def validate_extracted_model(model: Dict) -> tuple[bool, List[str]]:
    """
    Validate that extracted model has required structure.
    
    Args:
        model: The extracted capability model
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check top-level fields
    if not isinstance(model, dict):
        errors.append("Model must be a JSON object")
        return False, errors
    
    required_fields = ["name", "vertical", "processes"]
    for field in required_fields:
        if field not in model:
            errors.append(f"Missing required field: {field}")
    
    # Check processes structure
    if "processes" in model:
        if not isinstance(model["processes"], list):
            errors.append("'processes' must be an array")
        else:
            for i, proc in enumerate(model["processes"]):
                if not isinstance(proc, dict):
                    errors.append(f"Process {i} must be an object")
                elif "name" not in proc:
                    errors.append(f"Process {i} missing 'name' field")
    
    return len(errors) == 0, errors
