import React, { useState, useEffect, useRef, useCallback } from 'react'
import type NVL from '@neo4j-nvl/base'
import type { Node, Relationship, HitTargets } from '@neo4j-nvl/base'
import { InteractiveNvlWrapper } from '@neo4j-nvl/react'
import type { MouseEventCallbacks } from '@neo4j-nvl/react'
import PmoEntitySelector from './PmoEntitySelector'
import ControlPanel from './ControlPanel'
import NodeDetails from './NodeDetails'
import { transformPmoApiResponseToNvl } from './utils/pmoTransformer'
import type { PmoTraversalNode, PmoTraversalRelationship } from './utils/pmoTransformer'
import type { PmoFlatGraphResponse, PmoEntityListItem, Direction } from './pmoTypes'
import { PMO_LEGEND_ITEMS } from './pmoTypes'
import { runGraphAnimation, filterValidRelationships } from './utils/graphAnimation'

const API_BASE = '/api/pmo'
const PATH_HIGHLIGHT_COLOR = '#1976D2'
const PATH_STROKE_WIDTH = 3
const NORMAL_STROKE_WIDTH = 1.5
const MIN_ZOOM = 0.5
const MAX_ZOOM = 3.0
const ZOOM_STEP = 0.25
const DEFAULT_ZOOM = 1.0

