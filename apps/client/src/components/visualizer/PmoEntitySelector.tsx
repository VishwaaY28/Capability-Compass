import type { PmoEntityListItem } from './pmoTypes'
import { truncateLabel } from './utils/truncateLabel'

interface PmoEntitySelectorProps {
  labels: string[]
  entityType: string
  setEntityType: (type: string) => void
  entities: PmoEntityListItem[]
  selectedEntityUri: string | null
  setSelectedEntityUri: (uri: string | null) => void
  loading: boolean
}

export default function PmoEntitySelector({
  labels,
  entityType,
  setEntityType,
  entities,
  selectedEntityUri,
  setSelectedEntityUri,
  loading,
}: PmoEntitySelectorProps) {
  const selectedEntity = entities.find(e => e.uri === selectedEntityUri)

  return (
    <div className="entity-selector">
      <div className="selector-group">
        <label>Entity Type:</label>
        <select
          value={entityType}
          onChange={(e) => {
            setEntityType(e.target.value)
            setSelectedEntityUri(null)
          }}
          disabled={labels.length === 0}
        >
          {labels.map((label) => (
            <option key={label} value={label}>{label}</option>
          ))}
        </select>
      </div>
      <div className="selector-group">
        <label>{entityType}:</label>
        <select
          className="entity-select-dropdown"
          value={selectedEntityUri ?? ''}
          onChange={(e) => setSelectedEntityUri(e.target.value || null)}
          disabled={loading || entities.length === 0}
          title={selectedEntity?.name || selectedEntityUri || undefined}
        >
          <option value="">-- Select --</option>
          {entities.map((entity) => (
            <option key={entity.uri} value={entity.uri} title={entity.name}>
              {truncateLabel(entity.name)}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
