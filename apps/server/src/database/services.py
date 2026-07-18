from datetime import datetime
from typing import List, Optional
from tortoise.expressions import Q
from database.models import Workspace, Document, WorkspaceChunk


def _fmt_date(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.strftime("%Y-%m-%d")


async def serialize_workspace(workspace: Workspace) -> dict:
    document_count = await Document.filter(workspace_id=workspace.id).count()
    tags = workspace.tags if isinstance(workspace.tags, list) else []
    return {
        "id": workspace.id,
        "uid": workspace.id,
        "name": workspace.name,
        "client_name": workspace.client_name,
        "tags": tags,
        "description": workspace.description or "",
        "created_at": _fmt_date(workspace.created_at),
        "document_count": document_count,
    }


def serialize_document(document: Document, workspace: Optional[Workspace] = None) -> dict:
    return {
        "id": document.id,
        "uid": document.id,
        "file_name": document.file_name,
        "file_size": document.file_size or "",
        "page_count": document.page_count or 0,
        "chunk_count": document.chunk_count or 0,
        "uploaded_at": _fmt_date(document.uploaded_at),
        "workspace_id": document.workspace_id,
        "workspace_name": workspace.name if workspace else None,
    }


def serialize_chunk(chunk: WorkspaceChunk, document: Optional[Document] = None) -> dict:
    return {
        "id": chunk.id,
        "uid": chunk.id,
        "start_page": chunk.start_page,
        "end_page": chunk.end_page,
        "chunk_text": chunk.chunk_text or "",
        "document_id": chunk.document_id,
        "document_name": document.file_name if document else None,
    }


class WorkspaceService:
    @staticmethod
    async def get_all_workspaces(search: Optional[str] = None, tags: Optional[List[str]] = None):
        qs = Workspace.all().order_by("name")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(client_name__icontains=search)
                | Q(description__icontains=search)
            )
        workspaces = await qs
        result = []
        for workspace in workspaces:
            item = await serialize_workspace(workspace)
            if tags:
                workspace_tags = item.get("tags") or []
                if not all(tag in workspace_tags for tag in tags):
                    continue
            result.append(item)
        return result

    @staticmethod
    async def get_workspace_by_id(workspace_id: int):
        workspace = await Workspace.get_or_none(id=workspace_id)
        if not workspace:
            return None
        return await serialize_workspace(workspace)

    @staticmethod
    async def create_workspace(
        name: str,
        client_name: str,
        tags: Optional[List[str]] = None,
        description: Optional[str] = None,
    ):
        workspace = await Workspace.create(
            name=name,
            client_name=client_name,
            tags=tags or [],
            description=description or "",
        )
        return await serialize_workspace(workspace)

    @staticmethod
    async def update_workspace(
        workspace_id: int,
        name: Optional[str] = None,
        client_name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        description: Optional[str] = None,
    ):
        workspace = await Workspace.get_or_none(id=workspace_id)
        if not workspace:
            return None
        if name is not None:
            workspace.name = name
        if client_name is not None:
            workspace.client_name = client_name
        if tags is not None:
            workspace.tags = tags
        if description is not None:
            workspace.description = description
        await workspace.save()
        return await serialize_workspace(workspace)

    @staticmethod
    async def delete_workspace(workspace_id: int) -> bool:
        workspace = await Workspace.get_or_none(id=workspace_id)
        if not workspace:
            return False
        await workspace.delete()
        return True


class DocumentService:
    @staticmethod
    async def get_documents_by_workspace(workspace_id: int):
        workspace = await Workspace.get_or_none(id=workspace_id)
        if not workspace:
            return []
        documents = await Document.filter(workspace_id=workspace_id).order_by("file_name")
        return [serialize_document(doc, workspace) for doc in documents]

    @staticmethod
    async def get_document_by_id(document_id: int):
        document = await Document.get_or_none(id=document_id)
        if not document:
            return None
        workspace = await document.workspace
        return serialize_document(document, workspace)

    @staticmethod
    async def create_document(
        workspace_id: int,
        file_name: str,
        file_size: Optional[str] = None,
        page_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
    ):
        workspace = await Workspace.get_or_none(id=workspace_id)
        if not workspace:
            return None
        document = await Document.create(
            workspace=workspace,
            file_name=file_name,
            file_size=file_size or "",
            page_count=page_count or 0,
            chunk_count=chunk_count or 0,
        )
        return serialize_document(document, workspace)

    @staticmethod
    async def update_document(
        document_id: int,
        file_name: Optional[str] = None,
        file_size: Optional[str] = None,
        page_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
    ):
        document = await Document.get_or_none(id=document_id)
        if not document:
            return None
        if file_name is not None:
            document.file_name = file_name
        if file_size is not None:
            document.file_size = file_size
        if page_count is not None:
            document.page_count = page_count
        if chunk_count is not None:
            document.chunk_count = chunk_count
        await document.save()
        workspace = await document.workspace
        return serialize_document(document, workspace)

    @staticmethod
    async def delete_document(document_id: int) -> bool:
        document = await Document.get_or_none(id=document_id)
        if not document:
            return False
        await document.delete()
        return True


class WorkspaceChunkService:
    @staticmethod
    async def get_chunks_by_document(document_id: int):
        document = await Document.get_or_none(id=document_id)
        if not document:
            return []
        chunks = await WorkspaceChunk.filter(document_id=document_id).order_by("start_page", "id")
        return [serialize_chunk(chunk, document) for chunk in chunks]

    @staticmethod
    async def get_chunk_by_id(chunk_id: int):
        chunk = await WorkspaceChunk.get_or_none(id=chunk_id)
        if not chunk:
            return None
        document = await chunk.document
        return serialize_chunk(chunk, document)

    @staticmethod
    async def create_chunk(
        document_id: int,
        chunk_text: str,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ):
        document = await Document.get_or_none(id=document_id)
        if not document:
            return None
        chunk = await WorkspaceChunk.create(
            document=document,
            chunk_text=chunk_text or "",
            start_page=start_page,
            end_page=end_page,
        )
        document.chunk_count = (document.chunk_count or 0) + 1
        await document.save()
        return serialize_chunk(chunk, document)

    @staticmethod
    async def update_chunk(
        chunk_id: int,
        chunk_text: Optional[str] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ):
        chunk = await WorkspaceChunk.get_or_none(id=chunk_id)
        if not chunk:
            return None
        if chunk_text is not None:
            chunk.chunk_text = chunk_text
        if start_page is not None:
            chunk.start_page = start_page
        if end_page is not None:
            chunk.end_page = end_page
        await chunk.save()
        document = await chunk.document
        return serialize_chunk(chunk, document)

    @staticmethod
    async def delete_chunk(chunk_id: int) -> bool:
        chunk = await WorkspaceChunk.get_or_none(id=chunk_id)
        if not chunk:
            return False
        document = await chunk.document
        await chunk.delete()
        if document:
            document.chunk_count = max((document.chunk_count or 0) - 1, 0)
            await document.save()
        return True
