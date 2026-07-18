import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database.services import WorkspaceService, DocumentService, WorkspaceChunkService

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])
logger = logging.getLogger(__name__)


class WorkspaceCreateRequest(BaseModel):
    name: str
    client_name: str
    tags: Optional[List[str]] = Field(default_factory=list)
    description: Optional[str] = ""


class WorkspaceUpdateRequest(BaseModel):
    name: Optional[str] = None
    client_name: Optional[str] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None


class DocumentCreateRequest(BaseModel):
    file_name: str
    file_size: Optional[str] = ""
    page_count: Optional[int] = 0
    chunk_count: Optional[int] = 0
    uploaded_at: Optional[str] = None


class DocumentUpdateRequest(BaseModel):
    file_name: Optional[str] = None
    file_size: Optional[str] = None
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None


class ChunkCreateRequest(BaseModel):
    chunk_text: str
    start_page: Optional[int] = None
    end_page: Optional[int] = None


class ChunkUpdateRequest(BaseModel):
    chunk_text: Optional[str] = None
    start_page: Optional[int] = None
    end_page: Optional[int] = None


@router.get("/documents/{document_id}")
async def get_document(document_id: int):
    try:
        document = await DocumentService.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return JSONResponse(document)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/documents/{document_id}")
async def update_document(document_id: int, payload: DocumentUpdateRequest):
    try:
        document = await DocumentService.update_document(
            document_id,
            file_name=payload.file_name,
            file_size=payload.file_size,
            page_count=payload.page_count,
            chunk_count=payload.chunk_count,
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return JSONResponse(document)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int):
    try:
        deleted = await DocumentService.delete_document(document_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{document_id}/chunks")
async def list_document_chunks(document_id: int):
    try:
        document = await DocumentService.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        chunks = await WorkspaceChunkService.get_chunks_by_document(document_id)
        return JSONResponse(chunks)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list chunks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/{document_id}/chunks")
async def create_document_chunk(document_id: int, payload: ChunkCreateRequest):
    try:
        document = await DocumentService.get_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        chunk = await WorkspaceChunkService.create_chunk(
            document_id=document_id,
            chunk_text=payload.chunk_text,
            start_page=payload.start_page,
            end_page=payload.end_page,
        )
        if not chunk:
            raise HTTPException(status_code=400, detail="Failed to create chunk")
        return JSONResponse(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create chunk: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chunks/{chunk_id}")
async def get_chunk(chunk_id: int):
    try:
        chunk = await WorkspaceChunkService.get_chunk_by_id(chunk_id)
        if not chunk:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return JSONResponse(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get chunk: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/chunks/{chunk_id}")
async def update_chunk(chunk_id: int, payload: ChunkUpdateRequest):
    try:
        chunk = await WorkspaceChunkService.update_chunk(
            chunk_id,
            chunk_text=payload.chunk_text,
            start_page=payload.start_page,
            end_page=payload.end_page,
        )
        if not chunk:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return JSONResponse(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update chunk: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/chunks/{chunk_id}")
async def delete_chunk(chunk_id: int):
    try:
        deleted = await WorkspaceChunkService.delete_chunk(chunk_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete chunk: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_workspaces(
    search: Optional[str] = Query(None),
    tag: Optional[List[str]] = Query(None),
):
    try:
        workspaces = await WorkspaceService.get_all_workspaces(search=search, tags=tag)
        return JSONResponse(workspaces)
    except Exception as e:
        logger.error(f"Failed to list workspaces: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_workspace(payload: WorkspaceCreateRequest):
    try:
        workspace = await WorkspaceService.create_workspace(
            name=payload.name,
            client_name=payload.client_name,
            tags=payload.tags or [],
            description=payload.description or "",
        )
        if not workspace:
            raise HTTPException(status_code=400, detail="Failed to create workspace")
        return JSONResponse(workspace)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create workspace: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: int):
    try:
        workspace = await WorkspaceService.get_workspace_by_id(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return JSONResponse(workspace)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workspace: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{workspace_id}")
async def update_workspace(workspace_id: int, payload: WorkspaceUpdateRequest):
    try:
        workspace = await WorkspaceService.update_workspace(
            workspace_id,
            name=payload.name,
            client_name=payload.client_name,
            tags=payload.tags,
            description=payload.description,
        )
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return JSONResponse(workspace)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update workspace: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: int):
    try:
        deleted = await WorkspaceService.delete_workspace(workspace_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete workspace: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workspace_id}/documents")
async def list_workspace_documents(workspace_id: int):
    try:
        workspace = await WorkspaceService.get_workspace_by_id(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        documents = await DocumentService.get_documents_by_workspace(workspace_id)
        return JSONResponse(documents)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workspace_id}/documents")
async def create_workspace_document(workspace_id: int, payload: DocumentCreateRequest):
    try:
        workspace = await WorkspaceService.get_workspace_by_id(workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        document = await DocumentService.create_document(
            workspace_id=workspace_id,
            file_name=payload.file_name,
            file_size=payload.file_size,
            page_count=payload.page_count,
            chunk_count=payload.chunk_count,
        )
        if not document:
            raise HTTPException(status_code=400, detail="Failed to create document")
        return JSONResponse(document)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
