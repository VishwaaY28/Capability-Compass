import logging
import re
logging.basicConfig(level=logging.INFO)
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from tortoise.contrib.pydantic import pydantic_model_creator
import asyncio
import json
import tempfile
import os

from database.repositories import capability_repository, process_repository, vertical_repository, prompt_template_repository
from database.models import Capability as CapabilityModel, Process as ProcessModel, Vertical as VerticalModel, SubVertical as SubVerticalModel, SubProcess as SubProcessModel
from utils.llm import azure_openai_client
from utils.llm2 import gemini_client
from utils.llmthinking import azure_openai_thinking_client
from utils.llm_independent import azure_openai_independent_client
from utils.csv_export import get_csv_exporter
from utils.llm_logger import log_llm_call
from config.llm_settings import llm_settings_manager
from utils.deepagent_extractor import extract_capability_model, validate_extracted_model
import io
import csv

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/vmo/meta")
async def get_vmo_meta(request_id: Optional[str] = Query(None)):
    """Return VMO metadata for a given request_id. If no request_id provided, returns empty dict.

    Frontend should request metadata for the specific `request_id` returned with the LLM response
    to avoid reading a global last-meta value that can be overwritten by other requests.
    """
    try:
        # If request_id is not provided, return the last stored VMO meta to aid debugging/UI
        meta = azure_openai_thinking_client.get_vmo_meta(request_id)
        return JSONResponse(content=meta or {})
    except Exception as e:
        logger.error(f"Failed to get VMO meta for request_id={request_id}: {type(e).__name__}: {e}", exc_info=True)
        # Return empty dict instead of 500 error since metadata is optional
        return JSONResponse(content={}, status_code=200)

class LLMProviderRequest(BaseModel):
    provider: str  # "azure", "gemini", or "secure"

class LLMConfigRequest(BaseModel):
    provider: str
    vaultName: str
    temperature: float
    topP: float

class ResearchRequest(BaseModel):
    query: str

class CompassChatRequest(BaseModel):
    query: str
    vertical: str  # Selected vertical for context

@router.post("/capabilities/research")
async def research_capabilities(payload: ResearchRequest):
    """
    OPTIMIZED: Use database search to filter candidates, then use LLM for ranking.
    This approach:
    1. Filters capabilities by keywords (fast database operation)
    2. Builds hierarchy only for filtered items (reduces LLM context size)
    3. Uses LLM to identify most specific matching level
    
    Hierarchy matching logic:
    - If user query matches specific subprocesses -> return only those subprocesses
    - Else if user query matches specific processes -> return those with their subprocesses
    - Else return matching capabilities with their full structure
    """
    query = payload.query
    logger.info(f"[Research] User query: {query}")
    
    provider = await llm_settings_manager.get_setting("provider", "secure")
    logger.info(f"[Research] Using LLM provider: {provider}")

    # Select LLM client based on current provider
    if provider == "gemini":
        llm_client = gemini_client
    else:
        llm_client = azure_openai_client

    # Step 1: OPTIMIZED - Filter capabilities by keywords first (database-level search)
    query_lower = query.lower()
    query_words = [w.strip() for w in query_lower.split() if len(w.strip()) > 2]
    logger.info(f"[Research] Search keywords: {query_words}")
    
    filtered_capabilities = await capability_repository.search_capabilities_by_keywords(query_words)
    logger.info(f"[Research] Filtered to {len(filtered_capabilities)} capabilities (from keyword search)")
    
    # If no keyword matches, fall back to all capabilities but limit to prevent overload
    if not filtered_capabilities:
        logger.info(f"[Research] No keyword matches found, fetching limited set of capabilities")
        all_caps = await capability_repository.fetch_all_capabilities()
        filtered_capabilities = all_caps[:20]  # Limit to top 20 to prevent LLM overload
        logger.info(f"[Research] Using {len(filtered_capabilities)} capabilities as fallback")
    
    # Step 2: Build hierarchy only for FILTERED capabilities (not all!)
    hierarchy_context = []
    for cap in filtered_capabilities:
        try:
            processes = await cap.processes.all()
        except Exception:
            processes = []

        cap_data = {
            "capability_id": cap.id,
            "capability_name": cap.name,
            "capability_description": cap.description,
            "subvertical": cap.subvertical.name if getattr(cap, 'subvertical', None) else None,
            "processes": []
        }

        for proc in processes:
            try:
                subprocs = await proc.subprocesses.all()
            except Exception:
                subprocs = []

            proc_data = {
                "process_id": proc.id,
                "process_name": proc.name,
                "process_level": getattr(proc.level, 'value', proc.level),
                "process_description": proc.description,
                "process_category": proc.category,
                "subprocesses": []
            }
            
            for sp in subprocs:
                try:
                    data_entities = await sp.data_entities.all()
                except Exception:
                    data_entities = []
                
                # Fetch data elements for each data entity
                entities_with_elements = []
                for de in data_entities:
                    try:
                        data_elements = await de.data_elements.all()
                    except Exception:
                        data_elements = []
                    
                    entities_with_elements.append({
                        "data_entity_id": de.id,
                        "data_entity_name": de.name,
                        "data_entity_description": de.description,
                        "data_elements": [
                            {
                                "data_element_id": elem.id,
                                "data_element_name": elem.name,
                                "data_element_description": elem.description,
                            }
                            for elem in data_elements
                        ]
                    })
                
                subprocess_data = {
                    "subprocess_id": sp.id,
                    "subprocess_name": sp.name,
                    "subprocess_description": sp.description,
                    "subprocess_category": sp.category,
                    "subprocess_application": getattr(sp, "application", None),
                    "subprocess_api": getattr(sp, "api", None),
                    "data_entities": entities_with_elements
                }
                proc_data["subprocesses"].append(subprocess_data)
            cap_data["processes"].append(proc_data)
        
        hierarchy_context.append(cap_data)

    # Step 3: Use LLM to analyze query and identify matching items at all levels
    hierarchy_text = re.sub(r'\s+', ' ', str(hierarchy_context)[:5000])  # Reduced context size
    
    llm_prompt = f"""
    You are an expert Enterprise Architecture analyst. Analyze the user query and match it to the most SPECIFIC level in the business architecture hierarchy.
    
    Database Hierarchy:
    - Capability (highest level): Business capability or domain
    - Process (mid level): Business process under a capability  
    - SubProcess (lowest level): Detailed activities within a process
    
    User Query: "{query}"
    
    Database Structure (pre-filtered for relevance):
    {hierarchy_text}
    
    Instructions:
    1. Carefully analyze the user query against the database structure.
    2. If the query matches SUBPROCESS level (asking about specific activities, tasks, or detailed operations), return ONLY matching subprocesses with their exact IDs from the database.
    3. If the query matches PROCESS level (asking about business processes), return ONLY matching processes with their exact IDs from the database.
    4. If the query is general and matches CAPABILITY level, return ONLY matching capabilities with their exact IDs from the database.
    5. DO NOT return parent items if you've matched specific child items.
    6. Return exact IDs that exist in the database - these are critical for lookup.
    7. If no exact matches found, return empty matching_items array and the system will provide broader matches.
    
    Return ONLY a valid JSON object (no markdown, no extra text) with this structure:
    {{
        "matching_level": "subprocess" | "process" | "capability",
        "matching_items": [
            {{
                "id": <integer_id>,
                "type": "subprocess" | "process" | "capability",
                "name": "...",
                "description": "..."
            }}
        ],
        "confidence": <0-100>,
        "explanation": "Why these items match the query"
    }}
    
    Example response:
    {{"matching_level": "capability", "matching_items": [{{"id": 1, "type": "capability", "name": "Customer Management", "description": "Managing customer relationships"}}], "confidence": 85, "explanation": "Query matches customer-related capabilities"}}
    """

    logger.info(f"[Research] Sending LLM prompt for deep hierarchy matching")
    
    try:
        llm_result = await llm_client.generate_content(prompt=llm_prompt)
        logger.info(f"[Research] LLM raw result: {llm_result}")
        logger.info(f"[Research] LLM result type: {type(llm_result)}")
        
        # Extract matching items from LLM response
        matching_data = {}
        
        # Debug: Print the full structure
        logger.info(f"[Research] LLM result keys: {list(llm_result.keys()) if isinstance(llm_result, dict) else 'Not a dict'}")
        
        if isinstance(llm_result, dict):
            data = llm_result.get("data", {})
            logger.info(f"[Research] Data from LLM: {data}")
            logger.info(f"[Research] Data type: {type(data)}")
            
            if isinstance(data, dict):
                matching_data = data
            elif isinstance(data, str):
                # Try to parse if it's a JSON string
                try:
                    import json
                    # Try to extract JSON from the string if it contains markdown
                    data_str = data
                    if "```json" in data_str:
                        data_str = data_str.split("```json")[1].split("```")[0].strip()
                    elif "```" in data_str:
                        data_str = data_str.split("```")[1].split("```")[0].strip()
                    
                    matching_data = json.loads(data_str)
                    logger.info(f"[Research] Parsed JSON from data string: {matching_data}")
                except Exception as parse_err:
                    logger.warning(f"[Research] Could not parse data as JSON: {data}, error: {str(parse_err)}")
                    matching_data = {}
        
        matching_level = matching_data.get("matching_level", "capability")
        matching_items = matching_data.get("matching_items", [])
        confidence = matching_data.get("confidence", 0)
        
        logger.info(f"[Research] Matching level: {matching_level}, Items count: {len(matching_items)}, Confidence: {confidence}")
        logger.info(f"[Research] Matching items from LLM: {matching_items}")

        # Step 4: Build response based on matching level
        result = []

        if matching_level == "subprocess" and matching_items:
            # Return subprocess-level matches with their parent process and capability
            for item in matching_items:
                subprocess_id = item.get("id")
                try:
                    # Fetch subprocess with process, capability and subvertical prefetched
                    subprocess = await SubProcessModel.filter(id=subprocess_id, deleted_at=None).prefetch_related('process', 'process__capability', 'process__capability__subvertical').first()
                    if not subprocess:
                        logger.warning(f"[Research] Subprocess {subprocess_id} not found")
                        continue
                    
                    process = subprocess.process
                    if not process:
                        logger.warning(f"[Research] Subprocess {subprocess_id} has no process")
                        continue
                    
                    capability = process.capability
                    if not capability:
                        logger.warning(f"[Research] Process {process.id} has no capability")
                        continue
                    
                    # Fetch data entities and elements for the subprocess
                    try:
                        data_entities = await subprocess.data_entities.all()
                    except Exception:
                        data_entities = []
                    
                    # Build nested data_entities with data_elements inside them
                    entities_list = []
                    
                    for de in data_entities:
                        try:
                            data_elements = await de.data_elements.all()
                        except Exception:
                            data_elements = []
                        
                        entities_list.append({
                            "data_entity_id": de.id,
                            "data_entity_name": de.name,
                            "data_entity_description": de.description,
                            "data_elements": [
                                {
                                    "id": elem.id,
                                    "name": elem.name,
                                    "description": elem.description,
                                }
                                for elem in data_elements
                            ]
                        })
                    
                    result.append({
                        "id": subprocess.id,
                        "name": subprocess.name,
                        "description": subprocess.description,
                        "type": "subprocess",
                        "category": subprocess.category,
                        "data": getattr(subprocess, "data", None),
                        "application": getattr(subprocess, "application", None),
                        "api": getattr(subprocess, "api", None),
                        "data_entities": entities_list,
                        "parent_process": {
                            "id": process.id,
                            "name": process.name,
                            "level": getattr(process.level, 'value', process.level),
                        },
                        "parent_capability": {
                            "id": capability.id,
                            "name": capability.name,
                            "subvertical": capability.subvertical.name if (hasattr(capability, 'subvertical') and capability.subvertical and hasattr(capability.subvertical, 'name')) else None,
                        }
                    })
                except Exception as e:
                    logger.warning(f"[Research] Could not fetch subprocess {subprocess_id}: {str(e)}", exc_info=True)
                    continue

        elif matching_level == "process" and matching_items:
            # Return process-level matches with their subprocesses and capability
            for item in matching_items:
                process_id = item.get("id")
                try:
                    # Fetch process with capability and subvertical prefetched
                    process = await ProcessModel.filter(id=process_id, deleted_at=None).prefetch_related('capability', 'capability__subvertical', 'subprocesses').first()
                    if not process:
                        logger.warning(f"[Research] Process {process_id} not found")
                        continue
                    
                    capability = process.capability
                    if not capability:
                        logger.warning(f"[Research] Process {process_id} has no capability")
                        continue
                    
                    try:
                        subprocs = await process.subprocesses.all()
                    except Exception:
                        subprocs = []

                    subprocess_list = []
                    for sp in subprocs:
                        # Fetch data entities and elements for each subprocess
                        try:
                            data_entities = await sp.data_entities.all()
                        except Exception:
                            data_entities = []
                        
                        # Build nested data_entities with data_elements inside them
                        entities_list = []
                        
                        for de in data_entities:
                            try:
                                data_elements = await de.data_elements.all()
                            except Exception:
                                data_elements = []
                            
                            entities_list.append({
                                "data_entity_id": de.id,
                                "data_entity_name": de.name,
                                "data_entity_description": de.description,
                                "data_elements": [
                                    {
                                        "id": elem.id,
                                        "name": elem.name,
                                        "description": elem.description,
                                    }
                                    for elem in data_elements
                                ]
                            })
                        
                        subprocess_list.append({
                            "id": sp.id,
                            "name": sp.name,
                            "description": sp.description,
                            "category": sp.category,
                            "data": getattr(sp, "data", None),
                            "application": getattr(sp, "application", None),
                            "api": getattr(sp, "api", None),
                            "data_entities": entities_list,
                        })

                    result.append({
                        "id": process.id,
                        "name": process.name,
                        "description": process.description,
                        "type": "process",
                        "level": getattr(process.level, 'value', process.level),
                        "category": process.category,
                        "subprocesses": subprocess_list,
                        "parent_capability": {
                            "id": capability.id,
                            "name": capability.name,
                            "subvertical": capability.subvertical.name if (hasattr(capability, 'subvertical') and capability.subvertical and hasattr(capability.subvertical, 'name')) else None,
                        }
                    })
                except Exception as e:
                    logger.warning(f"[Research] Could not fetch process {process_id}: {str(e)}", exc_info=True)
                    continue

        else:
            # Default: Return capability-level matches with full structure
            logger.info(f"[Research] No specific matches found, trying to match capabilities by ID or name")
            
            matched_capabilities = []
            
            # Try to match by ID first if we have matching_items
            if matching_items and len(matching_items) > 0:
                matching_ids = [item.get("id") for item in matching_items]
                matched_capabilities = [c for c in filtered_capabilities if c.id in matching_ids]
                logger.info(f"[Research] Found {len(matched_capabilities)} matching capabilities by ID")
            
            # If no ID matches, try name matching
            if len(matched_capabilities) == 0 and query and len(filtered_capabilities) > 0:
                logger.info(f"[Research] No ID matches found, trying name-based matching")
                query_lower = query.lower()
                query_words = query_lower.split()
                
                # Match if any query word appears in capability name or description
                name_matched = []
                for c in filtered_capabilities:
                    cap_name_lower = c.name.lower()
                    cap_desc_lower = c.description.lower() if c.description else ""
                    
                    # Check if any query word matches
                    for word in query_words:
                        if len(word) > 3 and (word in cap_name_lower or word in cap_desc_lower):
                            name_matched.append(c)
                            break
                
                if name_matched:
                    matched_capabilities = name_matched
                    logger.info(f"[Research] Name-matched {len(matched_capabilities)} capabilities")
            
            # If still no matches, return empty result instead of all capabilities
            if len(matched_capabilities) == 0:
                logger.info(f"[Research] No matching capabilities found for query: {query}")
                # Return empty result - do not fallback to all capabilities
                matched_capabilities = []

            for cap in matched_capabilities:
                try:
                    processes = await cap.processes.all()
                except Exception:
                    processes = []

                proc_list = []
                for proc in processes:
                    try:
                        subprocs = await proc.subprocesses.all()
                    except Exception:
                        subprocs = []

                    subprocess_list = []
                    for sp in subprocs:
                        # Fetch data entities and elements for each subprocess
                        try:
                            data_entities = await sp.data_entities.all()
                        except Exception:
                            data_entities = []
                        
                        # Build nested data_entities with data_elements inside them
                        entities_list = []
                        
                        for de in data_entities:
                            try:
                                data_elements = await de.data_elements.all()
                            except Exception:
                                data_elements = []
                            
                            entities_list.append({
                                "data_entity_id": de.id,
                                "data_entity_name": de.name,
                                "data_entity_description": de.description,
                                "data_elements": [
                                    {
                                        "id": elem.id,
                                        "name": elem.name,
                                        "description": elem.description,
                                    }
                                    for elem in data_elements
                                ]
                            })
                        
                        subprocess_list.append({
                            "id": sp.id,
                            "name": sp.name,
                            "description": sp.description,
                            "category": sp.category,
                            "data": getattr(sp, "data", None),
                            "application": getattr(sp, "application", None),
                            "api": getattr(sp, "api", None),
                            "data_entities": entities_list,
                        })

                    proc_list.append({
                        "id": proc.id,
                        "name": proc.name,
                        "level": getattr(proc.level, 'value', proc.level),
                        "description": proc.description,
                        "category": proc.category,
                        "subprocesses": subprocess_list,
                    })

                result.append({
                    "id": cap.id,
                    "name": cap.name,
                    "description": cap.description,
                    "type": "capability",
                    "subvertical": cap.subvertical.name if (hasattr(cap, 'subvertical') and cap.subvertical and hasattr(cap.subvertical, 'name')) else None,
                    "processes": proc_list,
                })

        logger.info(f"[Research] Response payload items: {len(result)}, Types: {[r.get('type', 'unknown') for r in result]}")
        
        # Log the LLM call to CSV
        try:
            # For research endpoint, we log the matching data as response
            response_str = json.dumps(matching_data) if matching_data else json.dumps(result[:500])  # Limit to first 500 items
            # Thinking is the LLM prompt we sent
            thinking_str = llm_prompt[:1000] if 'llm_prompt' in locals() else ""
            log_llm_call(
                vertical="research",
                user_query=query,
                llm_thinking_compass=thinking_str,
                llm_response_compass=response_str,
                llm_thinking_independent="",
                llm_response_independent="",
                system_prompt_compass="",
                system_prompt_independent="",
            )
        except Exception as log_error:
            logger.error(f"[Research] Failed to log LLM call: {log_error}")
        
        return JSONResponse(result)

    except Exception as e:
        logger.error(f"[Research] Error during research: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Research failed: {str(e)}")


