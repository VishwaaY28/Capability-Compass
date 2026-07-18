import { useCallback } from 'react'
import { API_BASE } from '../utils/apiBase'

export type Workspace = {
  id: number
  uid: number
  name: string
  client_name: string
  tags: string[]
  description: string
  created_at: string
  document_count: number
}

export type WorkspaceDocument = {
  id: number
  uid: number
  file_name: string
  file_size: string
  page_count: number
  chunk_count: number
  uploaded_at: string
  workspace_id?: number
  workspace_name?: string
}

export type WorkspaceChunk = {
  id: number
  uid: number
  start_page?: number | null
  end_page?: number | null
  chunk_text: string
  document_id?: number
  document_name?: string
}

export type WorkspaceCreatePayload = {
  name: string
  client_name: string
  tags?: string[]
  description?: string
}

export type DocumentCreatePayload = {
  file_name: string
  file_size?: string
  page_count?: number
  chunk_count?: number
  uploaded_at?: string
}

export type ChunkCreatePayload = {
  chunk_text: string
  start_page?: number
  end_page?: number
}

async function fetcher<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options)
  if (!res.ok) {
    const error = await res.text()
    throw new Error(error || 'API error')
  }
  return res.json()
}

export function useWorkspaceApi() {
  const listWorkspaces = useCallback(async (search?: string, tags?: string[]) => {
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (tags?.length) tags.forEach((t) => params.append('tag', t))
    const qs = params.toString()
    return fetcher<Workspace[]>(`${API_BASE}/workspaces${qs ? `?${qs}` : ''}`)
  }, [])

  const getWorkspace = useCallback(async (id: number) => {
    return fetcher<Workspace>(`${API_BASE}/workspaces/${id}`)
  }, [])

  const createWorkspace = useCallback(async (payload: WorkspaceCreatePayload) => {
    return fetcher<Workspace>(`${API_BASE}/workspaces`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }, [])

  const updateWorkspace = useCallback(async (id: number, payload: Partial<WorkspaceCreatePayload>) => {
    return fetcher<Workspace>(`${API_BASE}/workspaces/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }, [])

  const deleteWorkspace = useCallback(async (id: number) => {
    return fetcher<{ deleted: boolean }>(`${API_BASE}/workspaces/${id}`, { method: 'DELETE' })
  }, [])

  const listDocuments = useCallback(async (workspaceId: number) => {
    return fetcher<WorkspaceDocument[]>(`${API_BASE}/workspaces/${workspaceId}/documents`)
  }, [])

  const getDocument = useCallback(async (documentId: number) => {
    return fetcher<WorkspaceDocument>(`${API_BASE}/workspaces/documents/${documentId}`)
  }, [])

  const createDocument = useCallback(async (workspaceId: number, payload: DocumentCreatePayload) => {
    return fetcher<WorkspaceDocument>(`${API_BASE}/workspaces/${workspaceId}/documents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }, [])

  const deleteDocument = useCallback(async (documentId: number) => {
    return fetcher<{ deleted: boolean }>(`${API_BASE}/workspaces/documents/${documentId}`, {
      method: 'DELETE',
    })
  }, [])

  const listChunks = useCallback(async (documentId: number) => {
    return fetcher<WorkspaceChunk[]>(`${API_BASE}/workspaces/documents/${documentId}/chunks`)
  }, [])

  const createChunk = useCallback(async (documentId: number, payload: ChunkCreatePayload) => {
    return fetcher<WorkspaceChunk>(`${API_BASE}/workspaces/documents/${documentId}/chunks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }, [])

  const deleteChunk = useCallback(async (chunkId: number) => {
    return fetcher<{ deleted: boolean }>(`${API_BASE}/workspaces/chunks/${chunkId}`, {
      method: 'DELETE',
    })
  }, [])

  return {
    listWorkspaces,
    getWorkspace,
    createWorkspace,
    updateWorkspace,
    deleteWorkspace,
    listDocuments,
    getDocument,
    createDocument,
    deleteDocument,
    listChunks,
    createChunk,
    deleteChunk,
  }
}
