"""
Neo4j-based API routes to replace SQLite endpoints
"""
import logging
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional

from neo4j_graph.services.vertical_service import VerticalService
from neo4j_graph.services.capability_service import CapabilityService
from neo4j_graph.services.process_service import ProcessService
from neo4j_graph.services.subprocess_service import SubprocessService
from neo4j_graph.services.query_execution_service import Neo4jQueryService

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models
# ============================================================================

class VerticalCreateRequest(BaseModel):
    name: str


class SubVerticalCreateRequest(BaseModel):
    name: str
    vertical_id: int


class CapabilityCreateRequest(BaseModel):
    name: str
    description: str
    subvertical_id: Optional[int] = None


class SubprocessData(BaseModel):
    name: str
    description: Optional[str] = ""
    category: Optional[str] = None


class ProcessCreateRequest(BaseModel):
    name: str
    level: str
    description: str
    capability_id: int
    category: Optional[str] = None
    subprocesses: Optional[List[SubprocessData]] = None


class SubprocessCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    category: Optional[str] = None
    parent_process_id: int


# ============================================================================
# Verticals & SubVerticals
# ============================================================================

@router.get("/verticals")
async def list_verticals():
    """List all verticals"""
    try:
        verticals = VerticalService.get_all_verticals()
        # Add id field for frontend compatibility
        for v in verticals:
            v["id"] = v["uid"]
        return JSONResponse(verticals)
    except Exception as e:
        logger.error(f"Failed to list verticals: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verticals")
async def create_vertical(payload: VerticalCreateRequest):
    """Create a new vertical"""
    try:
        # Get next UID
        query = "MATCH (v:Vertical) RETURN max(v.uid) AS max_uid"
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            max_uid = results[0]["max_uid"] if results and results[0]["max_uid"] else 0
            new_uid = max_uid + 1
        finally:
            svc.close()
        
        vertical = VerticalService.create_vertical(payload.name, new_uid)
        return JSONResponse(vertical)
    except Exception as e:
        logger.error(f"Failed to create vertical: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subverticals")
async def list_subverticals(vertical_id: Optional[int] = Query(None)):
    """List all subverticals, optionally filtered by vertical"""
    try:
        if vertical_id:
            subverticals = VerticalService.get_subverticals_by_vertical(vertical_id)
        else:
            subverticals = VerticalService.get_all_subverticals()
        
        # Add id field for frontend compatibility
        for sv in subverticals:
            sv["id"] = sv["uid"]
            # Map vertical_uid to vertical_id for frontend compatibility
            if "vertical_uid" in sv:
                sv["vertical_id"] = sv["vertical_uid"]
        
        return JSONResponse(subverticals)
    except Exception as e:
        logger.error(f"Failed to list subverticals: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/subverticals")
async def create_subvertical(payload: SubVerticalCreateRequest):
    """Create a new subvertical"""
    try:
        # Get next UID
        query = "MATCH (sv:SubVertical) RETURN max(sv.uid) AS max_uid"
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            max_uid = results[0]["max_uid"] if results and results[0]["max_uid"] else 0
            new_uid = max_uid + 1
        finally:
            svc.close()
        
        subvertical = VerticalService.create_subvertical(payload.name, new_uid, payload.vertical_id)
        if not subvertical:
            raise HTTPException(status_code=404, detail="Vertical not found")
        
        # Add id field for frontend compatibility
        subvertical["id"] = subvertical["uid"]
        if "vertical_uid" in subvertical:
            subvertical["vertical_id"] = subvertical["vertical_uid"]
        
        return JSONResponse(subvertical)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create subvertical: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subverticals/{subvertical_id}")
async def get_subvertical(subvertical_id: int):
    """Get a specific subvertical"""
    try:
        # Get subvertical with its vertical
        all_subverticals = VerticalService.get_all_subverticals()
        subvertical = next((sv for sv in all_subverticals if sv["uid"] == subvertical_id), None)
        if not subvertical:
            raise HTTPException(status_code=404, detail="SubVertical not found")
        
        # Add id field for frontend compatibility
        subvertical["id"] = subvertical["uid"]
        if "vertical_uid" in subvertical:
            subvertical["vertical_id"] = subvertical["vertical_uid"]
        return JSONResponse(subvertical)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get subvertical: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/verticals/{vertical_id}")
