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


def load_document(path: str, chunk_size: int = 1800, chunk_overlap: int = 200) -> List[Dict]:
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
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
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


def build_extraction_agent():
    """
    Build and configure the DeepAgent for capability extraction.
    
    Returns:
        Configured DeepAgent instance with tools and system prompt
    """
    llm = _get_azure_llm()
    agent = create_deep_agent(
        model=llm,
        tools=[load_document, write_json],
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
        
        # Step 1: Load and chunk the document
        yield {
            "status": "loading",
            "progress": 10,
            "message": "Loading document..."
        }
        
        chunks = load_document(file_path)
        chunk_count = len(chunks)
        yield {
            "status": "loading",
            "progress": 30,
            "message": f"Loaded {chunk_count} document chunks"
        }
        # Step 2: Build the agent
        yield {
            "status": "extracting",
            "progress": 40,
            "message": "Initializing extraction agent..."
        }
        
        # Build extraction instructions based on depth and manual overrides
        depth_instructions = _build_depth_instruction(extraction_depth)
        agent_instructions = EXTRACTION_INSTRUCTIONS + depth_instructions
        
        # Create agent with modified instructions
        llm = _get_azure_llm()
        agent = create_deep_agent(
            model=llm,
            tools=[load_document, write_json],
            system_prompt=agent_instructions,
        )
        
        output_dir = "Json_Documents"
        # Step 3: Create temp output path
        if output_dir is None:
            output_dir = tempfile.gettempdir()
        
        output_path = os.path.join(output_dir, "extracted_capability_model.json")
        
        # Step 4: Invoke the agent with explicit task including vertical, subvertical, and depth
        yield {
            "status": "extracting",
            "progress": 50,
            "message": "Processing with LLM (this may take a moment)..."
        }
        
        # Build task with user-provided configuration
        task_parts = [
            f"1) Call tool=load_document with path=`{file_path}` to ingest content.",
            "2) Analyze all chunks and construct the JSON capability model per OUTPUT CONTRACT.",
            "\nMANDATORY CONFIGURATION (MUST FOLLOW):",
        ]
        
        # Always include configuration even if defaults
        if vertical:
            task_parts.append(f"- VERTICAL NAME: Set to '{vertical}' (user-provided, do not override)")
        if subvertical:
            task_parts.append(f"- SUBVERTICAL NAME: Set to '{subvertical}' (user-provided, do not override)")
        
        task_parts.append(f"- EXTRACTION DEPTH: {extraction_depth} (STRICT - do not extract beyond this level)")
        task_parts.append(f"\n3) Call tool=write_json with path=`{output_path}` and the JSON object.")
        
        task = "\n".join(task_parts)
        
        # Log the complete task being sent to agent
        logger.info(f"[Extractor] Task being sent to agent:\n{task}")
        logger.info(f"[Extractor] Configuration summary - vertical: {repr(vertical)}, subvertical: {repr(subvertical)}, depth: {repr(extraction_depth)}")
        
        # Run in executor to avoid blocking
        def run_agent():
            return agent.invoke({"messages": [{"role": "user", "content": task}]})
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_agent)
        
        yield {
            "status": "extracting",
            "progress": 75,
            "message": "Extracting JSON from LLM response..."
        }
        
        # Step 5: Extract and validate the JSON from the response
        final_msg = result["messages"][-1].content if "messages" in result else str(result)
        
        # Try to parse JSON from the response
        extracted_data = None
        
        # Try direct JSON parse
        try:
            extracted_data = json.loads(final_msg)
        except json.JSONDecodeError:
            # Try to find JSON in the response (between { and })
            import re
            json_match = re.search(r'\{.*\}', final_msg, re.DOTALL)
            if json_match:
                try:
                    extracted_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
        
        if not extracted_data:
            yield {
                "status": "error",
                "error": "Failed to extract valid JSON from LLM response",
                "raw_response": final_msg[:500]  # Send first 500 chars for debugging
            }
            return
        
        # Step 6: Apply manual overrides if provided (overrides LLM values)
        if vertical:
            extracted_data["vertical"] = vertical
        if subvertical:
            extracted_data["subvertical"] = subvertical
        
        # Step 7: Save the extracted data
        final_path = write_json(output_path, extracted_data)
        
        yield {
            "status": "success",
            "progress": 100,
            "message": "Extraction complete",
            "data": extracted_data,
            "output_path": final_path,
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
