import logging
from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional
from pydantic import BaseModel

from neo4j_pmo.services.pmo_entity_service import PmoEntityService
from neo4j_pmo.services.pmo_graph_query_service import PmoGraphQueryService

router = APIRouter(prefix="/pmo", tags=["PMO Subtree"])
logger = logging.getLogger(__name__)


class PmoQueryRequest(BaseModel):
    query: str


@router.get("/labels")
def get_pmo_labels():
    try:
        return PmoEntityService.get_labels()
    except Exception as e:
        logger.error(f"Failed to list PMO labels: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subtree/{label}/all")
def get_all_pmo_entities(label: str = Path(...)):
    try:
        return PmoEntityService.get_all_entities(label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to list PMO entities for {label}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subtree/{label}/uri")
def get_pmo_subtree_by_uri(
    label: str = Path(...),
    uri: str = Query(...),
    depth: Optional[int] = Query(None),
    direction: Optional[str] = Query("outgoing"),
):
    try:
        result = PmoEntityService.get_subtree_by_uri(
            label, uri, depth=depth, direction=direction
        )
        if not result:
            raise HTTPException(status_code=404, detail=f"{label} or subtree not found")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch PMO subtree for {label}/{uri}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
def execute_pmo_query(payload: PmoQueryRequest):
    try:
        return PmoGraphQueryService.execute_visualization_query(payload.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to execute PMO query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
