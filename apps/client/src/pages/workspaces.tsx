import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FiMoreVertical, FiPlus, FiSearch, FiX } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { useWorkspaceApi, type Workspace } from '../hooks/useWorkspace'

const PRESET_TAGS = [
  'Payments',
  'Digital Banking',
  'AI',
  'Cloud',
  'Cybersecurity',
  'Lending',
  'Risk',
  'Compliance',
  'Data',
  'Automation',
  'Customer Experience',
]

export default function WorkspacesPage() {
  const navigate = useNavigate()
  const { listWorkspaces, createWorkspace, updateWorkspace, deleteWorkspace } = useWorkspaceApi()

  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [isFilterOpen, setIsFilterOpen] = useState(false)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null)

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(null)

  const [name, setName] = useState('')
  const [clientName, setClientName] = useState('')
  const [description, setDescription] = useState('')
  const [formTags, setFormTags] = useState<string[]>([])
  const [editName, setEditName] = useState('')
  const [addingCustomTag, setAddingCustomTag] = useState(false)
  const [customTag, setCustomTag] = useState('')
  const [saving, setSaving] = useState(false)

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

  const loadWorkspaces = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listWorkspaces(
        search.trim() || undefined,
        selectedTags.length ? selectedTags : undefined,
      )
      setWorkspaces(data)
    } catch (err) {
      console.error(err)
      toast.error('Failed to load workspaces')
    } finally {
      setLoading(false)
    }
  }, [listWorkspaces, search, selectedTags])

  useEffect(() => {
    const timer = setTimeout(() => {
      loadWorkspaces()
    }, 250)
    return () => clearTimeout(timer)
  }, [loadWorkspaces])

  const availableFilterTags = useMemo(() => {
    const fromData = workspaces.flatMap((w) => w.tags || [])
    return Array.from(new Set([...PRESET_TAGS, ...fromData])).sort()
  }, [workspaces])

  const allSelectableTags = useMemo(() => {
    return Array.from(new Set([...PRESET_TAGS, ...formTags]))
  }, [formTags])

  const toggleFormTag = (tag: string) => {
    setFormTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]))
  }

  const addCustomTag = () => {
    const value = customTag.trim()
    if (!value) return
    if (!formTags.includes(value)) setFormTags((prev) => [...prev, value])
    setCustomTag('')
    setAddingCustomTag(false)
  }

  const resetCreateForm = () => {
    setName('')
    setClientName('')
    setDescription('')
    setFormTags([])
    setCustomTag('')
    setAddingCustomTag(false)
  }

  const openEditModal = (workspace: Workspace) => {
    setActiveWorkspace(workspace)
    setEditName(workspace.name)
    setMenuOpenId(null)
    setIsEditOpen(true)
  }

  const openDeleteModal = (workspace: Workspace) => {
    setActiveWorkspace(workspace)
    setMenuOpenId(null)
    setIsDeleteOpen(true)
  }

  const handleCreate = async () => {
    if (!name.trim() || !clientName.trim()) {
      toast.error('Workspace name and client name are required')
      return
    }
    setSaving(true)
    try {
      const created = await createWorkspace({
        name: name.trim(),
        client_name: clientName.trim(),
        tags: formTags,
        description: description.trim(),
      })
      toast.success('Workspace created')
      setIsCreateOpen(false)
      resetCreateForm()
      await loadWorkspaces()
      navigate(`/dashboard/workspaces/${created.id}`)
    } catch (err) {
      console.error(err)
      toast.error('Failed to create workspace')
    } finally {
      setSaving(false)
    }
  }

  const handleEdit = async () => {
    if (!activeWorkspace || !editName.trim()) {
      toast.error('Workspace name is required')
      return
    }
    setSaving(true)
    try {
      await updateWorkspace(activeWorkspace.id, { name: editName.trim() })
      toast.success('Workspace updated')
      setIsEditOpen(false)
      setActiveWorkspace(null)
      await loadWorkspaces()
    } catch (err) {
      console.error(err)
      toast.error('Failed to update workspace')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!activeWorkspace) return
    setSaving(true)
    try {
      await deleteWorkspace(activeWorkspace.id)
      toast.success('Workspace deleted')
      setIsDeleteOpen(false)
      setActiveWorkspace(null)
      await loadWorkspaces()
    } catch (err) {
      console.error(err)
      toast.error('Failed to delete workspace')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-full bg-gray-50">
      <header className="border-b sticky top-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-50">
        <div className="px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h1 className="text-xl font-semibold">Workspaces</h1>
              <p className="text-xs text-muted-foreground">
                Organize client engagements, documents, and ontology graphs.
              </p>
            </div>
            <button
              onClick={() => setIsCreateOpen(true)}
              className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 whitespace-nowrap"
            >
              <FiPlus size={16} />
              Create Workspace
            </button>
          </div>
        </div>
      </header>

      <div className="px-6 py-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="relative w-full max-w-md">
            <FiSearch className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search workspaces..."
              className="w-full rounded-md border border-gray-200 bg-white py-2 pl-10 pr-3 text-sm text-gray-800 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          <button
            onClick={() => setIsFilterOpen(true)}
            className={`inline-flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium ${
              selectedTags.length
                ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
                : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
            }`}
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="6" cy="6" r="3"/>
              <line x1="9" y1="6" x2="21" y2="6"/>
              <circle cx="18" cy="12" r="3"/>
              <line x1="3" y1="12" x2="15" y2="12"/>
              <circle cx="6" cy="18" r="3"/>
              <line x1="9" y1="18" x2="21" y2="18"/>
            </svg>
            Filter
          </button>
        </div>

        {selectedTags.length > 0 && (
          <div className="mb-6 flex flex-wrap items-center gap-2 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3">
            <span className="text-sm text-slate-600">Filtered by:</span>
            {selectedTags.map((tag) => (
              <span key={tag} className="rounded-full bg-indigo-100 px-3 py-1 text-xs font-medium text-indigo-700">
                {tag}
              </span>
            ))}
            <button
              onClick={() => setSelectedTags([])}
              className="ml-auto text-xs font-semibold text-indigo-700 hover:text-indigo-900"
            >
              Clear all
            </button>
          </div>
        )}

        {loading ? (
          <div className="rounded-lg border border-gray-200 p-10 text-center text-gray-500">
            Loading workspaces...
          </div>
        ) : workspaces.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-300 p-12 text-center">
            <p className="text-lg font-medium text-gray-800">No workspaces yet</p>
            <p className="mt-1 text-sm text-gray-500">Create a workspace to start uploading documents.</p>
            <button
              onClick={() => setIsCreateOpen(true)}
              className="mt-4 inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              <FiPlus size={16} />
              New Workspace
            </button>
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {workspaces.map((workspace) => (
              <div
                key={workspace.id}
                role="button"
                tabIndex={0}
                onClick={() => navigate(`/dashboard/workspaces/${workspace.id}`)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    navigate(`/dashboard/workspaces/${workspace.id}`)
                  }
                }}
                className="relative cursor-pointer rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:border-gray-300 hover:shadow-md"
              >
                <div className="mb-3 flex items-start justify-between gap-3">
                  <h3 className="text-lg font-semibold text-gray-900">{workspace.name}</h3>
                  <button
                    data-menu-id={workspace.id}
                    onClick={(e) => {
                      e.stopPropagation()
                      setMenuOpenId((id) => (id === workspace.id ? null : workspace.id))
                    }}
                    className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                  >
                    <FiMoreVertical size={16} />
                  </button>
                </div>

                {menuOpenId === workspace.id && (
                  <div
                    data-menu-id={workspace.id}
                    className="absolute right-4 top-12 z-10 w-40 rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => openEditModal(workspace)}
                      className="block w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                    >
                      Edit name
                    </button>
                    <button
                      onClick={() => openDeleteModal(workspace)}
                      className="block w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>
                )}

                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-700">
                  Client: {workspace.client_name}
                </p>
                <p className="mb-4 line-clamp-3 min-h-[3.75rem] text-sm leading-relaxed text-gray-600">
                  {workspace.description || 'No description provided.'}
                </p>
                {workspace.tags?.length > 0 && (
                  <div className="mb-4 flex flex-wrap gap-1.5">
                    {workspace.tags.slice(0, 4).map((tag) => (
                      <span key={tag} className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-700">
                        {tag}
                      </span>
                    ))}
                    {workspace.tags.length > 4 && (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                        +{workspace.tags.length - 4}
                      </span>
                    )}
                  </div>
                )}
                <div className="flex items-center justify-between border-t border-gray-100 pt-3 text-xs text-gray-500">
                  <span>{workspace.document_count} docs</span>
                  <span>Created: {workspace.created_at || '—'}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {isFilterOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-xl rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Filter workspaces</h2>
                <p className="text-sm text-gray-500">Select tags to narrow the workspace list.</p>
              </div>
              <button
                onClick={() => setIsFilterOpen(false)}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <FiX size={18} />
              </button>
            </div>
            <div className="space-y-4 px-6 py-5">
              <div className="flex flex-wrap gap-2">
                {availableFilterTags.map((tag) => {
                  const active = selectedTags.includes(tag)
                  return (
                    <button
                      key={tag}
                      type="button"
                      onClick={() =>
                        setSelectedTags((prev) =>
                          active ? prev.filter((t) => t !== tag) : [...prev, tag],
                        )
                      }
                      className={`rounded-full border px-3 py-2 text-sm font-medium ${
                        active
                          ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                          : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      {tag}
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="flex items-center justify-between border-t border-gray-200 px-6 py-4">
              <button
                onClick={() => {
                  setSelectedTags([])
                  setIsFilterOpen(false)
                }}
                className="rounded-md px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
              >
                Clear all
              </button>
              <button
                onClick={() => setIsFilterOpen(false)}
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
              >
                Apply filters
              </button>
            </div>
          </div>
        </div>
      )}

      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-xl rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">New Workspace</h2>
              <button
                onClick={() => {
                  setIsCreateOpen(false)
                  resetCreateForm()
                }}
                className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
              >
                <FiX size={18} />
              </button>
            </div>

            <div className="space-y-4 px-6 py-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    Workspace Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Core Banking Modernization"
                    className="w-full rounded-md border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                  />
                </div>

                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    Client Name <span className="text-red-500">*</span>
                  </label>
                  <input
                    value={clientName}
                    onChange={(e) => setClientName(e.target.value)}
                    placeholder="e.g. First National Bank"
                    className="w-full rounded-md border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                  />
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">
                  Tags <span className="font-normal text-gray-400">(Optional)</span>
                </label>
                <div className="flex flex-wrap items-center gap-2">
                  {allSelectableTags.map((tag) => {
                    const active = formTags.includes(tag)
                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => toggleFormTag(tag)}
                        className={`rounded-full border px-3 py-1 text-xs font-medium ${
                          active
                            ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                            : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                        }`}
                      >
                        {tag}
                      </button>
                    )
                  })}
                  {addingCustomTag ? (
                    <div className="inline-flex items-center gap-1">
                      <input
                        autoFocus
                        value={customTag}
                        onChange={(e) => setCustomTag(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            addCustomTag()
                          }
                          if (e.key === 'Escape') {
                            setAddingCustomTag(false)
                            setCustomTag('')
                          }
                        }}
                        placeholder="New tag"
                        className="w-28 rounded-full border border-indigo-300 px-3 py-1 text-xs outline-none focus:ring-2 focus:ring-indigo-100"
                      />
                      <button
                        type="button"
                        onClick={addCustomTag}
                        className="rounded-full bg-indigo-600 px-2 py-1 text-xs text-white hover:bg-indigo-700"
                      >
                        Add
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setAddingCustomTag(true)}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-dashed border-gray-300 text-gray-500 hover:border-indigo-400 hover:text-indigo-600"
                      title="Add custom tag"
                    >
                      <FiPlus size={14} />
                    </button>
                  )}
                </div>
              </div>

              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700">
                  Description <span className="font-normal text-gray-400">(Optional)</span>
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={4}
                  placeholder="Scope and purpose of this workspace..."
                  className="w-full rounded-md border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                />
              </div>
            </div>

            <div className="flex items-center justify-between border-t border-gray-200 px-6 py-4">
              <button
                onClick={() => {
                  setIsCreateOpen(false)
                  resetCreateForm()
                }}
                className="text-sm font-medium text-gray-600 hover:text-gray-900"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={saving}
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? 'Creating...' : 'Create Workspace'}
              </button>
            </div>
          </div>
        </div>
      )}

      {isEditOpen && activeWorkspace && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">Edit workspace name</h2>
              <button
                onClick={() => {
                  setIsEditOpen(false)
                  setActiveWorkspace(null)
                }}
                className="rounded p-1 text-gray-400 hover:bg-gray-100"
              >
                <FiX size={18} />
              </button>
            </div>
            <div className="px-6 py-5">
              <label className="mb-1 block text-sm font-medium text-gray-700">Workspace Name</label>
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="w-full rounded-md border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
              />
            </div>
            <div className="flex justify-end gap-2 border-t border-gray-200 px-6 py-4">
              <button
                onClick={() => {
                  setIsEditOpen(false)
                  setActiveWorkspace(null)
                }}
                className="rounded-md px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                onClick={handleEdit}
                disabled={saving}
                className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {isDeleteOpen && activeWorkspace && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-lg bg-white shadow-xl">
            <div className="border-b border-gray-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-gray-900">Delete workspace</h2>
            </div>
            <div className="px-6 py-5">
              <p className="text-sm text-gray-600">
                Are you sure you want to delete{' '}
                <span className="font-semibold text-gray-900">{activeWorkspace.name}</span>? This will also
                remove its documents and chunks. This action cannot be undone.
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-gray-200 px-6 py-4">
              <button
                onClick={() => {
                  setIsDeleteOpen(false)
                  setActiveWorkspace(null)
                }}
                className="rounded-md px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={saving}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {saving ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