Vertical_Pydantic = pydantic_model_creator(VerticalModel, name="Vertical")
SubVertical_Pydantic = pydantic_model_creator(SubVerticalModel, name="SubVertical")
Capability_Pydantic = pydantic_model_creator(CapabilityModel, name="Capability")
Process_Pydantic = pydantic_model_creator(ProcessModel, name="Process")


class DomainCreateRequest(BaseModel):
    name: str

class VerticalCreateRequest(BaseModel):
    name: str

class SubVerticalCreateRequest(BaseModel):
    name: str
    vertical_id: int

class CapabilityCreateRequest(BaseModel):
    name: str
    description: str
    process_id: Optional[int] = None
    subvertical_id: Optional[int] = None


class SubProcessCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None

class SubProcessCreateRequestWithParent(BaseModel):
    name: str
    description: str
    category: Optional[str] = None
    parent_process_id: int

class ProcessCreateRequest(BaseModel):
    name: str
    level: str
    description: str
    capability_id: Optional[int] = None
    category: Optional[str] = None
    subprocesses: Optional[List[SubProcessCreateRequest]] = None


@router.get("/health")
async def health_check():
    return JSONResponse(content={"status": "ok"}, status_code=200)


@router.get("/capabilities/diagnostics")
async def get_diagnostics():
    """Get diagnostic information about the database and capabilities"""
    try:
        # Fetch all capabilities
        capabilities = await capability_repository.fetch_all_capabilities()
        
        # Build capability info
        cap_info = []
        total_data_entities = 0
        total_data_elements = 0
        
        for cap in capabilities:
            try:
                processes = await cap.processes.all()
                proc_count = len(processes)
                
                # Count subprocesses and data entities
                subprocess_count = 0
                cap_data_entities = 0
                cap_data_elements = 0
                
                for proc in processes:
                    try:
                        subprocs = await proc.subprocesses.all()
                        subprocess_count += len(subprocs)
                        
                        for sp in subprocs:
                            try:
                                data_entities = await sp.data_entities.all()
                                cap_data_entities += len(data_entities)
                                total_data_entities += len(data_entities)
                                
                                for de in data_entities:
                                    try:
                                        data_elements = await de.data_elements.all()
                                        cap_data_elements += len(data_elements)
                                        total_data_elements += len(data_elements)
                                    except:
                                        pass
                            except:
                                pass
                    except:
                        pass
                
                cap_info.append({
                    "id": cap.id,
                    "name": cap.name,
                    "subvertical": cap.subvertical.name if getattr(cap, 'subvertical', None) else None,
                    "processes_count": proc_count,
                    "subprocesses_count": subprocess_count,
                    "data_entities_count": cap_data_entities,
                    "data_elements_count": cap_data_elements,
                })
            except Exception as e:
                logger.error(f"[Diagnostics] Error processing capability {cap.id}: {str(e)}")
                continue
        
        return JSONResponse({
            "status": "ok",
            "total_capabilities": len(cap_info),
            "total_data_entities": total_data_entities,
            "total_data_elements": total_data_elements,
            "capabilities": cap_info,
            "message": f"Database contains {len(cap_info)} capabilities, {total_data_entities} data entities, and {total_data_elements} data elements"
        })
    except Exception as e:
        logger.error(f"[Diagnostics] Error: {str(e)}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# LLM Provider Management
@router.get("/settings/llm-provider")
async def get_llm_provider():
    """Get current LLM provider and configuration"""
    settings = await llm_settings_manager.get_all_settings()
    return JSONResponse(settings)


@router.post("/settings/llm-provider")
async def set_llm_provider(payload: LLMProviderRequest):
    """Set the LLM provider (azure, gemini, or secure)"""
    if payload.provider not in ["azure", "gemini", "secure"]:
        raise HTTPException(status_code=400, detail="Invalid provider. Must be 'azure', 'gemini', or 'secure'")
    settings = await llm_settings_manager.update_settings({"provider": payload.provider})
    logger.info(f"LLM provider changed to: {payload.provider}")
    return JSONResponse({"provider": payload.provider, "message": f"Switched to {payload.provider} LLM"})


@router.post("/settings/llm-config")
async def set_llm_config(payload: LLMConfigRequest):
    """Set the LLM configuration"""
    if payload.provider not in ["azure", "gemini", "secure"]:
        raise HTTPException(status_code=400, detail="Invalid provider. Must be 'azure', 'gemini', or 'secure'")
    
    if not (0 <= payload.temperature <= 1):
        raise HTTPException(status_code=400, detail="Temperature must be between 0 and 1")
    
    if not (0 <= payload.topP <= 1):
        raise HTTPException(status_code=400, detail="Top P must be between 0 and 1")
    
    new_settings = {
        "provider": payload.provider,
        "vaultName": payload.vaultName,
        "temperature": payload.temperature,
        "topP": payload.topP,
    }
    settings = await llm_settings_manager.update_settings(new_settings)
    logger.info(f"LLM configuration updated: {new_settings}")
    
    return JSONResponse({
        "status": "success",
        "message": "LLM configuration updated successfully",
        **settings
    })


@router.get("/settings/prompt-template/{process_level}")
async def get_prompt_template(process_level: str):
    """Get the prompt template for a given process level"""
    # Seed if not exists
    await prompt_template_repository.seed_default_prompts()
    
    prompt_obj = await prompt_template_repository.get_prompt_by_level(process_level)
    if not prompt_obj:
        raise HTTPException(status_code=404, detail=f"No prompt template found for level: {process_level}")
    
    return JSONResponse({"process_level": process_level, "prompt": prompt_obj.prompt})


# CRUD for Verticals
@router.post("/verticals", response_model=Vertical_Pydantic)
async def create_vertical(payload: VerticalCreateRequest):
    obj = await vertical_repository.create_vertical(payload.name)
    return await Vertical_Pydantic.from_tortoise_orm(obj)


@router.get("/verticals", response_model=List[Vertical_Pydantic])
async def list_verticals():
    # Seed default verticals if none exist
    await vertical_repository.seed_default_verticals()
    
    verticals = await vertical_repository.fetch_all_verticals()
    return await Vertical_Pydantic.from_queryset(VerticalModel.all())


@router.get("/verticals/{vertical_id}", response_model=Vertical_Pydantic)
async def get_vertical(vertical_id: int):
    obj = await vertical_repository.fetch_vertical_by_id(vertical_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Vertical not found")
    return await Vertical_Pydantic.from_tortoise_orm(obj)


@router.put("/verticals/{vertical_id}", response_model=Vertical_Pydantic)
async def update_vertical(vertical_id: int, payload: VerticalCreateRequest):
    obj = await vertical_repository.update_vertical(vertical_id, payload.name)
    if not obj:
        raise HTTPException(status_code=404, detail="Vertical not found")
    return await Vertical_Pydantic.from_tortoise_orm(obj)


@router.delete("/verticals/{vertical_id}")
async def delete_vertical(vertical_id: int):
    ok = await vertical_repository.delete_vertical(vertical_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Vertical not found")
    return {"deleted": True}


# CRUD for SubVerticals
@router.post("/subverticals", response_model=SubVertical_Pydantic)
async def create_subvertical(payload: SubVerticalCreateRequest):
    obj = await vertical_repository.create_subvertical(payload.name, payload.vertical_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Vertical not found")
    return await SubVertical_Pydantic.from_tortoise_orm(obj)


@router.get("/subverticals", response_model=List[SubVertical_Pydantic])
async def list_subverticals(vertical_id: Optional[int] = Query(None, alias="vertical_id")):
    if vertical_id:
        subverticals = await vertical_repository.fetch_subverticals_by_vertical(vertical_id)
    else:
        subverticals = await vertical_repository.fetch_all_subverticals()
    return [await SubVertical_Pydantic.from_tortoise_orm(sv) for sv in subverticals]


@router.get("/subverticals/{subvertical_id}")
async def get_subvertical(subvertical_id: int):
    """
    Get a specific sub-vertical with complete hierarchical data including:
    - Capabilities
    - Processes (with levels)
    - SubProcesses
    - Data Entities
    - Data Elements
    - Applications and APIs
    """
    obj = await vertical_repository.fetch_subvertical_by_id(subvertical_id)
    if not obj:
        raise HTTPException(status_code=404, detail="SubVertical not found")
    
    # Fetch vertical name for context
    vertical_name = None
    try:
        vertical = await obj.vertical
        if vertical:
            vertical_name = vertical.name
    except Exception:
        vertical_name = None
    
    # Fetch all capabilities for this sub-vertical
    try:
        capabilities = await obj.capabilities.all()
    except Exception:
        capabilities = []
    
    # Build complete capability hierarchy
    capabilities_list = []
    for capability in capabilities:
        try:
            processes = await capability.processes.all()
        except Exception:
            processes = []
        
        processes_list = []
        for process in processes:
            try:
                subprocesses = await process.subprocesses.all()
            except Exception:
                subprocesses = []
            
            subprocesses_list = []
            for subprocess in subprocesses:
                try:
                    data_entities = await subprocess.data_entities.all()
                except Exception:
                    data_entities = []
                
                # Fetch data elements for each data entity
                entities_with_elements = []
                for data_entity in data_entities:
                    try:
                        data_elements = await data_entity.data_elements.all()
                    except Exception:
                        data_elements = []
                    
                    entities_with_elements.append({
                        "data_entity_id": data_entity.id,
                        "data_entity_name": data_entity.name,
                        "data_entity_description": data_entity.description,
                        "data_elements": [
                            {
                                "data_element_id": elem.id,
                                "data_element_name": elem.name,
                                "data_element_description": elem.description,
                            }
                            for elem in data_elements
                        ]
                    })
                
                subprocesses_list.append({
                    "id": subprocess.id,
                    "name": subprocess.name,
                    "description": subprocess.description,
                    "category": subprocess.category,
                    "application": getattr(subprocess, "application", None),
                    "api": getattr(subprocess, "api", None),
                    "data_entities": entities_with_elements,
                })
            
            process_level = getattr(process.level, 'value', process.level)
            processes_list.append({
                "id": process.id,
                "name": process.name,
                "level": process_level,
                "description": process.description,
                "category": process.category,
                "subprocesses": subprocesses_list,
            })
        
        capabilities_list.append({
            "id": capability.id,
            "name": capability.name,
            "description": capability.description,
            "org_units": getattr(capability, "org_units", None),
            "processes": processes_list,
        })
    
    result = {
        "id": obj.id,
        "name": obj.name,
        "vertical": vertical_name,
        "capabilities": capabilities_list,
    }
    
    return JSONResponse(result)


@router.put("/subverticals/{subvertical_id}", response_model=SubVertical_Pydantic)
async def update_subvertical(subvertical_id: int, payload: SubVerticalCreateRequest):
    obj = await vertical_repository.update_subvertical(subvertical_id, name=payload.name, vertical_id=payload.vertical_id)
    if not obj:
        raise HTTPException(status_code=404, detail="SubVertical not found")
    return await SubVertical_Pydantic.from_tortoise_orm(obj)


@router.delete("/subverticals/{subvertical_id}")
async def delete_subvertical(subvertical_id: int):
    ok = await vertical_repository.delete_subvertical(subvertical_id)
    if not ok:
        raise HTTPException(status_code=404, detail="SubVertical not found")
    return {"deleted": True}


# CRUD for Legacy Domains (for backwards compatibility)
@router.post("/domains", response_model=Vertical_Pydantic)
async def create_domain(payload: DomainCreateRequest):
    obj = await vertical_repository.create_vertical(payload.name)
    return await Vertical_Pydantic.from_tortoise_orm(obj)


@router.get("/domains", response_model=List[Vertical_Pydantic])
async def list_domains():
    # Seed default verticals if none exist
    await vertical_repository.seed_default_verticals()
    
    verticals = await vertical_repository.fetch_all_verticals()
    return await Vertical_Pydantic.from_queryset(VerticalModel.all())


@router.get("/domains/{domain_id}", response_model=Vertical_Pydantic)
async def get_domain(domain_id: int):
    obj = await vertical_repository.fetch_vertical_by_id(domain_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Domain not found")
    return await Vertical_Pydantic.from_tortoise_orm(obj)


@router.put("/domains/{domain_id}", response_model=Vertical_Pydantic)
async def update_domain(domain_id: int, payload: DomainCreateRequest):
    obj = await vertical_repository.update_vertical(domain_id, payload.name)
    if not obj:
        raise HTTPException(status_code=404, detail="Domain not found")
    return await Vertical_Pydantic.from_tortoise_orm(obj)


@router.delete("/domains/{domain_id}")
async def delete_domain(domain_id: int):
    ok = await vertical_repository.delete_vertical(domain_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {"deleted": True}


@router.post("/capabilities", response_model=Capability_Pydantic)
async def create_capability(payload: CapabilityCreateRequest):
    obj = await capability_repository.create_capability(payload.name, payload.description, payload.subvertical_id)
    return await Capability_Pydantic.from_tortoise_orm(obj)


@router.get("/export/capability/{capability_id}/csv")
async def export_capability_csv(capability_id: int):
    """Export all processes and subprocesses for a capability as CSV."""
    cap = await capability_repository.fetch_by_id(capability_id)
    if not cap:
        raise HTTPException(status_code=404, detail="Capability not found")

    # Fetch processes for this capability
    processes = await ProcessModel.filter(deleted_at=None, capability_id=capability_id).all()

    output = io.StringIO()
    fieldnames = [
        "Vertical",
        "capability_name",
        "process_type",
        "process_name",
        "process_description",
        "process_category",
        "subprocess_name",
        "subprocess_description",
        "data_entity_name",
        "data_entity_description",
        "data_element_name",
        "data_element_description",
        "application",
        "api",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    subvertical_name = cap.subvertical.name if getattr(cap, 'subvertical', None) else ""

    for p in processes:
        try:
            subs = await p.subprocesses.all()
        except Exception:
            subs = []

        if not subs:
            writer.writerow({
                "Vertical": subvertical_name,
                "capability_name": cap.name,
                "process_type": getattr(p.level, 'value', p.level),
                "process_name": p.name,
                "process_description": p.description or "",
                "process_category": p.category or "",
                "subprocess_name": "",
                "subprocess_description": "",
                "data_entity_name": "",
                "data_entity_description": "",
                "data_element_name": "",
                "data_element_description": "",
                "application": "",
                "api": "",
            })
        else:
            for s in subs:
                try:
                    data_entities = await s.data_entities.all()
                except Exception:
                    data_entities = []
                
                if not data_entities:
                    writer.writerow({
                        "Vertical": subvertical_name,
                        "capability_name": cap.name,
                        "process_type": getattr(p.level, 'value', p.level),
                        "process_name": p.name,
                        "process_description": p.description or "",
                        "process_category": p.category or "",
                        "subprocess_name": s.name,
                        "subprocess_description": s.description or "",
                        "data_entity_name": "",
                        "data_entity_description": "",
                        "data_element_name": "",
                        "data_element_description": "",
                        "application": getattr(s, "application", None) or "",
                        "api": getattr(s, "api", None) or "",
                    })
                else:
                    for de in data_entities:
                        try:
                            data_elements = await de.data_elements.all()
                        except Exception:
                            data_elements = []
                        
                        if not data_elements:
                            writer.writerow({
                                "Vertical": subvertical_name,
                                "capability_name": cap.name,
                                "process_type": getattr(p.level, 'value', p.level),
                                "process_name": p.name,
                                "process_description": p.description or "",
                                "process_category": p.category or "",
                                "subprocess_name": s.name,
                                "subprocess_description": s.description or "",
                                "data_entity_name": de.name,
                                "data_entity_description": de.description or "",
                                "data_element_name": "",
                                "data_element_description": "",
                                "application": getattr(s, "application", None) or "",
                                "api": getattr(s, "api", None) or "",
                            })
                        else:
                            for del_elem in data_elements:
                                writer.writerow({
                                    "Vertical": subvertical_name,
                                    "capability_name": cap.name,
                                    "process_type": getattr(p.level, 'value', p.level),
                                    "process_name": p.name,
                                    "process_description": p.description or "",
                                    "process_category": p.category or "",
                                    "subprocess_name": s.name,
                                    "subprocess_description": s.description or "",
                                    "data_entity_name": de.name,
                                    "data_entity_description": de.description or "",
                                    "data_element_name": del_elem.name,
                                    "data_element_description": del_elem.description or "",
                                    "application": getattr(s, "application", None) or "",
                                    "api": getattr(s, "api", None) or "",
                                })

    csv_bytes = output.getvalue().encode("utf-8")
    output.close()

    filename = f"capability_{capability_id}_export.csv"
    return StreamingResponse(io.BytesIO(csv_bytes), media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename=\"{filename}\""
    })


@router.get("/capabilities")
async def list_capabilities():
    caps = await capability_repository.fetch_all_capabilities()
    result = []
    for c in caps:

        try:
            procs = await c.processes.all()
        except Exception:
            procs = []

        proc_list = []
        for p in procs:

            level = getattr(p.level, 'value', p.level)
            
            # Fetch subprocesses for this process
            try:
                subprocs = await p.subprocesses.all()
            except Exception:
                subprocs = []
            
            subprocess_list = []
            for sp in subprocs:
                try:
                    data_entities = await sp.data_entities.all()
                except Exception:
                    data_entities = []
                
                # Fetch data elements for each data entity
                entities_with_elements = []
                for de in data_entities:
                    try:
                        data_elements = await de.data_elements.all()
                    except Exception:
                        data_elements = []
                    
                    entities_with_elements.append({
                        "data_entity_id": de.id,
                        "data_entity_name": de.name,
                        "data_entity_description": de.description,
                        "data_elements": [
                            {
                                "data_element_id": elem.id,
                                "data_element_name": elem.name,
                                "data_element_description": elem.description,
                            }
                            for elem in data_elements
                        ]
                    })
                
                subprocess_list.append({
                    "id": sp.id,
                    "name": sp.name,
                    "description": sp.description,
                    "category": sp.category,
                    "data_entities": entities_with_elements,
                    "application": getattr(sp, "application", None),
                    "api": getattr(sp, "api", None),
                })
            
            proc_list.append({
                "id": p.id,
                "name": p.name,
                "level": level,
                "description": p.description,
                "category": p.category,
                "subprocesses": subprocess_list,
            })

        # Fetch vertical through subvertical relationship
        subvertical_name = None
        vertical_name = None
        if getattr(c, 'subvertical', None):
            subvertical_name = c.subvertical.name
            try:
                # Fetch the related vertical
                vertical = await c.subvertical.vertical
                if vertical:
                    vertical_name = vertical.name
            except Exception:
                vertical_name = None

        result.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "vertical": vertical_name,
            "subvertical": subvertical_name,
            "org_units": getattr(c, "org_units", None),
            "processes": proc_list,
        })

    return JSONResponse(result)


@router.get("/capabilities/{capability_id}")
async def get_capability(capability_id: int):
    """
    Get a specific capability with full hierarchical data including processes,
    subprocesses, data entities, and data elements.
    """
    obj = await capability_repository.fetch_by_id(capability_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Capability not found")
    
    # Fetch processes for this capability
    try:
        procs = await obj.processes.all()
    except Exception:
        procs = []
    
    proc_list = []
    for p in procs:
        level = getattr(p.level, 'value', p.level)
        
        # Fetch subprocesses for this process
        try:
            subprocs = await p.subprocesses.all()
        except Exception:
            subprocs = []
        
        subprocess_list = []
        for sp in subprocs:
            try:
                data_entities = await sp.data_entities.all()
            except Exception:
                data_entities = []
            
            # Fetch data elements for each data entity
            entities_with_elements = []
            for de in data_entities:
                try:
                    data_elements = await de.data_elements.all()
                except Exception:
                    data_elements = []
                
                entities_with_elements.append({
                    "data_entity_id": de.id,
                    "data_entity_name": de.name,
                    "data_entity_description": de.description,
                    "data_elements": [
                        {
                            "data_element_id": elem.id,
                            "data_element_name": elem.name,
                            "data_element_description": elem.description,
                        }
                        for elem in data_elements
                    ]
                })
            
            subprocess_list.append({
                "id": sp.id,
                "name": sp.name,
                "description": sp.description,
                "category": sp.category,
                "data_entities": entities_with_elements,
                "application": getattr(sp, "application", None),
                "api": getattr(sp, "api", None),
            })
        
        proc_list.append({
            "id": p.id,
            "name": p.name,
            "level": level,
            "description": p.description,
            "category": p.category,
            "subprocesses": subprocess_list,
        })
    
    # Fetch vertical through subvertical relationship
    subvertical_name = None
    vertical_name = None
    if getattr(obj, 'subvertical', None):
        subvertical_name = obj.subvertical.name
        try:
            # Fetch the related vertical
            vertical = await obj.subvertical.vertical
            if vertical:
                vertical_name = vertical.name
        except Exception:
            vertical_name = None
    
    result = {
        "id": obj.id,
        "name": obj.name,
        "description": obj.description,
        "vertical": vertical_name,
        "subvertical": subvertical_name,
        "processes": proc_list,
    }
    
    return JSONResponse(result)


@router.put("/capabilities/{capability_id}", response_model=Capability_Pydantic)
async def update_capability(capability_id: int, payload: CapabilityCreateRequest):
    obj = await capability_repository.update_capability(capability_id, name=payload.name, description=payload.description, subvertical_id=payload.subvertical_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Capability not found")
    return await Capability_Pydantic.from_tortoise_orm(obj)


@router.delete("/capabilities/{capability_id}")
async def delete_capability(capability_id: int):
    ok = await capability_repository.delete_capability(capability_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Capability not found")
    return {"deleted": True}


@router.post("/processes")
async def create_process(payload: ProcessCreateRequest):
    subprocesses_data = []
    if payload.subprocesses:
        subprocesses_data = [
            {"name": sp.name, "description": sp.description or "", "category": sp.category} 
            for sp in payload.subprocesses
        ]
    proc = await process_repository.create_process(
        payload.name,
        payload.level,
        payload.description,
        payload.capability_id,
        subprocesses=subprocesses_data,
        category=payload.category,
    )

    # Load subprocesses to return them immediately so frontend can display
    try:
        subs = await proc.subprocesses.all()
    except Exception:
        subs = []

    subprocess_list = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "category": getattr(s, "category", None),
            "data": getattr(s, "data", None),
            "application": getattr(s, "application", None),
            "api": getattr(s, "api", None),
        }
        for s in subs
    ]

    level = getattr(proc.level, "value", proc.level)

    result = {
        "id": proc.id,
        "name": proc.name,
        "level": level,
        "description": proc.description,
        "category": getattr(proc, "category", None),
        "subprocesses": subprocess_list,
    }

    return JSONResponse(result)


@router.get("/processes")
async def list_processes(capability_id: Optional[int] = Query(None, alias="capability_id")):
    """
    Get all processes with full hierarchical data including subprocesses, 
    data entities, and data elements.
    """
    # Fetch processes based on capability_id filter
    if capability_id is None:
        processes = await ProcessModel.filter(deleted_at=None).all()
    else:
        processes = await ProcessModel.filter(deleted_at=None, capability_id=capability_id).all()
    
    result = []
    
    for proc in processes:
        # Fetch capability info
        capability = None
        try:
            capability = await proc.capability
        except Exception:
            capability = None
        
        # Fetch all subprocesses
        try:
            subprocs = await proc.subprocesses.all()
        except Exception:
            subprocs = []
        
        # Build subprocess list with data entities and elements
        subprocess_list = []
        for sp in subprocs:
            try:
                data_entities = await sp.data_entities.all()
            except Exception:
                data_entities = []
            
            # Fetch data elements for each data entity
            entities_with_elements = []
            for de in data_entities:
                try:
                    data_elements = await de.data_elements.all()
                except Exception:
                    data_elements = []
                
                entities_with_elements.append({
                    "data_entity_id": de.id,
                    "data_entity_name": de.name,
                    "data_entity_description": de.description,
                    "data_elements": [
                        {
                            "data_element_id": elem.id,
                            "data_element_name": elem.name,
                            "data_element_description": elem.description,
                        }
                        for elem in data_elements
                    ]
                })
            
            subprocess_list.append({
                "id": sp.id,
                "name": sp.name,
                "description": sp.description,
                "category": sp.category,
                "data": getattr(sp, "data", None),
                "application": getattr(sp, "application", None),
                "api": getattr(sp, "api", None),
                "data_entities": entities_with_elements,
            })
        
        # Get process level
        level = getattr(proc.level, 'value', proc.level)
        
        result.append({
            "id": proc.id,
            "name": proc.name,
            "level": level,
            "description": proc.description,
            "category": proc.category,
            "capability_id": proc.capability_id,
            "capability_name": capability.name if capability else None,
            "subprocesses": subprocess_list,
        })
    
    return JSONResponse(result)


@router.get("/processes/{process_id}", response_model=Process_Pydantic)
async def get_process(process_id: int):
    obj = await process_repository.fetch_process_by_id(process_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Process not found")
    return await Process_Pydantic.from_tortoise_orm(obj)


@router.put("/processes/{process_id}", response_model=Process_Pydantic)
async def update_process(process_id: int, payload: ProcessCreateRequest):
    obj = await process_repository.update_process(process_id, name=payload.name, level=payload.level, description=payload.description)
    if not obj:
        raise HTTPException(status_code=404, detail="Process not found")
    return await Process_Pydantic.from_tortoise_orm(obj)


@router.delete("/processes/{process_id}")
async def delete_process(process_id: int):
    ok = await process_repository.delete_process(process_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Process not found")
    return {"deleted": True}


@router.post("/subprocesses")
async def create_subprocess(payload: SubProcessCreateRequestWithParent):
    """Create a new subprocess for a given parent process"""
    from database.models import Process as ProcessModel, SubProcess as SubProcessModel
    
    # Get the parent process
    try:
        parent_process = await ProcessModel.get(id=payload.parent_process_id, deleted_at=None)
    except Exception:
        raise HTTPException(status_code=404, detail="Parent process not found")
    
    # Create the subprocess
    subproc = await SubProcessModel.create(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        process=parent_process
    )
    
    result = {
        "id": subproc.id,
        "name": subproc.name,
        "level": "subprocess",
        "description": subproc.description,
        "category": getattr(subproc, "category", None),
        "data": getattr(subproc, "data", None),
        "application": getattr(subproc, "application", None),
        "api": getattr(subproc, "api", None),
        "parent_process_id": payload.parent_process_id,
    }
    
    return JSONResponse(result)


@router.get("/subprocesses")
async def list_subprocesses(process_id: Optional[int] = Query(None, alias="process_id")):
    """Get all subprocesses for a given process"""
    if process_id is None:
        raise HTTPException(status_code=400, detail="process_id parameter is required")
    
    try:
        process = await ProcessModel.get(id=process_id, deleted_at=None)
    except Exception:
        raise HTTPException(status_code=404, detail="Process not found")
    
    try:
        subprocs = await process.subprocesses.all()
    except Exception:
        subprocs = []
    
    result = [
        {
            "id": sp.id,
            "name": sp.name,
            "description": sp.description,
            "category": getattr(sp, "category", None),
            "data": getattr(sp, "data", None),
            "application": getattr(sp, "application", None),
            "api": getattr(sp, "api", None),
        }
        for sp in subprocs
    ]
    
    return JSONResponse(result)


class GenerateProcessRequest(BaseModel):
    capability_name: str
    capability_id: int
    capability_description: Optional[str] = None
    domain: str
    process_type: str
    prompt: str


@router.post("/processes/generate")
async def generate_processes(payload: GenerateProcessRequest):
    """Generate processes using LLM and save them to the database"""
    try:
        logger.info(f"/processes/generate called with payload: capability_name={payload.capability_name}, capability_id={payload.capability_id}, domain={payload.domain}, process_type={payload.process_type}")
        
        provider = await llm_settings_manager.get_setting("provider", "secure")
        logger.info(f"Using LLM provider: {provider}")
        
        
        if provider == "gemini":
            llm_client = gemini_client
        else:
            llm_client = azure_openai_client
        
        
        logger.info(f"Calling {provider} LLM client.generate_processes...")
        print(f"[DEBUG] /processes/generate payload: capability_name={payload.capability_name}, capability_id={payload.capability_id}, domain={payload.domain}, process_type={payload.process_type}, capability_description={payload.capability_description}")
        try:
            llm_result = await llm_client.generate_processes(
                payload.capability_name, 
                payload.capability_description or "", 
                payload.domain, 
                payload.process_type,
                payload.prompt
            )
            logger.info(f"LLM returned: {llm_result}")
            print(f"[DEBUG] LLM returned: {llm_result}")
        except Exception as e:

            logger.exception("LLM call failed")
            print(f"[DEBUG] LLM call failed: {e}")
            raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")
        
        if llm_result.get("status") != "success":
            raise HTTPException(status_code=500, detail="Failed to generate processes from LLM")
        
        generated_data = llm_result.get("data", {})
        
        logger.info(f"[DEBUG] generated_data type: {type(generated_data)}")
        logger.info(f"[DEBUG] generated_data keys: {list(generated_data.keys()) if isinstance(generated_data, dict) else 'not a dict'}")
        logger.info(f"[DEBUG] generated_data content: {str(generated_data)[:500]}")

        # Verify capability exists (just for validation; we don't persist yet)
        capability = await capability_repository.fetch_by_id(payload.capability_id)
        if not capability:
            raise HTTPException(status_code=404, detail="Capability not found")
        
        # Save LLM response to CSV file
        try:
            csv_exporter = get_csv_exporter()
            csv_filepath = csv_exporter.export_process_generation(
                capability_name=payload.capability_name,
                domain=payload.domain,
                process_type=payload.process_type,
                generated_data=generated_data,
                provider=provider,
            )
            logger.info(f"LLM response saved to CSV: {csv_filepath}")
        except Exception as e:
            logger.error(f"Failed to save LLM response to CSV: {str(e)}")
            # Don't fail the entire request if CSV export fails, just log it
        
        # Save processes to database
        saved_processes = []
        try:
            processes_data = generated_data.get("processes", [])
            if not isinstance(processes_data, list):
                logger.warning(f"Expected 'processes' to be a list, got {type(processes_data)}. Wrapping in list.")
                processes_data = [processes_data]
            
            for process_item in processes_data:
                if not isinstance(process_item, dict):
                    logger.warning(f"Skipping non-dict process item: {process_item}")
                    continue
                
                # Extract process data
                process_name = process_item.get("business_process") or process_item.get("name", "Unnamed Process")
                process_description = process_item.get("activities_and_description") or process_item.get("description", "")
                process_category = process_item.get("category", "")
                
                # Create process in database
                proc = await process_repository.create_process(
                    name=process_name,
                    level=payload.process_type or "core",
                    description=process_description,
                    capability_id=payload.capability_id,
                    category=process_category,
                    subprocesses=[]  # Subprocesses can be added separately if needed
                )
                
                saved_processes.append({
                    "id": proc.id,
                    "name": proc.name,
                    "description": proc.description,
                    "category": proc.category,
                    "level": proc.level
                })
                logger.info(f"Created process: {proc.name} (id={proc.id})")
            
            logger.info(f"Saved {len(saved_processes)} processes to database")
        except Exception as e:
            logger.error(f"Error saving processes to database: {str(e)}", exc_info=True)

        return {
            "status": "success",
            "message": f"Generated processes for {payload.capability_name}",
            "processes": saved_processes,
            "data": generated_data,
            "process_type": payload.process_type or 'core',
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating processes: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate processes: {str(e)}")


@router.post("/chat/compass")
async def compass_chat(payload: CompassChatRequest):
    """
    Compass Chat endpoint - Uses Azure OpenAI LLM to analyze user queries against vertical data.
    Returns both the agent's thinking process and final analysis result.
    """
    try:
        query = payload.query
        vertical_name = payload.vertical
        logger.info(f"[CompassChat] Query: {query}, Vertical: {vertical_name}")

        # Fetch vertical by name from all verticals
        all_verticals = await vertical_repository.fetch_all_verticals()
        vertical = next((v for v in all_verticals if v.name == vertical_name), None)
        if not vertical:
            raise HTTPException(status_code=404, detail=f"Vertical '{vertical_name}' not found")
        # Build hierarchical vertical context (fallback) and also pre-run the Cypher
        vertical_data = await _build_vertical_context(vertical)

        # Build a query plan and cypher locally then execute the cypher so we can pass the
        # exact query result to the thinking client (ensures the LLM receives query result)
        serialized_context_debug = ""
        try:
            plan_for_debug = azure_openai_thinking_client._create_query_plan(query, None)
            cypher = azure_openai_thinking_client._generate_enterprise_query(plan_for_debug)
            logger.debug(f"[CompassChat] Pre-running Cypher: {cypher[:400]}")
            try:
                db_query_result = azure_openai_thinking_client._default_db_fetch(cypher)
                logger.debug(f"[CompassChat] Pre-fetched DB query result type={type(db_query_result)}")
            except Exception as e:
                logger.warning(f"[CompassChat] Pre-fetch DB query failed: {e}")
                db_query_result = vertical_data  # fallback to hierarchical context

            # Serialize the context (for debug and response) from the actual query result
            try:
                serialized_context_debug = azure_openai_thinking_client._serialize_db_records(db_query_result, plan_for_debug)
                logger.debug(f"[CompassChat] Serialized context length={len(serialized_context_debug)} snippet={serialized_context_debug[:500]}")
            except Exception:
                serialized_context_debug = ""

            # Pass the actual db_query_result into the thinking client as vertical_data so it is used directly
            thinking, result, request_id = azure_openai_thinking_client.think_and_analyze(
                query=query,
                vertical=vertical_name,
                vertical_data=db_query_result,
            )
        except Exception as e:
            logger.warning(f"[CompassChat] Pre-query and think_and_analyze attempt failed: {e}")
            # Fall back to calling the thinking client with the hierarchical context
            thinking, result, request_id = azure_openai_thinking_client.think_and_analyze(
                query=query,
                vertical=vertical_name,
                vertical_data=vertical_data,
            )

        logger.info(f"[CompassChat] Analysis complete")

        # Get system and user prompts for logging and frontend
        system_prompt = azure_openai_thinking_client.get_last_system_prompt() or ""
        user_prompt = azure_openai_thinking_client.get_last_user_prompt() or ""

        # Auto-log this compass chat (includes system prompt and user prompt)
        try:
            logger.debug(f"[CompassChat] System prompt length={len(system_prompt)} snippet={system_prompt[:300]}")
            logger.debug(f"[CompassChat] User prompt length={len(user_prompt)} snippet={user_prompt[:300]}")
            log_llm_call(
                vertical=vertical_name,
                user_query=query,
                user_prompt=user_prompt,
                llm_thinking_compass=thinking or "",
                llm_response_compass=result or "",
                llm_thinking_independent="",
                llm_response_independent="",
                system_prompt_compass=system_prompt or "",
                system_prompt_independent="",
            )
        except Exception as e:
            logger.warning(f"[CompassChat] Failed to auto-log LLM call: {e}")

        return {
            "status": "success",
            "query": query,
            "vertical": vertical_name,
            "thinking": thinking,
            "result": result,
            "request_id": request_id,
            "system_prompt_compass": system_prompt,
            # Include the VMO metadata (persona/tone/intent/anchors) so frontend
            # can display it immediately without relying on a separate poll.
            "vmo_meta": azure_openai_thinking_client.get_vmo_meta(request_id),
            # Include a short serialized context snippet for debugging whether the LLM received context data
            "context_snippet": (serialized_context_debug[:2000] if serialized_context_debug else ""),
            "context_length": (len(serialized_context_debug) if serialized_context_debug else 0),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CompassChat] Error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to process compass chat: {str(e)}"
        )


@router.get("/chat/compass/stream")
async def compass_chat_stream(
    query: str = Query(...),
    vertical: str = Query(...),
):
    """
    Streaming version of Compass Chat - streams thinking and result progressively.
    """
    try:
        logger.info(f"[CompassChat Stream] Query: {query}, Vertical: {vertical}")

        # Fetch vertical by name
        all_verticals = await vertical_repository.fetch_all_verticals()
        vertical_obj = next((v for v in all_verticals if v.name == vertical), None)
        if not vertical_obj:
            raise HTTPException(status_code=404, detail=f"Vertical '{vertical}' not found")

        # Build vertical context
        vertical_data = await _build_vertical_context(vertical_obj)

        async def generate():
            thinking_parts = []
            result_parts = []
            current_section = None
            
            try:
                # Stream the thinking and result
                # Pre-run the cypher query and pass the exact query result into the stream so
                # the thinking client uses the query result as the context for the LLM.
                try:
                    plan_for_debug = azure_openai_thinking_client._create_query_plan(query, None)
                    cypher = azure_openai_thinking_client._generate_enterprise_query(plan_for_debug)
                    logger.debug(f"[CompassChat Stream] Pre-running Cypher: {cypher[:400]}")
                    try:
                        db_query_result = azure_openai_thinking_client._default_db_fetch(cypher)
                        logger.debug(f"[CompassChat Stream] Pre-fetched DB result type={type(db_query_result)}")
                    except Exception as e:
                        logger.warning(f"[CompassChat Stream] Pre-fetch DB query failed: {e}")
                        db_query_result = vertical_data

                    stream_iterable = azure_openai_thinking_client.stream_think_and_analyze(
                        query=query,
                        vertical=vertical,
                        vertical_data=db_query_result,
                    )
                except Exception as e:
                    logger.warning(f"[CompassChat Stream] Pre-query failed, falling back to hierarchical vertical_data: {e}")
                    stream_iterable = azure_openai_thinking_client.stream_think_and_analyze(
                        query=query,
                        vertical=vertical,
                        vertical_data=vertical_data,
                    )

                for chunk_type, content in stream_iterable:
                    # Collect thinking and result parts for logging
                    if chunk_type == "thinking":
                        thinking_parts.append(content)
                    elif chunk_type == "result":
                        result_parts.append(content)
                    
                    current_section = chunk_type
                    
                    # Send JSON-formatted chunks
                    chunk = {
                        "type": chunk_type,
                        "content": content,
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"

                # Send completion signal with metadata for logging
                thinking_str = "".join(thinking_parts) if thinking_parts else ""
                result_str = "".join(result_parts) if result_parts else ""
                system_prompt = azure_openai_thinking_client.get_last_system_prompt() or ""
                # Debug: include a short serialized context snippet to help frontend
                try:
                    plan_for_debug = azure_openai_thinking_client._create_query_plan(query, None)
                    serialized_context_debug = azure_openai_thinking_client._serialize_db_records(vertical_data, plan_for_debug)
                    logger.debug(f"[CompassChat Stream] Serialized context length={len(serialized_context_debug)} snippet={serialized_context_debug[:500]}")
                except Exception:
                    serialized_context_debug = ""
                context_str = json.dumps(vertical_data)[:10000] if vertical_data else ""
                # Auto-log streamed chat completion to CSV
                try:
                    # Get user prompt from thinking client for logging
                    user_prompt_str = azure_openai_thinking_client.get_last_user_prompt() or ""
                    logger.debug(f"[CompassChat Stream] System prompt length={len(system_prompt)} snippet={system_prompt[:300]}")
                    logger.debug(f"[CompassChat Stream] User prompt length={len(user_prompt_str)} snippet={user_prompt_str[:300]}")
                    log_llm_call(
                        vertical=vertical,
                        user_query=query,
                        user_prompt=user_prompt_str,
                        llm_thinking_compass=thinking_str or "",
                        llm_response_compass=result_str or "",
                        llm_thinking_independent="",
                        llm_response_independent="",
                        system_prompt_compass=system_prompt or "",
                        system_prompt_independent="",
                        request_id=None,
                    )
                except Exception as e:
                    logger.warning(f"[CompassChat Stream] Failed to auto-log LLM call: {e}")

                yield f"data: {json.dumps({
                    'type': 'complete',
                    'system_prompt_compass': system_prompt,
                    'thinking_compass': thinking_str,
                    'response_compass': result_str,
                    'context_snippet': (serialized_context_debug[:2000] if serialized_context_debug else ''),
                })}\n\n"

            except Exception as e:
                logger.error(f"[CompassChat Stream] Error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CompassChat Stream] Error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to stream compass chat: {str(e)}"
        )


@router.post("/chat/compass/independent")
async def compass_chat_independent(payload: CompassChatRequest):
    """
    Independent Compass Chat endpoint - Uses Azure OpenAI LLM to analyze user queries with optional context.
    The LLM can leverage vertical data from the database but also uses its own knowledge and reasoning.
    Returns both the agent's thinking process and final analysis result.
    """
    try:
        query = payload.query
        vertical_name = payload.vertical
        logger.info(f"[CompassChat Independent] Query: {query}, Vertical: {vertical_name}")

        # Fetch vertical by name to get context
        all_verticals = await vertical_repository.fetch_all_verticals()
        vertical_obj = next((v for v in all_verticals if v.name == vertical_name), None)
        
        # Build vertical context if vertical exists
        vertical_data = None
        if vertical_obj:
            vertical_data = await _build_vertical_context(vertical_obj)

        # Use independent Azure OpenAI client to analyze query with optional vertical context
        thinking, result = azure_openai_independent_client.think_and_analyze(
            query=query,
            vertical=vertical_name,
            vertical_data=vertical_data,
        )

        # VALIDATION: Log response details for debugging
        thinking_len = len(thinking) if thinking else 0
        result_len = len(result) if result else 0
        logger.info(f"[CompassChat Independent] Analysis complete - Thinking length: {thinking_len}, Result length: {result_len}")
        
        # WARNING: If result is empty, log it for debugging
        if not result or result.strip() == "":
            logger.warning(f"[CompassChat Independent] EMPTY RESULT DETECTED! Thinking: {thinking[:200] if thinking else 'None'}")

        # Get system prompt for frontend logging
        system_prompt = azure_openai_independent_client.get_last_system_prompt() or ""

        response_obj = {
            "status": "success",
            "query": query,
            "vertical": vertical_name,
            "thinking": thinking or "",  # Ensure never None
            "result": result or "",  # Ensure never None
            "system_prompt_independent": system_prompt,
            # Include VMO metadata if available from thinking client
            "vmo_meta": azure_openai_thinking_client.get_last_vmo_meta() or {},
        }
        
        logger.debug(f"[CompassChat Independent] Response keys: {list(response_obj.keys())}, result_type: {type(response_obj['result'])}")
        return response_obj

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CompassChat Independent] Error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to process independent compass chat: {str(e)}"
        )


class DualChatLoggingRequest(BaseModel):
    query: str
    vertical: str
    system_prompt_compass: str
    user_prompt: Optional[str] = ""
    thinking_compass: str
    response_compass: str
    system_prompt_independent: str
    thinking_independent: str
    response_independent: str
    context_data: Optional[str] = ""


@router.post("/chat/compass/log-dual")
async def log_dual_chat_responses(payload: DualChatLoggingRequest):
    """
    Log both compass and independent chat responses to CSV.
    Called by frontend after both responses are received.
    This ensures both responses appear on the same row in the CSV.
    """
    try:
        logger.info(f"[DualChatLogging] Logging dual responses for query: {payload.query[:50]}...")
        
        # Log both responses together in a single row (update existing by request_id if available)
        try:
            logger.debug(f"[DualChatLogging] System prompt snippet: {str(payload.system_prompt_compass)[:300]}")
            logger.debug(f"[DualChatLogging] User prompt snippet: {str(payload.user_prompt)[:300]}")
            log_llm_call(
                vertical=payload.vertical,
                user_query=payload.query,
                user_prompt=payload.user_prompt or "",
                llm_thinking_compass=payload.thinking_compass or "",
                llm_response_compass=payload.response_compass or "",
                llm_thinking_independent=payload.thinking_independent or "",
                llm_response_independent=payload.response_independent or "",
                system_prompt_compass=payload.system_prompt_compass or "",
                system_prompt_independent=payload.system_prompt_independent or "",
            )
        except Exception as e:
            logger.warning(f"[DualChatLogging] Failed to log dual chat: {e}")
        
        logger.info(f"[DualChatLogging] Dual responses logged successfully")
        
        return {
            "status": "success",
            "message": "Dual responses logged successfully"
        }
    
    except Exception as e:
        logger.error(f"[DualChatLogging] Error logging dual responses: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to log dual responses: {str(e)}"
        )


async def _build_vertical_context(vertical) -> dict:
    """Build comprehensive hierarchical context data for a vertical: Capability -> Process -> SubProcess -> Data Entity -> Data Element"""
    try:
        # Get all subverticals for this vertical
        subverticals = await vertical.subverticals.all()

        capabilities_list = []

        for subvert in subverticals:
            # Get capabilities for each subvertical
            capabilities = await subvert.capabilities.all()

            for cap in capabilities:
                cap_data = {
                    "id": cap.id,
                    "name": cap.name,
                    "description": cap.description,
                    "processes": []
                }

                # Get processes for each capability
                processes = await cap.processes.all()

                for proc in processes:
                    proc_data = {
                        "id": proc.id,
                        "name": proc.name,
                        "description": proc.description,
                        "category": proc.category,
                        "level": proc.level.value if hasattr(proc.level, 'value') else str(proc.level),
                        "subprocesses": []
                    }

                    # Get subprocesses
                    subprocs = await proc.subprocesses.all()

                    for subproc in subprocs:
                        subproc_data = {
                            "id": subproc.id,
                            "name": subproc.name,
                            "description": subproc.description,
                            "category": subproc.category,
                            "application": subproc.application,
                            "api": subproc.api,
                            "data_entities": []
                        }

                        # Get data entities for each subprocess
                        try:
                            data_entities = await subproc.data_entities.all()

                            for data_entity in data_entities:
                                entity_data = {
                                    "data_entity_name": data_entity.name,
                                    "data_entity_description": data_entity.description,
                                    "data_elements": []
                                }

                                # Get data elements for each data entity
                                try:
                                    data_elements = await data_entity.data_elements.all()

                                    for data_element in data_elements:
                                        element_data = {
                                            "data_element_name": data_element.name,
                                            "data_element_description": data_element.description,
                                        }
                                        entity_data["data_elements"].append(element_data)
                                except Exception as e:
                                    logger.warning(f"Error fetching data elements for entity {data_entity.id}: {e}")
                                
                                subproc_data["data_entities"].append(entity_data)
                        except Exception as e:
                            logger.warning(f"Error fetching data entities for subprocess {subproc.id}: {e}")

                        proc_data["subprocesses"].append(subproc_data)

                    cap_data["processes"].append(proc_data)

                capabilities_list.append(cap_data)


        return {
            "vertical_name": vertical.name,
            "capabilities": capabilities_list,
        }

    except Exception as e:
        logger.error(f"Error building vertical context: {e}", exc_info=True)
        return {"vertical_name": vertical.name, "capabilities": []}


# ========== DOCUMENT INGESTION & EXTRACTION ==========

class CapabilityImportRequest(BaseModel):
    """Request to import extracted capability model into the database"""
    model_data: dict  # The extracted capability model JSON
    chunks_path: Optional[str] = None  # Path to the chunks JSON file for knowledge base insertion


@router.post("/upload/pdf")
async def upload_and_extract_pdf(
    file: UploadFile = File(...),
    vertical: Optional[str] = Query(None),
    subvertical: Optional[str] = Query(None),
    extraction_depth: str = Query("data_element")
):
    """
    Upload a PDF/document and extract capability model using DeepAgent.
    
    Streams extraction progress back to the frontend in real-time.
    Each event is a JSON object on its own line (JSONL format).
    
    Args:
        file: The uploaded document file
        vertical: Optional manual vertical name to override LLM detection (query parameter)
        subvertical: Optional manual subvertical name to override LLM detection (query parameter)
        extraction_depth: Extraction depth level - capability|process|subprocess|data_entity|data_element (query parameter)
    
    Frontend should handle:
    - "started": Extraction beginning
    - "loading": Document loading progress
    - "extracting": LLM extraction in progress
    - "success": Extraction complete with data
    - "error": Extraction failed
    
    Returns:
        StreamingResponse with JSONL-formatted progress events
    """
    
    # Validate file type
    allowed_extensions = {'.pdf', '.docx', '.doc', '.txt'}
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Normalize and clean parameters (strip whitespace, handle empty strings as None)
    vertical = vertical.strip() if vertical and isinstance(vertical, str) else None
    subvertical = subvertical.strip() if subvertical and isinstance(subvertical, str) else None
    extraction_depth = extraction_depth.strip() if extraction_depth else "data_element"
    
    # Validate extraction depth
    valid_depths = {"capability", "process", "subprocess", "data_entity", "data_element"}
    if extraction_depth not in valid_depths:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid extraction_depth: '{extraction_depth}'. Allowed: {', '.join(sorted(valid_depths))}"
        )
    
    # Log received parameters for debugging - show None vs actual values
    logger.info(f"[API] Upload request - file: {file.filename}, vertical: {repr(vertical)}, subvertical: {repr(subvertical)}, depth: {repr(extraction_depth)}")
    
    # Save uploaded file to temp location
    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, file.filename)
    
    try:
        # Save the uploaded file
        contents = await file.read()
        with open(temp_file_path, "wb") as f:
            f.write(contents)
        
        logger.info(f"[API] Uploaded file saved to: {temp_file_path}")
        logger.info(f"[API] Passing parameters to extractor - vertical: {repr(vertical)}, subvertical: {repr(subvertical)}, extraction_depth: {repr(extraction_depth)}")
        
        # Stream extraction progress
        async def generate_extraction_stream():
            """Generator that yields JSONL events from the extraction process"""
            async for event in extract_capability_model(
                temp_file_path, 
                temp_dir,
                vertical=vertical,
                subvertical=subvertical,
                extraction_depth=extraction_depth
            ):
                # Yield each event as a JSON line
                yield json.dumps(event) + "\n"
        
        return StreamingResponse(
            generate_extraction_stream(),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": f"inline"
            }
        )
        
    except Exception as e:
        logger.error(f"[API] Upload failed: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {str(e)}"
        )
    finally:
        # Clean up temp file after streaming starts (file will be referenced by extractor)
        pass  # Don't delete yet - extractor may still use it


