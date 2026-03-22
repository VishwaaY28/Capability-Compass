from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from neo4j_graph.services.query_execution_service import Neo4jQueryService

router = APIRouter(tags=["Neo4J Query"])


class CypherQueryRequest(BaseModel):
    query: str


@router.post("/execute-cypher")
async def execute_cypher_query(request: CypherQueryRequest):
    try:
        service = Neo4jQueryService()
        data = service.execute_cypher(request.query)
        service.close()
        return {"results": data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