const PmoVisualizerSection: React.FC = () => {
  const nvlRef = useRef<NVL | null>(null)
  const [labels, setLabels] = useState<string[]>([])
  const [entityType, setEntityType] = useState<string>('')
  const [entities, setEntities] = useState<PmoEntityListItem[]>([])
  const [selectedEntityUri, setSelectedEntityUri] = useState<string | null>(null)
  const [depth, setDepth] = useState(1)
  const [direction, setDirection] = useState<Direction>('outgoing')
  const [cypherQuery, setCypherQuery] = useState('')
  const [allNodes, setAllNodes] = useState<PmoTraversalNode[]>([])
  const [allRels, setAllRels] = useState<PmoTraversalRelationship[]>([])
  const [visibleNodes, setVisibleNodes] = useState<Node[]>([])
  const [visibleRels, setVisibleRels] = useState<Relationship[]>([])
  const [totalLoadedNodes, setTotalLoadedNodes] = useState(0)
  const [loading, setLoading] = useState(false)
  const [animating, setAnimating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<{ id: string; label: string; properties: Record<string, unknown>; path?: Array<{ name: string; type: string }> } | null>(null)
  const [parentMap, setParentMap] = useState<Map<string, string>>(new Map())
  const [currentZoom, setCurrentZoom] = useState(DEFAULT_ZOOM)
  const animationRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { fetchLabels() }, [])
  useEffect(() => {
    if (entityType) fetchEntities()
  }, [entityType])
  useEffect(() => {
    if (selectedEntityUri !== null) fetchSubtree()
  }, [selectedEntityUri, depth, direction])
  useEffect(() => () => { if (animationRef.current) clearTimeout(animationRef.current) }, [])

  const applyGraphData = useCallback((data: PmoFlatGraphResponse) => {
    const { nodes: nvlNodes, rels: nvlRels, parentMap: newParentMap } = transformPmoApiResponseToNvl(data)
    setAllNodes(nvlNodes)
    setAllRels(nvlRels)
    setTotalLoadedNodes(nvlNodes.length)
    setParentMap(newParentMap)
    runGraphAnimation(nvlNodes, nvlRels, animationRef, {
      setVisibleNodes,
      setVisibleRels,
      setAnimating,
      onComplete: () => {
        setTimeout(() => {
          if (nvlRef.current && nvlNodes.length > 0) nvlRef.current.fit(nvlNodes.map(n => n.id))
        }, 200)
      },
    })
  }, [])

  async function fetchLabels() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/labels`)
      if (!res.ok) throw new Error('Failed to fetch PMO labels')
      const data: string[] = await res.json()
      setLabels(data)
      if (data.length > 0) setEntityType(data[0])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  async function fetchEntities() {
    if (!entityType) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/subtree/${encodeURIComponent(entityType)}/all`)
      if (!res.ok) throw new Error('Failed to fetch PMO entities')
      setEntities(await res.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  async function fetchSubtree() {
    if (selectedEntityUri === null || !entityType) return
    setLoading(true)
    setError(null)
    try {
      const depthParam = depth > 0 ? `&depth=${depth}` : ''
      const uriParam = encodeURIComponent(selectedEntityUri)
      const res = await fetch(
        `${API_BASE}/subtree/${encodeURIComponent(entityType)}/uri?uri=${uriParam}&direction=${direction}${depthParam}`
      )
      if (!res.ok) throw new Error('Failed to fetch PMO subtree')
      const data: PmoFlatGraphResponse = await res.json()
      applyGraphData(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  async function executeCypherQuery() {
    if (!cypherQuery.trim()) return
    setLoading(true)
    setError(null)
    setSelectedEntityUri(null)
    try {
      const res = await fetch(`${API_BASE}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: cypherQuery }),
      })
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}))
        throw new Error((errBody as { detail?: string }).detail || 'Failed to execute query')
      }
      const data: PmoFlatGraphResponse = await res.json()
      applyGraphData(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const computePathToRoot = useCallback((nodeId: string) => {
    const pathEdges = new Set<string>()
    const pathDetails: Array<{ name: string; type: string }> = []
    let currentId: string | undefined = nodeId
    while (currentId) {
      const currentNode = allNodes.find(n => n.id === currentId)
      if (currentNode) pathDetails.push({ name: currentNode.captions?.[0]?.value || 'Unknown', type: currentNode.label || 'Node' })
      const parentId = parentMap.get(currentId)
      if (parentId) {
        const edge = allRels.find(r => (r.from === parentId && r.to === currentId) || (r.from === currentId && r.to === parentId))
        if (edge) pathEdges.add(edge.id)
      }
      currentId = parentId
    }
    return { pathEdges, pathDetails }
  }, [parentMap, allRels, allNodes])

  const clearPathHighlight = useCallback(() => {
    setVisibleRels(prev => prev.map(rel => ({ ...rel, color: '#000000', width: NORMAL_STROKE_WIDTH })))
  }, [])

  const highlightPathToNode = useCallback((nodeId: string) => {
    const { pathEdges, pathDetails } = computePathToRoot(nodeId)
    setVisibleRels(prev => prev.map(rel => ({
      ...rel,
      color: pathEdges.has(rel.id) ? PATH_HIGHLIGHT_COLOR : '#000000',
      width: pathEdges.has(rel.id) ? PATH_STROKE_WIDTH : NORMAL_STROKE_WIDTH,
    })))
    return pathDetails
  }, [computePathToRoot])

  const skipAnimation = () => {
    if (animationRef.current) clearTimeout(animationRef.current)
    const nodeIds = new Set(allNodes.map(n => String(n.id)))
    const validRels = filterValidRelationships(allRels, nodeIds)
    setVisibleNodes(allNodes.map(n => ({ id: n.id, captions: n.captions, color: n.color, size: n.size, x: n.x, y: n.y })))
    setVisibleRels(validRels.map(r => ({ id: r.id, from: r.from, to: r.to, captions: r.captions, color: '#000000' })))
    setAnimating(false)
    setTimeout(() => { if (nvlRef.current && allNodes.length > 0) nvlRef.current.fit(allNodes.map(n => n.id)) }, 100)
  }

  const zoomIn = useCallback(() => {
    if (nvlRef.current && currentZoom < MAX_ZOOM) { const z = Math.min(currentZoom + ZOOM_STEP, MAX_ZOOM); nvlRef.current.setZoom(z); setCurrentZoom(z) }
  }, [currentZoom])

  const zoomOut = useCallback(() => {
    if (nvlRef.current && currentZoom > MIN_ZOOM) { const z = Math.max(currentZoom - ZOOM_STEP, MIN_ZOOM); nvlRef.current.setZoom(z); setCurrentZoom(z) }
  }, [currentZoom])

  const resetZoom = useCallback(() => { if (nvlRef.current) { nvlRef.current.setZoom(DEFAULT_ZOOM); setCurrentZoom(DEFAULT_ZOOM) } }, [])

  const fitToView = useCallback(() => {
    if (nvlRef.current && visibleNodes.length > 0) {
      nvlRef.current.fit(visibleNodes.map(n => n.id))
      setTimeout(() => { if (nvlRef.current) setCurrentZoom(Math.max(MIN_ZOOM, Math.min(nvlRef.current.getScale(), MAX_ZOOM))) }, 100)
    }
  }, [visibleNodes])

  const handleNodeClick = (node: Node, _hitTargets: HitTargets, originalEvent: MouseEvent) => {
    originalEvent.stopPropagation()
    const fullNode = allNodes.find(n => n.id === node.id)
    const pathDetails = highlightPathToNode(node.id)
    setSelectedNode({
      id: node.id,
      label: fullNode?.label || node.captions?.[0]?.value || 'Node',
      properties: fullNode?.properties || {},
      path: pathDetails,
    })
  }

  const mouseEventCallbacks: MouseEventCallbacks = {
    onHover: () => {},
    onNodeClick: handleNodeClick,
    onNodeDoubleClick: () => {},
    onRelationshipClick: () => {},
    onDrag: () => {},
    onPan: () => {},
    onZoom: (zoomLevel: number) => setCurrentZoom(Math.max(MIN_ZOOM, Math.min(zoomLevel, MAX_ZOOM))),
    onCanvasClick: () => clearPathHighlight(),
  }

  return (
    <>
      <div className="app-controls">
        <PmoEntitySelector
          labels={labels}
          entityType={entityType}
          setEntityType={setEntityType}
          entities={entities}
          selectedEntityUri={selectedEntityUri}
          setSelectedEntityUri={setSelectedEntityUri}
          loading={loading}
        />
        <ControlPanel depth={depth} setDepth={setDepth} direction={direction} setDirection={setDirection} />
        <div className="selector-group pmo-query-group">
          <label>Query:</label>
          <input
            type="text"
            className="pmo-query-input"
            value={cypherQuery}
            onChange={(e) => setCypherQuery(e.target.value)}
            placeholder="MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50"
            onKeyDown={(e) => { if (e.key === 'Enter') executeCypherQuery() }}
          />
          <button className="pmo-query-btn" onClick={executeCypherQuery} disabled={loading || !cypherQuery.trim()}>
            Execute
          </button>
        </div>
        {animating && <button className="skip-animation-btn" onClick={skipAnimation}>Skip Animation</button>}
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="app-main">
        {totalLoadedNodes > 0 && (
          <div className="node-counter">
            <span className="counter-label">Number of Nodes:</span>
            <span className="counter-value">{totalLoadedNodes}</span>
          </div>
        )}
        <div className="zoom-controls">
          <button className="zoom-btn" onClick={zoomIn} disabled={currentZoom >= MAX_ZOOM || visibleNodes.length === 0} aria-label="Zoom In">+</button>
          <button className="zoom-btn" onClick={zoomOut} disabled={currentZoom <= MIN_ZOOM || visibleNodes.length === 0} aria-label="Zoom Out">−</button>
          <button className="zoom-btn zoom-btn-text" onClick={resetZoom} disabled={visibleNodes.length === 0} aria-label="Reset Zoom">Reset</button>
          <button className="zoom-btn zoom-btn-text" onClick={fitToView} disabled={visibleNodes.length === 0} aria-label="Fit to View">Fit</button>
          <span className="zoom-level">{Math.round(currentZoom * 100)}%</span>
        </div>

        <div className="graph-container" onClick={(e) => { if (e.target === e.currentTarget) clearPathHighlight() }}>
          {loading && <div className="loading-overlay"><div className="spinner"></div></div>}
          {animating && <div className="animation-indicator">Traversing path... ({visibleNodes.length}/{allNodes.length} nodes)</div>}
          {visibleNodes.length > 0 ? (
            <div className="graph-wrapper">
              <InteractiveNvlWrapper
                ref={nvlRef}
                style={{ borderRadius: 10, border: '2px solid #D5D6D8', height: '100%', width: '100%', minHeight: '600px', minWidth: '800px', background: '#ffffff' }}
                nodes={visibleNodes}
                rels={visibleRels}
                mouseEventCallbacks={mouseEventCallbacks}
                layout="forceDirected"
                nvlOptions={{ initialZoom: 1, relationshipThreshold: 0, minZoom: 0.1, maxZoom: 10 }}
              />
            </div>
          ) : (
            !loading && selectedEntityUri === null && totalLoadedNodes === 0 && (
              <div className="empty-state"><p>Select an entity type and item, or run a Cypher query to visualize</p></div>
            )
          )}
        </div>

        <NodeDetails selectedNode={selectedNode} onClose={() => setSelectedNode(null)} />
      </div>

      <div className="legend">
        {PMO_LEGEND_ITEMS.map((item) => (
          <span key={item.label} className="legend-item">
            <span className={`dot ${item.className}`} style={{ backgroundColor: item.color }}></span>
            {item.label}
          </span>
        ))}
      </div>
    </>
  )
}

export default PmoVisualizerSection
