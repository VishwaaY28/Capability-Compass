import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { FiMoreVertical } from 'react-icons/fi'
import toast from 'react-hot-toast'
import {
  useWorkspaceApi,
  type WorkspaceChunk,
  type WorkspaceDocument,
} from '../hooks/useWorkspace'

function fileBadge(fileName: string) {
  const ext = fileName.split('.').pop()?.toUpperCase() || 'FILE'
  if (ext === 'PDF') return { label: 'PDF', className: 'bg-red-100 text-red-700' }
  if (ext === 'DOC' || ext === 'DOCX') return { label: 'DOC', className: 'bg-blue-100 text-blue-700' }
  if (ext === 'XLS' || ext === 'XLSX') return { label: 'XLS', className: 'bg-emerald-100 text-emerald-700' }
  return { label: ext.slice(0, 3), className: 'bg-slate-100 text-slate-700' }
}

export default function WorkspaceDocumentPage() {
  const { workspaceId, documentId } = useParams()
  const navigate = useNavigate()
  const wsId = Number(workspaceId)
  const docId = Number(documentId)
  const { getDocument, listChunks, deleteChunk } = useWorkspaceApi()

  const [document, setDocument] = useState<WorkspaceDocument | null>(null)
  const [chunks, setChunks] = useState<WorkspaceChunk[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'chunks' | 'ontology'>('chunks')
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null)

  useEffect(() => {
    if (menuOpenId === null) return

    const handleOutsideClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement
      if (target.closest('[data-menu-id]')) return
      setMenuOpenId(null)
    }

    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [menuOpenId])

  const load = useCallback(async () => {
    if (!Number.isFinite(docId)) return
    setLoading(true)
    try {
      const [doc, chunkRows] = await Promise.all([getDocument(docId), listChunks(docId)])
      setDocument(doc)
      setChunks(chunkRows)
    } catch (err) {
      console.error(err)
      toast.error('Failed to load document')
      navigate(`/dashboard/workspaces/${wsId}`)
    } finally {
      setLoading(false)
    }
  }, [getDocument, listChunks, docId, navigate, wsId])

  useEffect(() => {
    load()
  }, [load])

  const handleDeleteChunk = async (chunk: WorkspaceChunk) => {
    setMenuOpenId(null)
    if (!window.confirm('Delete this chunk?')) return
    try {
      await deleteChunk(chunk.id)
      toast.success('Chunk deleted')
      await load()
    } catch (err) {
      console.error(err)
      toast.error('Failed to delete chunk')
    }
  }

  if (loading) {
    return <div className="p-8 text-slate-500">Loading document...</div>
  }

  if (!document) {
    return <div className="p-8 text-slate-500">Document not found.</div>
  }

  const badge = fileBadge(document.file_name)
  const workspaceName = document.workspace_name || 'Workspace'

  return (
    <div className="min-h-full bg-slate-50">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <nav className="mb-5 text-sm text-slate-500">
          <Link to="/dashboard/workspaces" className="hover:text-blue-600">
            Workspaces
          </Link>
          <span className="mx-2">›</span>
          <Link to={`/dashboard/workspaces/${wsId}`} className="font-medium text-sky-600 hover:text-sky-700">
            {workspaceName}
          </Link>
          <span className="mx-2 text-slate-400">›</span>
          <span className="text-slate-800">{document.file_name}</span>
        </nav>

        <div className="mb-6 flex items-start gap-4">
          <div
            className={`flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-lg text-sm font-bold ${badge.className}`}
          >
            {badge.label}
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{document.file_name}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {document.file_size || '—'} · {document.uploaded_at || '—'}
            </p>
          </div>
        </div>

        <div className="mb-5 inline-flex rounded-xl bg-slate-200/70 p-1">
          <button
            onClick={() => setActiveTab('chunks')}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              activeTab === 'chunks'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-800'
            }`}
          >
            Chunks ({chunks.length || document.chunk_count || 0})
          </button>
          <button
            onClick={() => setActiveTab('ontology')}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              activeTab === 'ontology'
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-600 hover:text-slate-800'
            }`}
          >
            Ontology Graph
          </button>
        </div>

        {activeTab === 'chunks' ? (
          <div className="space-y-3">
            {chunks.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
                <p className="font-medium text-slate-800">No chunks yet</p>
                <p className="mt-1 text-sm text-slate-500">
                  Chunking logic will populate this view later.
                </p>
              </div>
            ) : (
              chunks.map((chunk) => (
                <div
                  key={chunk.id}
                  className="relative rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      {(chunk.start_page != null || chunk.end_page != null) && (
                        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">
                          Pages {chunk.start_page ?? '?'}–{chunk.end_page ?? '?'}
                        </p>
                      )}
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                        {chunk.chunk_text}
                      </p>
                    </div>
                    <button
                      data-menu-id={chunk.id}
                      onClick={() => setMenuOpenId((v) => (v === chunk.id ? null : chunk.id))}
                      className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                    >
                      <FiMoreVertical size={16} />
                    </button>
                  </div>
                  {menuOpenId === chunk.id && (
                    <div
                      data-menu-id={chunk.id}
                      className="absolute right-4 top-10 z-10 w-36 rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
                    >
                      <button
                        onClick={() => handleDeleteChunk(chunk)}
                        className="block w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
            <p className="text-lg font-medium text-slate-800">Ontology Graph</p>
            <p className="mt-2 text-sm text-slate-500">
              Document-level ontology visualization will be implemented later.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