async def update_vertical(vertical_id: int, payload: VerticalCreateRequest):
    """Update a vertical"""
    try:
        vertical = VerticalService.update_vertical(vertical_id, payload.name)
        if not vertical:
            raise HTTPException(status_code=404, detail="Vertical not found")
        
        vertical["id"] = vertical["uid"]
        return JSONResponse(vertical)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update vertical: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/verticals/{vertical_id}")
async def delete_vertical(vertical_id: int):
    """Delete a vertical"""
    try:
        deleted = VerticalService.delete_vertical(vertical_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Vertical not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete vertical: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/subverticals/{subvertical_id}")
async def update_subvertical(subvertical_id: int, payload: SubVerticalCreateRequest):
    """Update a subvertical"""
    try:
        subvertical = VerticalService.update_subvertical(
            subvertical_id, 
            name=payload.name, 
            vertical_id=payload.vertical_id
        )
        if not subvertical:
            raise HTTPException(status_code=404, detail="SubVertical not found")
        
        subvertical["id"] = subvertical["uid"]
        if "vertical_uid" in subvertical:
            subvertical["vertical_id"] = subvertical["vertical_uid"]
        return JSONResponse(subvertical)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update subvertical: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subverticals/{subvertical_id}")
async def delete_subvertical(subvertical_id: int):
    """Delete a subvertical"""
    try:
        deleted = VerticalService.delete_subvertical(subvertical_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="SubVertical not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete subvertical: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Capabilities
# ============================================================================

@router.get("/capabilities")
async def list_capabilities():
    """List all capabilities with their hierarchy"""
    try:
        capabilities = CapabilityService.get_all_capabilities()
        
        # Fetch processes for each capability with full hierarchy
        for cap in capabilities:
            # Add id field for frontend compatibility
            cap["id"] = cap["uid"]
            
            # Get full capability details including processes with subprocesses
            full_cap = CapabilityService.get_capability_by_id(cap["uid"])
            if full_cap:
                cap["processes"] = full_cap.get("processes", [])
                # Update vertical and subvertical from full_cap if available
                cap["vertical"] = full_cap.get("vertical") or cap.get("vertical")
                cap["subvertical"] = full_cap.get("subvertical") or cap.get("subvertical")
            else:
                cap["processes"] = []
        
        return JSONResponse(capabilities)
    except Exception as e:
        logger.error(f"Failed to list capabilities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capabilities/{capability_id}")
async def get_capability(capability_id: int):
    """Get a specific capability with full hierarchical data"""
    try:
        capability = CapabilityService.get_capability_by_id(capability_id)
        if not capability:
            raise HTTPException(status_code=404, detail="Capability not found")
        return JSONResponse(capability)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get capability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/capabilities")
async def create_capability(payload: CapabilityCreateRequest):
    """Create a new capability"""
    try:
        # Get next UID
        query = "MATCH (c:Capability) RETURN max(c.uid) AS max_uid"
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            max_uid = results[0]["max_uid"] if results and results[0]["max_uid"] else 0
            new_uid = max_uid + 1
        finally:
            svc.close()
        
        capability = CapabilityService.create_capability(
            payload.name,
            payload.description,
            new_uid,
            payload.subvertical_id
        )
        if not capability:
            raise HTTPException(status_code=400, detail="Failed to create capability")
        
        # Add id field for frontend compatibility
        capability["id"] = capability["uid"]
        return JSONResponse(capability)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create capability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/capabilities/{capability_id}")
async def update_capability(capability_id: int, payload: CapabilityCreateRequest):
    """Update a capability"""
    try:
        capability = CapabilityService.update_capability(
            capability_id,
            payload.name,
            payload.description,
            payload.subvertical_id
        )
        if not capability:
            raise HTTPException(status_code=404, detail="Capability not found")
        
        capability["id"] = capability["uid"]
        return JSONResponse(capability)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update capability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/capabilities/{capability_id}")
async def delete_capability(capability_id: int):
    """Delete a capability"""
    try:
        deleted = CapabilityService.delete_by_id(capability_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Capability not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete capability: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Processes
# ============================================================================

@router.get("/processes")
async def list_processes(capability_id: Optional[int] = Query(None)):
    """List all processes, optionally filtered by capability"""
    try:
        if capability_id:
            processes = ProcessService.get_processes_by_capability(capability_id)
        else:
            processes = ProcessService.get_all_processes()
            # Add id field for frontend compatibility
            for p in processes:
                p["id"] = p["uid"]
        
        return JSONResponse(processes)
    except Exception as e:
        logger.error(f"Failed to list processes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/processes")
async def create_process(payload: ProcessCreateRequest):
    """Create a new process"""
    try:
        # Get next UID for process
        query = "MATCH (p:Process) RETURN max(p.uid) AS max_uid"
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            max_uid = results[0]["max_uid"] if results and results[0]["max_uid"] else 0
            new_uid = max_uid + 1
            
            # Get next UID for subprocesses
            sp_query = "MATCH (sp:Subprocess) RETURN max(sp.uid) AS max_uid"
            sp_results = svc.execute_cypher(sp_query)
            sp_max_uid = sp_results[0]["max_uid"] if sp_results and sp_results[0]["max_uid"] else 0
        finally:
            svc.close()
        
        # Prepare subprocess data with UIDs
        subprocesses_with_uids = []
        if payload.subprocesses:
            for i, sp in enumerate(payload.subprocesses):
                subprocesses_with_uids.append({
                    "uid": sp_max_uid + i + 1,
                    "name": sp.name,
                    "description": sp.description or "",
                    "category": sp.category
                })
        
        process = ProcessService.create_process(
            payload.name,
            payload.level,
            payload.description,
            new_uid,
            payload.capability_id,
            payload.category,
            subprocesses_with_uids
        )
        
        if not process:
            raise HTTPException(status_code=400, detail="Failed to create process")
        
        # Fetch full process with subprocesses
        processes = ProcessService.get_processes_by_capability(payload.capability_id)
        created_process = next((p for p in processes if p["id"] == new_uid), process)
        
        return JSONResponse(created_process)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create process: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/processes/{process_id}")
async def delete_process(process_id: int):
    """Delete a process"""
    try:
        deleted = ProcessService.delete_process(process_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Process not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete process: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Subprocesses
# ============================================================================

@router.post("/subprocesses")
async def create_subprocess(payload: SubprocessCreateRequest):
    """Create a new subprocess"""
    try:
        # Get next UID
        query = "MATCH (sp:Subprocess) RETURN max(sp.uid) AS max_uid"
        svc = Neo4jQueryService()
        try:
            results = svc.execute_cypher(query)
            max_uid = results[0]["max_uid"] if results and results[0]["max_uid"] else 0
            new_uid = max_uid + 1
        finally:
            svc.close()
        
        subprocess = SubprocessService.create_subprocess(
            payload.name,
            payload.description or "",
            new_uid,
            payload.parent_process_id,
            payload.category
        )
        
        if not subprocess:
            raise HTTPException(status_code=400, detail="Failed to create subprocess")
        
        # Add id field for frontend compatibility
        subprocess["id"] = subprocess["uid"]
        return JSONResponse(subprocess)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create subprocess: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subprocesses/{subprocess_id}")
async def delete_subprocess(subprocess_id: int):
    """Delete a subprocess"""
    try:
        deleted = SubprocessService.delete_subprocess(subprocess_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Subprocess not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete subprocess: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Research (Keyword Search)
# ============================================================================

class ResearchRequest(BaseModel):
    query: str


@router.post("/capabilities/research")
async def research_capabilities(payload: ResearchRequest):
    """LLM-based intelligent search across entity hierarchy"""
    from neo4j_graph.routes.llm_research_endpoint import llm_research_capabilities
    return await llm_research_capabilities(payload.query)


# ============================================================================
# Domains (alias for verticals for frontend compatibility)
# ============================================================================

@router.get("/domains")
async def list_domains():
    """List all domains (alias for verticals)"""
    return await list_verticals()


# ============================================================================
# LLM & Generation Endpoints
# ============================================================================

class ProcessGenerateRequest(BaseModel):
    capability_name: str
    capability_id: int
    capability_description: str
    domain: str
    process_type: str
    prompt: str


@router.post("/processes/generate")
async def generate_processes(payload: ProcessGenerateRequest):
    """Generate processes using LLM and save them to Neo4j"""
    try:
        logger.info(f"/processes/generate called with payload: capability_name={payload.capability_name}, capability_id={payload.capability_id}, domain={payload.domain}, process_type={payload.process_type}")
        
        # Import LLM utilities
        from config.llm_settings import llm_settings_manager
        from utils.llm import azure_openai_client
        from utils.llm2 import gemini_client
        from utils.csv_export import get_csv_exporter
        
        provider = llm_settings_manager.get_setting("provider", "secure")
        logger.info(f"Using LLM provider: {provider}")
        
        if provider == "gemini":
            llm_client = gemini_client
        else:
            llm_client = azure_openai_client
        
        logger.info(f"Calling {provider} LLM client.generate_processes...")
        try:
            llm_result = await llm_client.generate_processes(
                payload.capability_name, 
                payload.capability_description or "", 
                payload.domain, 
                payload.process_type,
                payload.prompt
            )
            logger.info(f"LLM returned: {llm_result}")
        except Exception as e:
            logger.exception("LLM call failed")
            raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")
        
        if llm_result.get("status") != "success":
            raise HTTPException(status_code=500, detail="Failed to generate processes from LLM")
        
        generated_data = llm_result.get("data", {})
        
        logger.info(f"[DEBUG] generated_data type: {type(generated_data)}")
        logger.info(f"[DEBUG] generated_data keys: {list(generated_data.keys()) if isinstance(generated_data, dict) else 'not a dict'}")
        
        # Verify capability exists in Neo4j
        capability = CapabilityService.get_capability_by_id(payload.capability_id)
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
        
        # Don't save to Neo4j automatically - return data for frontend to review and save
        # This matches the frontend's expectation of reviewing generated processes
        processes_data = generated_data.get("processes", [])
        if not isinstance(processes_data, list):
            logger.warning(f"Expected 'processes' to be a list, got {type(processes_data)}. Wrapping in list.")
            processes_data = [processes_data]
        
        return {
            "status": "success",
            "message": f"Generated processes for {payload.capability_name}",
            "processes": [],  # Empty because we don't auto-save
            "data": generated_data,
            "process_type": payload.process_type or 'core',
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating processes: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate processes: {str(e)}")


@router.get("/settings/prompt-template/{process_level}")
async def get_prompt_template(process_level: str):
    """Get prompt template for process level"""
    try:
        from config.prompt_templates import prompt_template_manager
        
        template = await prompt_template_manager.get_template(process_level)
        return JSONResponse({
            "process_level": process_level,
            "prompt": template
        })
    except Exception as e:
        logger.error(f"Failed to get prompt template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class BulkExportRequest(BaseModel):
    ids: List[int]


CSV_EXPORT_HEADERS = [
    'Vertical',
    'Sub-Vertical',
    'Capability Name',
    'Capability Description',
    'Process Name',
    'Process Description',
    'Subprocess Name',
    'Subprocess Description',
    'Subprocess Category',
    'Data Entities',
    'Data Entity Description',
    'Data Elements',
    'Data Element Description',
    'Organization Units',
    'Applications',
]


def _format_data_entities(data_entities: list) -> tuple[str, str, str, str]:
    entity_names = []
    entity_descriptions = []
    element_names = []
    element_descriptions = []

    for de in data_entities:
        entity_name = de.get("data_entity_name", "")
        entity_desc = de.get("data_entity_description", "")
        if entity_name:
            entity_names.append(entity_name)
            entity_descriptions.append(entity_desc or "")

        for elem in de.get("data_elements", []):
            elem_name = elem.get("data_element_name", "")
            elem_desc = elem.get("data_element_description", "")
            if elem_name:
                element_names.append(f"{elem_name} ({entity_name})" if entity_name else elem_name)
                element_descriptions.append(elem_desc or "")

    return (
        ", ".join(entity_names),
        ", ".join(entity_descriptions),
        "; ".join(element_names),
        "; ".join(element_descriptions),
    )


def _build_capability_csv_rows(capability: dict) -> list[list]:
    rows = []
    vertical = capability.get("vertical", "")
    subvertical = capability.get("subvertical", "")
    cap_name = capability.get("name", "")
    cap_desc = capability.get("description", "")
    org_units_str = ", ".join(capability.get("org_units", []))

    processes = capability.get("processes", [])
    if not processes:
        rows.append([
            vertical, subvertical, cap_name, cap_desc,
            "", "", "", "", "",
            "", "", "", "",
            org_units_str, "",
        ])
        return rows

    for proc in processes:
        proc_name = proc.get("name", "")
        proc_desc = proc.get("description", "")

        subprocesses = proc.get("subprocesses", [])
        if not subprocesses:
            rows.append([
                vertical, subvertical, cap_name, cap_desc,
                proc_name, proc_desc,
                "", "", "",
                "", "", "", "",
                org_units_str, "",
            ])
            continue

        for subproc in subprocesses:
            data_entities = subproc.get("data_entities", [])
            (
                data_entity_names,
                data_entity_descs,
                data_elements_str,
                data_element_descs,
            ) = _format_data_entities(data_entities)
            applications_str = ", ".join(subproc.get("applications", []))

            rows.append([
                vertical, subvertical, cap_name, cap_desc,
                proc_name, proc_desc,
                subproc.get("name", ""),
                subproc.get("description", ""),
                subproc.get("category", ""),
                data_entity_names,
                data_entity_descs,
                data_elements_str,
                data_element_descs,
                org_units_str,
                applications_str,
            ])

    return rows


def _build_capabilities_csv(capabilities: list[dict]) -> str:
    import io
    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_EXPORT_HEADERS)

    for capability in capabilities:
        for row in _build_capability_csv_rows(capability):
            writer.writerow(row)

    output.seek(0)
    return output.getvalue()


def _csv_streaming_response(csv_content: str, filename: str):
    import io
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        io.BytesIO(csv_content.encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/export/capability/{capability_id}/csv")
async def export_capability_csv(capability_id: int):
    """Export a single capability as CSV"""
    try:
        capability = CapabilityService.get_capability_by_id(capability_id)
        if not capability:
            raise HTTPException(status_code=404, detail="Capability not found")

        csv_content = _build_capabilities_csv([capability])
        filename = f"{capability.get('name', 'capability').replace(' ', '_')}_export.csv"
        return _csv_streaming_response(csv_content, filename)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export CSV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export/capabilities/csv")
async def export_capabilities_csv(request: BulkExportRequest):
    """Export multiple capabilities into a single CSV file"""
    try:
        if not request.ids:
            raise HTTPException(status_code=400, detail="Select at least one capability to export")

        capabilities = []
        missing_ids = []
        for capability_id in request.ids:
            capability = CapabilityService.get_capability_by_id(capability_id)
            if capability:
                capabilities.append(capability)
            else:
                missing_ids.append(capability_id)

        if not capabilities:
            raise HTTPException(status_code=404, detail="No capabilities found for export")

        csv_content = _build_capabilities_csv(capabilities)
        filename = "capabilities_export.csv"
        if len(capabilities) == 1:
            filename = f"{capabilities[0].get('name', 'capability').replace(' ', '_')}_export.csv"

        response = _csv_streaming_response(csv_content, filename)
        if missing_ids:
            response.headers["X-Missing-Capability-Ids"] = ",".join(str(i) for i in missing_ids)
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to bulk export CSV: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LLM Settings Endpoints
# ============================================================================

@router.get("/settings/llm-provider")
async def get_llm_provider():
    """Get current LLM provider and settings"""
    try:
        from config.llm_settings import llm_settings_manager
        
        settings = llm_settings_manager.get_all_settings()
        return JSONResponse({
            "provider": settings.get("provider", "azure"),
            "vaultName": settings.get("vaultName", ""),
            "temperature": settings.get("temperature", 0.2),
            "topP": settings.get("topP", 0.9),
        })
    except Exception as e:
        logger.error(f"Failed to get LLM provider: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/llm-provider")
async def update_llm_provider(request: Request):
    """Update LLM provider"""
    try:
        from config.llm_settings import llm_settings_manager
        
        body = await request.json()
        provider = body.get("provider", "azure")
        
        # Update only the provider field
        llm_settings_manager.update_settings({"provider": provider})
        
        return JSONResponse({
            "status": "success",
            "provider": provider
        })
    except Exception as e:
        logger.error(f"Failed to update LLM provider: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings/llm-config")
async def update_llm_config(request: Request):
    """Update full LLM configuration"""
    try:
        from config.llm_settings import llm_settings_manager
        
        body = await request.json()
        
        # Update settings using the manager's update method
        # The manager handles field name mapping internally
        llm_settings_manager.update_settings(body)
        
        return JSONResponse({
            "status": "success",
            "settings": llm_settings_manager.get_all_settings()
        })
    except Exception as e:
        logger.error(f"Failed to update LLM config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
