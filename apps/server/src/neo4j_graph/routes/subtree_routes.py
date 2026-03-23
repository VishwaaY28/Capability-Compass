from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional
from neo4j_graph.services.capability_service import CapabilityService
from neo4j_graph.services.process_service import ProcessService
from neo4j_graph.services.subprocess_service import SubprocessService
from neo4j_graph.services.dataentity_service import DataEntityService
from neo4j_graph.services.dataelement_service import DataElementService
from neo4j_graph.services.orgunits_service import OrganizationUnitService
from neo4j_graph.services.applicationcatalog_service import ApplicationCatalogService

router = APIRouter(prefix="/subtree", tags=["Neo4J Subtree"])

SERVICE_MAP = {
    "capability": CapabilityService,
    "process": ProcessService,
    "subprocess": SubprocessService,
    "dataentity": DataEntityService,
    "dataelement": DataElementService,
    "orgunits": OrganizationUnitService,
    "applicationcatalog": ApplicationCatalogService,
}


def get_service(entity_type: str):
    service = SERVICE_MAP.get(entity_type.lower())
    if not service:
        raise HTTPException(status_code=400, detail=f"Unknown entity type '{entity_type}'")
    return service


@router.get("/{entity_type}/id/{entity_id}")
def get_subtree_by_id(
    entity_type: str = Path(...),
    entity_id: int = Path(...),
    depth: Optional[int] = Query(None),
    direction: Optional[str] = Query('outgoing'),
):
    service = get_service(entity_type)
    result = service.get_subtree_by_id(entity_id, depth=depth, direction=direction)
    if not result:
        raise HTTPException(status_code=404, detail=f"{entity_type.title()} or subtree not found")
    return result


@router.get("/{entity_type}/name/")
def get_subtree_by_name(
    entity_type: str = Path(...),
    name: str = Query(...),
    depth: Optional[int] = Query(None),
    direction: Optional[str] = Query('outgoing'),
):
    service = get_service(entity_type)
    result = service.get_subtree_by_name(name, depth=depth, direction=direction)
    if not result:
        raise HTTPException(status_code=404, detail=f"{entity_type.title()} or subtree not found")
    return result


@router.get("/{entity_type}/all")
def get_all_entities(entity_type: str = Path(...)):
    service = get_service(entity_type)
    et = entity_type.lower()
    if hasattr(service, "get_all_entities"):
        return service.get_all_entities()
    elif et == "capability":
        return service.get_all_capabilities()
    elif et == "process":
        return service.get_all_processes()
    elif et == "subprocess":
        return service.get_all_subprocesses()
    elif et == "dataentity":
        return service.get_all_data_entities()
    elif et == "dataelement":
        return service.get_all_data_elements()
    elif et == "orgunits":
        return service.get_all_organization_units()
    elif et == "applicationcatalog":
        return service.get_all_application_catalogs()
    else:
        raise HTTPException(status_code=400, detail=f"Service for {entity_type} does not support listing all entities")
