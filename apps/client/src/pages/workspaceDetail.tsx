import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { FiMoreVertical, FiUpload, FiX } from 'react-icons/fi'
import toast from 'react-hot-toast'
import {
  useWorkspaceApi,
  type Workspace,
  type WorkspaceDocument,
} from '../hooks/useWorkspace'

function fileBadge(fileName: string) {
  const ext = fileName.split('.').pop()?.toUpperCase() || 'FILE'
  if (ext === 'PDF') return { label: 'PDF', className: 'bg-red-100 text-red-700' }
  if (ext === 'DOC' || ext === 'DOCX') return { label: 'DOC', className: 'bg-blue-100 text-blue-700' }
  if (ext === 'XLS' || ext === 'XLSX') return { label: 'XLS', className: 'bg-emerald-100 text-emerald-700' }
  if (ext === 'TXT') return { label: 'TXT', className: 'bg-slate-100 text-slate-700' }
  return { label: ext.slice(0, 3), className: 'bg-slate-100 text-slate-700' }
}

export default function WorkspaceDetailPage() {
  const { workspaceId } = useParams()
  const navigate = useNavigate()
  const id = Number(workspaceId)
  const { getWorkspace, listDocuments, createDocument, deleteDocument } = useWorkspaceApi()

  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [documents, setDocuments] = useState<WorkspaceDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [isIngestOpen, setIsIngestOpen] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [saving, setSaving] = useState(false)
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
    if (!Number.isFinite(id)) return
    setLoading(true)
    try {
      const [ws, docs] = await Promise.all([getWorkspace(id), listDocuments(id)])
      setWorkspace(ws)
      setDocuments(docs)
    } catch (err) {
      console.error(err)
      toast.error('Failed to load workspace')
      navigate('/dashboard/workspaces')
    } finally {
      setLoading(false)
    }
  }, [getWorkspace, listDocuments, id, navigate])

  useEffect(() => {
    load()
  }, [load])

  const documentCount = useMemo(() => workspace?.document_count ?? documents.length, [workspace, documents])

  const formatBytes = (b: number) => {
    if (b === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(b) / Math.log(k))
    return parseFloat((b / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
  }

  const handleCreateDocument = async () => {
    if (!selectedFiles.length) return toast.error('Select files')
    setSaving(true)
    try {
      for (const file of selectedFiles) {
        await createDocument(id, { file_name: file.name, file_size: formatBytes(file.size), page_count: 0, chunk_count: 0 })
      }
      toast.success('Documents uploaded')
      setIsIngestOpen(false)
      setSelectedFiles([])
      await load()
    } catch (e) {
      console.error(e)
      toast.error('Upload failed')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteDocument = async (doc: WorkspaceDocument) => {
    setMenuOpenId(null)
    if (!window.confirm(`Delete document "${doc.file_name}"?`)) return
    try {
      await deleteDocument(doc.id)
      toast.success('Document deleted')
      await load()
    } catch (err) {
      console.error(err)
      toast.error('Failed to delete document')
    }
  }


  if (loading) return <div className="min-h-full bg-gray-50 p-8">Loading workspace...</div>
  if (!workspace) return <div className="min-h-full bg-gray-50 p-8 text-slate-500">Workspace not found</div>

  return (
    <div className="min-h-full bg-gray-50">
      <header className="border-b sticky top-0 bg-white z-40">
        <div className="px-6 py-2">
          <h1 className="text-xl font-semibold text-slate-900">Workspace View</h1>
          <nav className="mt-1 text-sm text-slate-500">
            <Link to="/dashboard/workspaces" className="font-medium text-sky-600 hover:text-sky-700">
               Workspaces
            </Link>
            <span className="mx-2 text-slate-400">›</span>
            <span className="text-slate-900">{workspace.name}</span>
          </nav>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-4">
        <div className="mb-6 rounded-lg bg-slate-50 py-4">
          <div className="w-full">
            <div className="flex items-start justify-between gap-4">
              <div className="w-full">
                <h1 className="text-2xl font-bold text-slate-900">{workspace.name}</h1>
                <p className="mt-1 text-md text-slate-700">Client: {workspace.client_name}</p>
                <p className="mt-3 text-sm text-slate-600">Description: {workspace.description || 'No description provided.'}</p>
              </div>
              <div className="flex-shrink-0">
                <button
                  onClick={() => setIsIngestOpen(true)}
                  className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                >
                  <FiUpload size={16} />
                  Ingest Documents
                </button>
              </div>
            </div>

            <div className="mt-6">
              <div className="inline-flex items-center gap-3 bg-slate-100 rounded-xl p-1">
                <button className="rounded-full bg-white px-4 py-2 text-sm font-medium text-slate-900 shadow-sm">Documents ({documents.length})</button>
                <button className="rounded-full px-4 py-2 text-sm font-medium text-slate-600">Ontology Graph</button>
              </div>
            </div>
          </div>
        </div>

        <div>
          <h2 className="mb-4 text-lg font-semibold text-gray-900">Documents ({documents.length})</h2>
          {documents.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-300 bg-white p-10 text-center">
              <p className="font-medium text-gray-800">No documents uploaded yet</p>
              <p className="mt-1 text-sm text-gray-500">
                Use Ingest Documents to register files for this workspace.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {documents.map((doc) => {
                const badge = fileBadge(doc.file_name)
                return (
                  <div
                    key={doc.id}
                    className="relative flex items-center gap-4 rounded-lg border border-gray-200 bg-white px-4 py-4 shadow-sm hover:shadow-md transition"
                  >
                    <div
                      className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg text-xs font-bold ${badge.className}`}
                    >
                      {badge.label}
                    </div>
                    <div className="min-w-0 flex-1">
                      <Link
                        to={`/dashboard/workspaces/${workspace.id}/documents/${doc.id}`}
                        className="font-medium text-slate-900 hover:text-sky-600 truncate block"
                      >
                        {doc.file_name}
                      </Link>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {doc.file_size || '—'} · {doc.uploaded_at || '—'}
                      </p>
                    </div>
                    <div className="hidden sm:block text-sm text-slate-500">
                      {doc.chunk_count || 0} chunks
                    </div>
                    <button
                      data-menu-id={doc.id}
                      onClick={() => setMenuOpenId((v) => (v === doc.id ? null : doc.id))}
                      className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                    >
                      <FiMoreVertical size={16} />
                    </button>
                    {menuOpenId === doc.id && (
                      <div
                        data-menu-id={doc.id}
                        className="absolute right-4 top-12 z-10 w-40 rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
                      >
                        <button
                          onClick={() => {
                            setMenuOpenId(null)
                            navigate(`/dashboard/workspaces/${workspace.id}/documents/${doc.id}`)
                          }}
                          className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                        >
                          View
                        </button>
                        <button
                          onClick={() => handleDeleteDocument(doc)}
                          className="block w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {isIngestOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Ingest Documents</h2>
                <p className="text-xs text-slate-500">{workspace.name}</p>
              </div>
              <button
                onClick={() => setIsIngestOpen(false)}
                className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <FiX size={18} />
              </button>
            </div>

            <div className="space-y-4 px-6 py-5">
              <label
                htmlFor="file-upload"
                className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-6 py-8 text-center cursor-pointer hover:bg-gray-100 transition block"
              >
                <FiUpload className="mx-auto mb-2 text-gray-400" size={24} />
                <p className="text-sm font-medium text-gray-700">Upload documents</p>
                <p className="mt-1 text-xs text-gray-500">
                  Drag and drop files or click to select. Supported: PDF, DOCX, TXT, XLSX.
                </p>
                <input
                  type="file"
                  multiple
                  className="hidden"
                  id="file-upload"
                  onChange={(e) => {
                    if (e.target.files?.length) {
                      setSelectedFiles(Array.from(e.target.files))
                    }
                  }}
                  accept=".pdf,.docx,.doc,.txt,.xlsx,.xls"
                />
              </label>

              {selectedFiles.length > 0 && (
                <div>
                  <p className="mb-2 text-sm font-medium text-gray-700">Files to upload:</p>
                  <div className={`rounded-lg border border-gray-200 bg-gray-50 ${selectedFiles.length >= 2 ? 'max-h-24 overflow-y-auto' : ''}`}>
                    {selectedFiles.map((f, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between border-b border-gray-200 px-4 py-3 last:border-b-0"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-gray-800">{f.name}</p>
                          <p className="text-xs text-gray-500">{formatBytes(f.size)}</p>
                        </div>
                        <button
                          onClick={() => setSelectedFiles((prev) => prev.filter((_, idx) => idx !== i))}
                          className="ml-2 rounded p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-700"
                        >
                          <FiX size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between border-t border-gray-200 px-6 py-4">
              <span className="text-sm text-gray-600">{selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected</span>
              <div className="flex gap-2">
                <button
                  onClick={() => {
                    setIsIngestOpen(false)
                    setSelectedFiles([])
                  }}
                  className="rounded-lg px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateDocument}
                  disabled={saving || !selectedFiles.length}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {saving ? 'Uploading...' : 'Upload'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