async def _import_chunks_to_knowledge_base(chunks_path: str) -> tuple[int, List[str]]:
    """
    Import document chunks from a JSON file into the Knowledge base in Neo4j.
    
    Creates or fetches the top-level Knowledge node and creates Chunk nodes
    for each chunk in the file, linking them to the Knowledge node.
    
    Args:
        chunks_path: Path to the chunks JSON file created during extraction
        
    Returns:
        Tuple of (chunks_imported_count, cypher_lines)
    """
    chunks_imported = 0
    cypher_lines = []
    
    try:
        if not os.path.exists(chunks_path):
            logger.warning(f"Chunks file not found at {chunks_path}")
            return chunks_imported, cypher_lines
        
        # Load chunks from JSON file
        with open(chunks_path, 'r', encoding='utf-8') as f:
            chunks_data = json.load(f)
        
        # Ensure chunks_data has the expected structure
        if isinstance(chunks_data, dict) and "chunks" in chunks_data:
            chunks = chunks_data["chunks"]
        else:
            chunks = chunks_data if isinstance(chunks_data, list) else []
        
        if not chunks:
            logger.info(f"No chunks found in {chunks_path}")
            return chunks_imported, cypher_lines
        
        # Create or get the Knowledge node (global parent for all chunks)
        cypher_lines.append("MERGE (k:Knowledge {name: 'Knowledge'})")
        
        def _esc(val: str) -> str:
            """Escape string for Cypher queries"""
            if val is None:
                return ""
            s = str(val)
            s = s.replace('\\', '\\\\')
            s = s.replace('"', '\\"')
            s = s.replace("'", "\\'")
            return s
        
        # Create chunk nodes and link to Knowledge
        for idx, chunk in enumerate(chunks):
            chunk_text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})
            embedding = chunk.get("embedding", [])
            
            if not chunk_text.strip():
                continue
            
            # Extract metadata
            page = metadata.get("page", 0)
            section = metadata.get("section", "Unknown")
            source = metadata.get("source", "Unknown")
            
            chunk_text_truncated = chunk_text
            
            # Create unique chunk ID based on source and index
            chunk_id = f"{source}_{idx}_{page}"
            
            # Create Chunk node with properties including embedding
            chunk_var = f"chunk_{idx}"
            if embedding:
                embedding_str = str(embedding).replace("'", '"')
                cypher_lines.append(
                    f"MERGE ({chunk_var}:Chunk {{"
                    f"id: '{_esc(chunk_id)}', "
                    f"source: '{_esc(source)}', "
                    f"section: '{_esc(section)}', "
                    f"page: {page}, "
                    f"text: '{_esc(chunk_text_truncated)}', "
                    f"embedding: {embedding_str}"
                    f"}})"
                )
            else:
                cypher_lines.append(
                    f"MERGE ({chunk_var}:Chunk {{"
                    f"id: '{_esc(chunk_id)}', "
                    f"source: '{_esc(source)}', "
                    f"section: '{_esc(section)}', "
                    f"page: {page}, "
                    f"text: '{_esc(chunk_text_truncated)}'"
                    f"}})"
                )
            
            # Create relationship from Knowledge to Chunk
            cypher_lines.append(f"MERGE (k)-[:CONTAINS_CHUNK]->({chunk_var})")
            chunks_imported += 1
        logger.info(f"Prepared {chunks_imported} chunks for import from {chunks_path}")
        
    except Exception as e:
        logger.error(f"Error processing chunks file {chunks_path}: {e}", exc_info=True)
    
    return chunks_imported, cypher_lines


