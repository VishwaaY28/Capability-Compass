import os
import json
from typing import List, Dict
from langchain_google_genai import ChatGoogleGenerativeAI
from deepagents import create_deep_agent
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from datetime import datetime

from pathlib import Path

GOOGLE_API_KEY = "AIzaSyDkY-VHiiZQ-q-SH9LdtbcMgWYHQkSntuc"
GEMINI_MODEL_ID = "gemini-2.5-flash"
INPUT_DOC_PATH = "policy.pdf"
OUTPUT_JSON_PATH = "response.json"


def load_document(path: str, chunk_size: int = 1800, chunk_overlap: int = 200) -> List[Dict]:
    """
    Load .pdf/.docx/.txt and return chunk dicts: [{"text": "...", "metadata": {...}}]
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
    Create a *new* JSON file on every call and write `data` into it.
    A timestamp (and, if needed, a numeric suffix) is appended so that
    no existing file is overwritten.

    Examples:
      input:  ".../capability_model.json"
      output: ".../capability_model_2026-02-11_11-31-40.json"
              (or "..._2026-02-11_11-31-40_2.json" if collision occurs)
    """
    abs_target = Path(path).expanduser().resolve()

    # Ensure parent directory exists
    abs_target.parent.mkdir(parents=True, exist_ok=True)

    # Split the input into base name and extension
    base = abs_target.stem if abs_target.suffix else abs_target.name
    ext = abs_target.suffix if abs_target.suffix else ".json"

    # Build a timestamped filename (local time)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = abs_target.with_name(f"{base}_{ts}{ext}")

    # If something already created the same file this second, add a counter
    counter = 2
    while candidate.exists():
        candidate = abs_target.with_name(f"{base}_{ts}_{counter}{ext}")
        counter += 1

    # Write the JSON
    with candidate.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return str(candidate)

def insert_graph(query: str) -> str:
    """
    After validation from the user, upload the data to the graph db.
    Uses Cypher query language via Neo4jQueryService.
    """
    from neo4j_graph.services.query_execution_service import Neo4jQueryService
    try:
        svc = Neo4jQueryService()
        svc.execute_cypher(query)
        svc.close()
    except Exception as e:
        raise RuntimeError(f"Failed to insert graph: {e}")
    return query



# --------------------------
# System prompt (strict JSON with explicit edges)
# --------------------------
EXTRACTION_INSTRUCTIONS = """
You are an expert Enterprise Architecture Consultant. Your job is to read a source document and produce a
normalized, ID-stable capability model with explicit relationships.

OUTPUT CONTRACT (must be STRICT JSON; no markdown; no commentary):

  {
  "id": 1,
  "name": "Fund Mandate",
  "description": "",
  "vertical": "Capital Markets",
  "subvertical": "Asset Management",
  "processes": [
    {
      "id": 1,
      "name": "Research and Idea Generation",
      "level": "core",
      "description": "",
      "category": "Back Office",
      "subprocesses": [
        {
          "id": 1,
          "name": "Sector & Industry Research",
          "description": "",
          "category": "Back Office",
          "data_entities": [
            {
              "data_entity_id": 1,
              "data_entity_name": "Base Profile",
              "data_entity_description": "",
              "data_elements": [
                {
                  "data_element_id": 1,
                  "data_element_name": "country",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 2,
                  "data_element_name": "sector",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 3,
                  "data_element_name": "industry",
                  "data_element_description": ""
                }
              ]
            }
          ],
        },
        {
          "id": 2,
          "name": "Bottom-Up Fundamental Analysis",
          "description": "",
          "category": "Back Office",
          "data_entities": [
            {
              "data_entity_id": 2,
              "data_entity_name": "Financial Parameters",
              "data_entity_description": "",
              "data_elements": [
                {
                  "data_element_id": 4,
                  "data_element_name": "revenue",
                  "data_element_description": ""
                },
                {
                  "data_element_id": 5,
                  "data_element_name": "ebitda",
                  "data_element_description": ""
                },
              ]
            }
          ],
        },      
    }
  ]
}


REQUIREMENTS:
- Preserve relationships using the 'parent_*_id' fields and the 'edges' array so no hierarchy is implicit.
- Prefer nouns for Capabilities and Processes; Subprocesses are action-centric but concise.
- Data Entities are business nouns; Data Elements are atomic attributes on entities with datatypes.
- Return only the JSON object (no extra text).

FINALIZATION (MANDATORY):
- After creating the JSON object, you MUST call tool=write_json with the full JSON and the provided output path.

"""


# --------------------------
# Build the Deep Agent (Gemini only)
# --------------------------
def build_agent_gemini(model_id: str):
    """
    building gemini agent
    """
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
    if not GOOGLE_API_KEY or GOOGLE_API_KEY == "REPLACE_WITH_YOUR_GEMINI_API_KEY":
        raise RuntimeError("Please edit GOOGLE_API_KEY at the top of this file with your real Gemini API key.")

    llm = ChatGoogleGenerativeAI(
        model=model_id,
        temperature=0.1,
        max_retries=2,
    )

    agent = create_deep_agent(
        model=llm,
        tools=[load_document, write_json],
        system_prompt=EXTRACTION_INSTRUCTIONS,
    )
    return agent


# --------------------------
# Orchestration
# --------------------------
def main():
    agent = build_agent_gemini(GEMINI_MODEL_ID)

    user_task = (
        "1) Call tool=load_document with path=`{doc}` to ingest content.\n"
        "2) Analyze all chunks and construct the single JSON capability model per OUTPUT CONTRACT.\n"
        "3) Call tool=write_json with path=`{out}` and the JSON object."
    ).format(doc=INPUT_DOC_PATH, out=OUTPUT_JSON_PATH)

    result = agent.invoke({"messages": [{"role": "user", "content": user_task}]})
    final_msg = result["messages"][-1].content if "messages" in result else str(result)
    print("\nAgent finished. Final message:\n", result)

    abs_out = os.path.abspath(OUTPUT_JSON_PATH)
    if os.path.exists(abs_out):
        with open(abs_out, "r", encoding="utf-8") as f:
            data = json.load(f)
        print("\n--- Extracted Capability Model (summary) ---")
        print("Capabilities:", len(data.get("capabilities", [])),
              "| Processes:", len(data.get("processes", [])),
              "| Subprocesses:", len(data.get("subprocesses", [])),
              "| Entities:", len(data.get("data_entities", [])),
              "| Elements:", len(data.get("data_elements", [])))
        print("\nSaved:", abs_out)
    else:
        print(f"\nWARNING: output file not found at {abs_out}")


if __name__ == "__main__":
    main()