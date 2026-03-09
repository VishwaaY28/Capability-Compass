"""
DeepAgent-based capability model extractor.

This module handles PDF/document parsing and capability model extraction
using DeepAgent with man-in-the-middle callback streaming.
"""

import os
import json
import logging
import asyncio
import tempfile
from typing import List, Dict, AsyncGenerator, Optional
from pathlib import Path
from datetime import datetime
from deepagents import create_deep_agent
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from langchain_openai import AzureChatOpenAI
from langchain_core.callbacks.base import BaseCallbackHandler

logger = logging.getLogger(__name__)


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


def load_document(path: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[Dict]:
    """
    Load .pdf/.docx/.txt and return chunk dicts: [{"text": "...", "metadata": {...}}]
    
    Args:
        path: File path to load
        chunk_size: Character size for text chunks
        chunk_overlap: Overlap between chunks
        
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
    Write data to a JSON file with timestamp suffix to avoid overwrites.
    
    Args:
        path: Target file path
        data: Dictionary to write

    Returns:
        Actual path where file was written
    """
    abs_target = Path(path).expanduser().resolve()
    abs_target.parent.mkdir(parents=True, exist_ok=True)
    
    base = abs_target.stem if abs_target.suffix else abs_target.name
    ext = abs_target.suffix if abs_target.suffix else ".json"
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = abs_target.with_name(f"{base}_{ts}{ext}")
    
    counter = 2
    while candidate.exists():
        candidate = abs_target.with_name(f"{base}_{ts}_{counter}{ext}")
        counter += 1
        
    with candidate.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"JSON written to {candidate}")
    return str(candidate)


def save_document_chunks(chunks: List[Dict], filename: str, chunks_dir: str = "document_chunks") -> str:
    """
    Save document chunks to a JSON file in the document chunks folder.
    
    Args:
        chunks: List of chunk dictionaries with 'text' and 'metadata' keys
        filename: Base filename for the chunks file (without extension)
        chunks_dir: Directory to save chunks (default: 'document_chunks')
        
    Returns:
        Actual path where chunks file was written
    """
    chunks_path = Path(chunks_dir)
    chunks_path.mkdir(parents=True, exist_ok=True)
    
    base = filename
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = chunks_path / f"{base}_chunks_{ts}.json"
    
    # Handle file collisions
    counter = 2
    while candidate.exists():
        candidate = chunks_path / f"{base}_chunks_{ts}_{counter}.json"
        counter += 1
    
    # Prepare chunks data with metadata
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
    Initialize Azure OpenAI LLM with credentials from Key Vault.
    
    Returns:
        AzureChatOpenAI instance configured for capability extraction
    """
    try:
        credential = DefaultAzureCredential()
        key_vault_url = "https://fstodevazureopenai.vault.azure.net/"
        kv_client = SecretClient(vault_url=key_vault_url, credential=credential)

        api_version = kv_client.get_secret("llm-mini-version").value
        api_key = kv_client.get_secret("llm-api-key").value
        endpoint = kv_client.get_secret("llm-base-endpoint").value
        deployment = kv_client.get_secret("llm-5").value

        llm = AzureChatOpenAI(
            azure_deployment=deployment,
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
            streaming=True,
        )
        return llm
        
    except Exception as e:
        logger.error(f"Failed to initialize Azure LLM: {e}")
        raise


def build_extraction_agent(pre_loaded_chunks: List[Dict]):
    """
    Build and configure the DeepAgent for capability extraction.
    
    Args:
        pre_loaded_chunks: Pre-loaded document chunks to avoid agent calling load_document
    
    Returns:
        Configured DeepAgent instance with tools and system prompt
    """
    # Create a wrapper function that returns pre-loaded chunks (prevents re-loading)
    def get_cached_chunks(path: str = None) -> List[Dict]:
        """Returns pre-loaded chunks instead of loading from disk"""
        return pre_loaded_chunks
    
    llm = _get_azure_llm()
    agent = create_deep_agent(
        model=llm,
        tools=[get_cached_chunks, write_json],  # Use cached chunks getter, not file loader
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


async def extract_capability_model(
    file_path: str,
    output_dir: Optional[str] = None,
    vertical: Optional[str] = None,
    subvertical: Optional[str] = None,
    extraction_depth: str = "data_element"
) -> AsyncGenerator[Dict, None]:
    """
    Extract capability model from a document using DeepAgent.
    
    Streams progress updates as the extraction proceeds, allowing the frontend
    to show real-time feedback during LLM processing.
    
    Args:
        file_path: Path to the document file (.pdf, .docx, .txt)
        output_dir: Directory to save extracted JSON (optional)
        vertical: Manual vertical name override (optional, uses LLM value if not provided)
        subvertical: Manual subvertical name override (optional, uses LLM value if not provided)
        extraction_depth: Level to extract to - "capability", "process", "subprocess", "data_entity", "data_element"
        
    Yields:
        Dictionary events with status and data:
        - {"status": "started", "filename": "..."}
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
        
        # Step 1: Load and chunk the document ONCE, before agent creation
        yield {
            "status": "loading",
            "progress": 10,
            "message": "Loading document..."
        }
        
        chunks = load_document(file_path)
        chunk_count = len(chunks)
        logger.info(f"[Extractor] Loaded {chunk_count} chunks from document")
        
        yield {
            "status": "loading",
            "progress": 25,
            "message": f"Loaded {chunk_count} document chunks"
        }
        
        # Save chunks to document_chunks folder
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
        
        # Step 4: Run agent ONCE with pre-loaded context
        def run_agent():
            return agent.invoke({"messages": [{"role": "user", "content": task}]})
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_agent)
        
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
        
        # Step 7: Save the extracted data
        final_path = write_json(output_path, extracted_data)
        logger.info(f"[Extractor] Saved extracted model to: {final_path}")
        
        yield {
            "status": "success",
            "progress": 100,
            "message": "Extraction complete",
            "data": extracted_data,
            "output_path": final_path,
            "chunks_path": chunks_output_path,
            "chunk_count": chunk_count
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
