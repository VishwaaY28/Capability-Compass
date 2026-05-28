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
from typing import List, Dict, AsyncGenerator, Optional
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


def _compute_config_hash(vertical: Optional[str], subvertical: Optional[str], extraction_depth: str) -> str:
    """
    Compute hash of extraction configuration parameters.
    
    Args:
        vertical: Vertical name
        subvertical: SubVertical name
        extraction_depth: Extraction depth level
        
    Returns:
        Hexadecimal hash string
    """
    config_str = f"{vertical or ''}|{subvertical or ''}|{extraction_depth}"
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
    
    try:
        # Log received parameters for verification - use repr() to see True None vs "None" string
        logger.info(f"[Extractor] Received parameters - file: {file_path}, vertical: {repr(vertical)}, subvertical: {repr(subvertical)}, extraction_depth: {repr(extraction_depth)}")
        
        # Validate file exists
        if not os.path.exists(file_path):
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
                yield {
                    "status": "cache_hit",
                    "progress": 100,
                    "message": "Retrieved from cache (instant)",
                    "data": cached_result,
                    "cached": True
                }
                # Still need to return output_path and chunks_path for compatibility
                # Generate paths even though we're using cache
                source_filename = Path(file_path).stem
                output_dir = "Json_Documents"
                output_path = os.path.join(output_dir, "extracted_capability_model.json")
                
                yield {
                    "status": "success",
                    "progress": 100,
                    "message": "Extraction complete (from cache)",
                    "data": cached_result,
                    "output_path": output_path,
                    "cached": True
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
        
        # Step 2: Build extraction instructions based on depth
        yield {
            "status": "extracting",
            "progress": 40,
            "message": "Initializing extraction agent..."
        }
        
        depth_instructions = _build_depth_instruction(extraction_depth)
        agent_instructions = EXTRACTION_INSTRUCTIONS + depth_instructions
        
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
        
        # Step 7: Save the extracted data
        final_path = write_json(output_path, extracted_data)
        logger.info(f"[Extractor] Saved extracted model to: {final_path}")
        
        # Step 8: Re-save chunks with the actual capability name now that we have it
        capability_name = extracted_data.get("name", "capability")
        safe_capability_name = "".join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in capability_name).strip()
        chunks_output_path = save_document_chunks(chunks, safe_capability_name)
        logger.info(f"[Extractor] Re-saved chunks with capability name to: {chunks_output_path}")
        
        # Step 9: Save to cache for future use
        if file_hash and config_hash:
            _save_extraction_to_cache(file_hash, config_hash, extracted_data)
            logger.info("[CACHE] Saved extraction result to cache for future reuse")
        
        yield {
            "status": "success",
            "progress": 100,
            "message": "Extraction complete",
            "data": extracted_data,
            "output_path": final_path,
            "chunks_path": chunks_output_path,
            "chunk_count": chunk_count,
            "cached": False
        }
        
    except Exception as e:
        logger.error(f"Extraction failed: {type(e).__name__}: {e}", exc_info=True)
        yield {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
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