@router.post("/upload/import-to-graph")
async def import_extracted_model_to_graph(payload: CapabilityImportRequest):
    """
    Import an extracted capability model into the graph database.
    
    Takes the JSON model structure from the DeepAgent extraction
    and imports it as Capability -> Vertical -> SubVertical -> Process -> SubProcess
    structure in the database. Also imports document chunks into a Knowledge base.
    
    Args:
        payload.model_data: The extracted capability model JSON
        payload.chunks_path: Optional path to chunks JSON file for knowledge base
        
    Returns:
        Success response with import summary including chunks imported
    """
    
    try:
        model_data = payload.model_data
        
        # Validate the model structure
        is_valid, errors = validate_extracted_model(model_data)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid model structure: {'; '.join(errors)}"
            )
        
        logger.info(f"Starting import of capability model: {model_data.get('name', 'Unknown')}")
        
        # Extract top-level information
        capability_name = model_data.get("name", "Unnamed Capability")
        capability_description = model_data.get("description", "")
        vertical_name = model_data.get("vertical", "General")
        subvertical_name = model_data.get("subvertical", "General")
        
        # Step 1: Create or fetch vertical
        existing_verticals = await vertical_repository.fetch_all_verticals()
        vertical = None
        for v in existing_verticals:
            if v.name.lower() == vertical_name.lower():
                vertical = v
                break
        
        if not vertical:
            vertical = await vertical_repository.create_vertical(vertical_name)
            logger.info(f"Created vertical: {vertical_name}")
        else:
            logger.info(f"Using existing vertical: {vertical_name}")
        
        # Step 2: Create or fetch subvertical
        existing_subverticals = await vertical_repository.fetch_subverticals_by_vertical(vertical.id)
        subvertical = None
        for sv in existing_subverticals:
            if sv.name.lower() == subvertical_name.lower():
                subvertical = sv
                break
        
        if not subvertical:
            subvertical = await vertical_repository.create_subvertical(subvertical_name, vertical.id)
            logger.info(f"Created subvertical: {subvertical_name}")
        else:
            logger.info(f"Using existing subvertical: {subvertical_name}")
        
        # Step 3: Create capability
        capability = await capability_repository.create_capability(
            capability_name,
            capability_description,
            subvertical.id
        )
        logger.info(f"Created capability: {capability_name} (ID: {capability.id})")
        
        # Step 4: Create processes, subprocesses, data entities and data elements
        process_count = 0
        subprocess_count = 0
        data_entity_count = 0
        data_element_count = 0
        # Prepare Cypher lines to sync to Neo4j cloud via /execute-cypher
        cypher_lines = []

        def _esc(val: str) -> str:
            if val is None:
                return ""
            s = str(val)
            s = s.replace('\\', '\\\\')
            s = s.replace("'", "\\'")
            return s

        # Merge top-level vertical/subvertical/capability in cypher
        # Include uid from local database for retrieval
        cypher_lines.append(f"MERGE (v:Vertical {{uid: {vertical.id}, name: '{_esc(vertical_name)}'}})")
        cypher_lines.append(f"MERGE (sv:SubVertical {{uid: {subvertical.id}, name: '{_esc(subvertical_name)}'}})")
        cypher_lines.append("MERGE (v)-[:HAS_SUBVERTICAL]->(sv)")
        cypher_lines.append(f"MERGE (c:Capability {{uid: {capability.id}, name: '{_esc(capability_name)}'}})")
        cypher_lines.append("MERGE (sv)-[:HAS_CAPABILITY]->(c)")
        # counters to create unique variable names in the cypher batch (avoid redeclaration)
        _proc_counter = 0
        _subproc_counter = 0
        _de_counter = 0
        _delem_counter = 0

        for process_data in model_data.get("processes", []):
            process_name = process_data.get("name", "Unnamed Process")
            process_description = process_data.get("description", "")
            raw_level = str(process_data.get("level", "core") or "core")
            process_category = process_data.get("category", "")

            # Normalize process level to allowed ProcessLevel values
            lvl = raw_level.strip().lower()
            level_map = {
                "enterprise": "enterprise",
                "enterpise": "enterprise",
                "core": "core",
                "process": "process",
                # Map common terms to a safe enum value
                "support": "process",
                "supporting": "process",
                "supporting function": "process",
                "operational": "process",
            }
            process_level = level_map.get(lvl, "process")
            
            # Create process with subprocesses
            subprocesses_list = []
            for subprocess_data in process_data.get("subprocesses", []):
                subproc = {
                    "name": subprocess_data.get("name", "Unnamed SubProcess"),
                    "description": subprocess_data.get("description", ""),
                    "category": subprocess_data.get("category", "")
                }
                subprocesses_list.append(subproc)
            
            process = await process_repository.create_process(
                process_name,
                process_level,
                process_description,
                capability.id,
                subprocesses=subprocesses_list,
                category=process_category
            )
            
            process_count += 1
            subprocess_count += len(subprocesses_list)
            logger.info(f"Created process: {process_name} with {len(subprocesses_list)} subprocesses")

            # Add process MERGE and relationship to capability (use a unique var)
            _proc_counter += 1
            p_var = f"p{_proc_counter}"
            cypher_lines.append(f"MERGE ({p_var}:Process {{uid: {process.id}, name: '{_esc(process_name)}', level: '{_esc(process_level)}'}})")
            cypher_lines.append(f"MERGE (c)-[:HAS_PROCESS]->({p_var})")

            # --- Persist Data Entities and Data Elements (if provided by extractor) ---
            # Import models locally to avoid top-level coupling
            from database.models import DataEntity, DataElement, SubProcess as SubProcessModel

            try:
                # Fetch created subprocess records for this process so we can attach data entities
                created_subprocs = await SubProcessModel.filter(process_id=process.id).all()
                # Build a lookup by name (lowercased) to match extractor payloads
                subproc_lookup = { (s.name or "").strip().lower(): s for s in created_subprocs }

                for subprocess_data in process_data.get("subprocesses", []):
                    subproc_name = (subprocess_data.get("name") or "").strip()
                    if not subproc_name:
                        continue

                    subproc = subproc_lookup.get(subproc_name.lower())
                    if not subproc:
                        # Try a looser match (starts-with) as a fallback
                        subproc = next((s for k, s in subproc_lookup.items() if k.startswith(subproc_name.lower()[:10])), None)
                    if not subproc:
                        logger.debug(f"SubProcess not found for data entities: {subproc_name}")
                        continue

                    # Ensure a SubProcess node is created in Neo4j and related to the Process (unique var)
                    _subproc_counter += 1
                    sp_var = f"sp{_subproc_counter}"
                    cypher_lines.append(f"MERGE ({sp_var}:Subprocess {{uid: {subproc.id}, name: '{_esc(subproc_name)}'}})")
                    cypher_lines.append(f"MERGE ({p_var})-[:DECOMPOSES]->({sp_var})")

                    # Extract data entities list - extractor may use either 'data_entities' or 'data_entity' keys
                    data_entities = subprocess_data.get("data_entities") or subprocess_data.get("data_entity") or []
                    if isinstance(data_entities, dict):
                        # Single object provided, wrap into list
                        data_entities = [data_entities]

                    for de in data_entities:
                        # Support multiple possible key names coming from the LLM
                        data_entity_name = de.get("data_entity_name") or de.get("name") or de.get("data_entity") or ""
                        data_entity_description = de.get("data_entity_description") or de.get("description") or de.get("data_entity_description") or ""
                        if not data_entity_name:
                            continue

                        # Create or get DataEntity under this SubProcess
                        data_entity, de_created = await DataEntity.get_or_create(
                            name=data_entity_name,
                            subprocess=subproc,
                            defaults={
                                "description": data_entity_description
                            }
                        )
                        # If get_or_create returned tuple style (older tortoise), ensure we handle it
                        if isinstance(data_entity, tuple):
                            data_entity = data_entity[0]
                            de_created = data_entity[1] if len(data_entity) > 1 else False

                        if de_created:
                            logger.info(f"✓ Created DataEntity: {data_entity_name} (ID: {data_entity.id})")
                            data_entity_count += 1
                        else:
                            logger.debug(f"↻ DataEntity already exists: {data_entity_name}")

                        # Add DataEntity MERGE and relationship (unique var)
                        _de_counter += 1
                        de_var = f"de{_de_counter}"
                        cypher_lines.append(f"MERGE ({de_var}:DataEntity {{uid: {data_entity.id}, name: '{_esc(data_entity_name)}'}})")
                        cypher_lines.append(f"MERGE ({sp_var})-[:USES_DATA]->({de_var})")

                        # Create data elements under the data entity
                        data_elements = de.get("data_elements") or de.get("elements") or []
                        if isinstance(data_elements, dict):
                            data_elements = [data_elements]

                        for elem in data_elements:
                            data_element_name = elem.get("data_element_name") or elem.get("name") or elem.get("data_element") or ""
                            data_element_description = elem.get("data_element_description") or elem.get("description") or ""
                            if not data_element_name:
                                continue

                            data_element, del_created = await DataElement.get_or_create(
                                name=data_element_name,
                                data_entity=data_entity,
                                defaults={
                                    "description": data_element_description
                                }
                            )
                            if isinstance(data_element, tuple):
                                data_element = data_element[0]
                                del_created = data_element[1] if len(data_element) > 1 else False

                            if del_created:
                                logger.info(f"✓ Created DataElement: {data_element_name} under {data_entity.name}")
                                data_element_count += 1
                            else:
                                logger.debug(f"↻ DataElement already exists: {data_element_name}")

                            # Add DataElement MERGE and relationship (unique var)
                            _delem_counter += 1
                            delem_var = f"delem{_delem_counter}"
                            cypher_lines.append(f"MERGE ({delem_var}:DataElements {{uid: {data_element.id}, name: '{_esc(data_element_name)}'}})")
                            cypher_lines.append(f"MERGE ({de_var})-[:HAS_ELEMENT]->({delem_var})")

            except Exception as e:
                logger.warning(f"Failed to persist data entities/elements for process {process_name}: {e}")
        
        logger.info(f"Import completed successfully")
        
        # Step 5: Import chunks if chunks_path is provided
        chunks_imported = 0
        if payload.chunks_path:
            chunks_imported, chunks_cypher = await _import_chunks_to_knowledge_base(payload.chunks_path)
            cypher_lines.extend(chunks_cypher)
            logger.info(f"Added {chunks_imported} chunks to import")
        
        # After local DB insertions, attempt to sync to Neo4j cloud via the API
        try:
            import requests

            cypher_query = "\n".join(cypher_lines)
            # POST to Neo4J API (separate service)
            try:
                r = requests.post("http://localhost:5000/execute-cypher", json={"query": cypher_query}, timeout=30)
                if r.status_code == 200:
                    logger.info("Synced imported model to Neo4j cloud successfully")
                else:
                    logger.warning(f"Neo4j sync returned status {r.status_code}: {r.text}")
            except Exception as e:
                logger.warning(f"Failed to call Neo4j API to execute cypher: {e}")
        except Exception:
            # Avoid failing the import if sync machinery has issues
            logger.exception("Unexpected error while preparing Neo4j sync")

        return JSONResponse({
            "status": "success",
            "message": "Model imported successfully",
            "summary": {
                "capability_name": capability_name,
                "vertical": vertical_name,
                "subvertical": subvertical_name,
                "capability_id": capability.id,
                "processes_created": process_count,
                "subprocesses_created": subprocess_count,
                "data_entities_created": data_entity_count,
                "data_elements_created": data_element_count,
                "chunks_imported": chunks_imported
            }
        })
        
    except Exception as e:
        logger.error(f"Import failed: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {str(e)}"
        )


@router.get("/upload/formats-info")
async def get_supported_formats():
    """Get information about supported file formats for ingestion"""
    return JSONResponse({
        "supported_formats": [
            {
                "extension": ".pdf",
                "name": "PDF Document",
                "description": "Adobe PDF files"
            },
            {
                "extension": ".docx",
                "name": "Word Document",
                "description": "Microsoft Word (.docx) files"
            },
            {
                "extension": ".txt",
                "name": "Text File",
                "description": "Plain text files"
            }
        ],
        "max_file_size_mb": 100,
        "extraction_method": "DeepAgent with Azure OpenAI LLM",
        "output_format": "Capability Model JSON"
    })
    
