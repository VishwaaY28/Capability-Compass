import type { EntityType, EntityListItem } from './types'
import { truncateLabel } from './utils/truncateLabel'

interface EntitySelectorProps {
  entityType: EntityType
  setEntityType: (type: EntityType) => void
  entities: EntityListItem[]
  selectedEntityId: number | null
  setSelectedEntityId: (id: number | null) => void
  loading: boolean
}

const ENTITY_TYPES: { value: EntityType; label: string }[] = [
  { value: 'Capability',        label: 'Capabilities' },
  { value: 'Process',           label: 'Processes' },
  { value: 'Subprocess',        label: 'Subprocesses' },
  { value: 'DataEntity',        label: 'Data Entities' },
  { value: 'DataElement',       label: 'Data Elements' },
  { value: 'OrgUnit',           label: 'Org Units' },
  { value: 'ApplicationCatalog', label: 'Applications' },
]

// Maps frontend EntityType to the slug the backend subtree router expects
export const ENTITY_TYPE_SLUG: Record<EntityType, string> = {
  Capability:         'capability',
  Process:            'process',
  Subprocess:         'subprocess',
  DataEntity:         'dataentity',
  DataElement:        'dataelement',
  OrgUnit:            'orgunits',
  ApplicationCatalog: 'applicationcatalog',
}

export default function EntitySelector({
  entityType, setEntityType, entities, selectedEntityId, setSelectedEntityId, loading,
}: EntitySelectorProps) {
  return (
    <div className="entity-selector">
      <div className="selector-group">
        <label>Entity Type:</label>
        <select value={entityType} onChange={(e) => { setEntityType(e.target.value as EntityType); setSelectedEntityId(null) }}>
          {ENTITY_TYPES.map((type) => (
            <option key={type.value} value={type.value}>{type.label}</option>
          ))}
        </select>
      </div>
      <div className="selector-group">
        <label>{entityType}:</label>
        <select
          className="entity-select-dropdown"
          value={selectedEntityId ?? ''}
          onChange={(e) => setSelectedEntityId(e.target.value ? Number(e.target.value) : null)}
          disabled={loading || entities.length === 0}
          title={entities.find(e => e.uid === selectedEntityId)?.name}
        >
          <option value="">-- Select --</option>
          {entities.map((entity) => (
            <option key={entity.uid} value={entity.uid} title={entity.name}>
              {truncateLabel(entity.name)}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
