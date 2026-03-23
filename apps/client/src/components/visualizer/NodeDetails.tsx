import { useState } from 'react'

interface NodeDetailsProps {
  selectedNode: {
    id: string
    label: string
    properties: Record<string, unknown>
    path?: Array<{ name: string; type: string }>
  } | null
  onClose: () => void
  loading?: boolean
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(formatValue).join(', ')
  return JSON.stringify(value, null, 2)
}

function formatPropertyName(key: string): string {
  return key.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase()).replace(/_/g, ' ').trim()
}

export default function NodeDetails({ selectedNode, onClose, loading = false }: NodeDetailsProps) {
  const [isCollapsed, setIsCollapsed] = useState(false)
  if (!selectedNode) return null

  const displayableProps = Object.entries(selectedNode.properties).filter(
    ([key, value]) => value !== null && value !== undefined && value !== '' && !['captions', 'color', 'size'].includes(key)
  )

  return (
    <div className={`node-details ${isCollapsed ? 'collapsed' : ''}`}>
      <div className="node-details-header">
        <button className="collapse-btn" onClick={() => setIsCollapsed(!isCollapsed)} title={isCollapsed ? 'Expand' : 'Collapse'}>
          {isCollapsed ? '◀' : '▶'}
        </button>
        {!isCollapsed && (
          <>
            <div className="header-content">
              <h3>{selectedNode.label}</h3>
              {selectedNode.path && selectedNode.path.length > 0 && (
                <div className="node-path">
                  {[...selectedNode.path].reverse().map((node, index) => (
                    <span key={index} className="path-item">
                      {index > 0 && <span className="path-separator">&gt;</span>}
                      <span className="path-node">
                        <span className="path-type">{node.type}</span>
                        <span className="path-name">{node.name}</span>
                      </span>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button className="close-btn" onClick={onClose}>&times;</button>
          </>
        )}
      </div>
      {!isCollapsed && (
        <div className="node-details-content">
          {loading && <div className="property-loading"><span className="loading-spinner-small"></span>Loading properties...</div>}
          {displayableProps.map(([key, value]) => (
            <div key={key} className="property-row">
              <span className="property-key">{formatPropertyName(key)}:</span>
              <span className="property-value">{formatValue(value)}</span>
            </div>
          ))}
          {!loading && displayableProps.length === 0 && <div className="no-properties">No properties available</div>}
        </div>
      )}
    </div>
  )
}
