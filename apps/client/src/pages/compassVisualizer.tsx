import React, { useState, useEffect, useRef, useCallback } from 'react'
import type NVL from '@neo4j-nvl/base'
import type { Node, Relationship, HitTargets } from '@neo4j-nvl/base'
import { InteractiveNvlWrapper } from '@neo4j-nvl/react'
import type { MouseEventCallbacks } from '@neo4j-nvl/react'
import EntitySelector, { ENTITY_TYPE_SLUG } from '../components/visualizer/EntitySelector'
import ControlPanel from '../components/visualizer/ControlPanel'
import NodeDetails from '../components/visualizer/NodeDetails'
import { transformApiResponseToNvl } from '../components/visualizer/utils/transformer'
import type { TraversalNode, TraversalRelationship } from '../components/visualizer/utils/transformer'
import type { EntityType, EntityListItem, Direction, ApiResponse } from '../components/visualizer/types'
import '../components/visualizer/visualizer.css'

const API_BASE = '/api'
const ANIMATION_DELAY = 80
const ANIMATION_BATCH_SIZE = 5   // nodes revealed per tick
const ANIMATION_NODE_LIMIT = 80  // skip animation above this count
const PATH_HIGHLIGHT_COLOR = '#1976D2'
const PATH_STROKE_WIDTH = 3
const NORMAL_STROKE_WIDTH = 1.5
const MIN_ZOOM = 0.5
const MAX_ZOOM = 3.0
const ZOOM_STEP = 0.25
const DEFAULT_ZOOM = 1.0

const CompassVisualizer: React.FC = () => {
  const nvlRef = useRef<NVL | null>(null)
  const [entityType, setEntityType] = useState<EntityType>('Capability')
  const [entities, setEntities] = useState<EntityListItem[]>([])
  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null)
  const [depth, setDepth] = useState(1)
  const [direction, setDirection] = useState<Direction>('outgoing')
  const [allNodes, setAllNodes] = useState<TraversalNode[]>([])
  const [allRels, setAllRels] = useState<TraversalRelationship[]>([])
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

  useEffect(() => { fetchEntities() }, [entityType])
  useEffect(() => { if (selectedEntityId !== null) fetchSubtree() }, [selectedEntityId, depth, direction])
  useEffect(() => () => { if (animationRef.current) clearTimeout(animationRef.current) }, [])

  const animateTraversal = useCallback((nodes: TraversalNode[], rels: TraversalRelationship[]) => {
    if (animationRef.current) clearTimeout(animationRef.current)

    const allNvlNodes = nodes.map(n => ({ id: n.id, captions: n.captions, color: n.color, size: n.size, x: n.x, y: n.y }))
    const allNvlRels = rels.map(r => ({ id: r.id, from: r.from, to: r.to, captions: r.captions, color: '#000000' }))

    // Skip animation for large graphs to avoid crashing
    if (nodes.length > ANIMATION_NODE_LIMIT) {
      setVisibleNodes(allNvlNodes)
      setVisibleRels(allNvlRels)
      setAnimating(false)
      setTimeout(() => { if (nvlRef.current && nodes.length > 0) nvlRef.current.fit(nodes.map(n => n.id)) }, 200)
      return
    }

    setVisibleNodes([])
    setVisibleRels([])
    setAnimating(true)

    const sortedNodes = [...nodes].sort((a, b) => a.traversalOrder - b.traversalOrder)
    const sortedRels = [...rels].sort((a, b) => a.traversalOrder - b.traversalOrder)
    let nodeIndex = 0
    let relIndex = 0

    const animate = () => {
      if (nodeIndex >= sortedNodes.length) {
        // Flush any remaining rels
        if (relIndex < sortedRels.length) {
          const remaining = sortedRels.slice(relIndex).map(r => ({ id: r.id, from: r.from, to: r.to, captions: r.captions, color: '#000000' }))
          setVisibleRels(prev => [...prev, ...remaining])
        }
        setAnimating(false)
        setTimeout(() => { if (nvlRef.current && nodes.length > 0) nvlRef.current.fit(nodes.map(n => n.id)) }, 200)
        return
      }

      // Reveal a batch of nodes at once
      const batchEnd = Math.min(nodeIndex + ANIMATION_BATCH_SIZE, sortedNodes.length)
      const batchNodes = sortedNodes.slice(nodeIndex, batchEnd)
      const maxOrderInBatch = batchNodes[batchNodes.length - 1].traversalOrder

      const newNvlNodes = batchNodes.map(n => ({ id: n.id, captions: n.captions, color: n.color, size: n.size, x: n.x, y: n.y }))

      // Collect rels whose target is within this batch
      const newNvlRels: Relationship[] = []
      while (relIndex < sortedRels.length) {
        const rel = sortedRels[relIndex]
        const targetOrder = sortedNodes.find(n => n.id === rel.to)?.traversalOrder ?? Infinity
        if (targetOrder <= maxOrderInBatch) {
          newNvlRels.push({ id: rel.id, from: rel.from, to: rel.to, captions: rel.captions, color: '#000000' })
          relIndex++
        } else break
      }

      setVisibleNodes(prev => [...prev, ...newNvlNodes])
      if (newNvlRels.length > 0) setVisibleRels(prev => [...prev, ...newNvlRels])

      nodeIndex = batchEnd
      animationRef.current = setTimeout(animate, ANIMATION_DELAY)
    }

    animate()
  }, [])

  async function fetchEntities() {
    setLoading(true)
    setError(null)
    try {
      const slug = ENTITY_TYPE_SLUG[entityType]
      const res = await fetch(`${API_BASE}/subtree/${slug}/all`)
      if (!res.ok) throw new Error('Failed to fetch entities')
      setEntities(await res.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  async function fetchSubtree() {
    if (selectedEntityId === null) return
    setLoading(true)
    setError(null)
    try {
      const slug = ENTITY_TYPE_SLUG[entityType]
      const depthParam = depth > 0 ? `&depth=${depth}` : ''
      const res = await fetch(`${API_BASE}/subtree/${slug}/id/${selectedEntityId}?direction=${direction}${depthParam}`)
      if (!res.ok) throw new Error('Failed to fetch subtree')
      const data: ApiResponse = await res.json()
      const { nodes: nvlNodes, rels: nvlRels, parentMap: newParentMap } = transformApiResponseToNvl(data)
      setAllNodes(nvlNodes)
      setAllRels(nvlRels)
      setTotalLoadedNodes(nvlNodes.length)
      setParentMap(newParentMap)
      animateTraversal(nvlNodes, nvlRels)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  const computePathToRoot = useCallback((nodeId: string) => {
    const pathNodes = new Set<string>()
    const pathEdges = new Set<string>()
    const pathDetails: Array<{ name: string; type: string }> = []
    let currentId: string | undefined = nodeId
    while (currentId) {
      pathNodes.add(currentId)
      const currentNode = allNodes.find(n => n.id === currentId)
      if (currentNode) pathDetails.push({ name: currentNode.captions?.[0]?.value || 'Unknown', type: currentNode.label || 'Node' })
      const parentId = parentMap.get(currentId)
      if (parentId) {
        const edge = allRels.find(r => (r.from === parentId && r.to === currentId) || (r.from === currentId && r.to === parentId))
        if (edge) pathEdges.add(edge.id)
      }
      currentId = parentId
    }
    return { pathNodes, pathEdges, pathDetails }
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
    setVisibleNodes(allNodes.map(n => ({ id: n.id, captions: n.captions, color: n.color, size: n.size, x: n.x, y: n.y })))
    setVisibleRels(allRels.map(r => ({ id: r.id, from: r.from, to: r.to, captions: r.captions, color: '#000000' })))
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
    <div className="viz-app">
        <header className="border-b sticky top-0 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-50">
          <div className="container px-6 py-4">
              <div className="flex items-center gap-3">
           {/* <img src={favicon} width={40} height={40} alt="favicon" /> */}
                <div>
                    <h1 className="text-xl font-semibold">Visualizer</h1>
                    <p className="text-xs text-muted-foreground">
                        View your data in a Graphical way.
                    </p>
                </div>
              </div>
          </div>
      </header>
      <div className="app-controls">
        <EntitySelector
          entityType={entityType}
          setEntityType={setEntityType}
          entities={entities}
          selectedEntityId={selectedEntityId}
          setSelectedEntityId={setSelectedEntityId}
          loading={loading}
        />
        <ControlPanel depth={depth} setDepth={setDepth} direction={direction} setDirection={setDirection} />
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
            !loading && selectedEntityId === null && (
              <div className="empty-state"><p>Select an entity type and item to visualize its graph</p></div>
            )
          )}
        </div>

        <NodeDetails selectedNode={selectedNode} onClose={() => setSelectedNode(null)} />
      </div>

      <div className="legend">
        <span className="legend-item"><span className="dot capability"></span>Capability</span>
        <span className="legend-item"><span className="dot process"></span>Process</span>
        <span className="legend-item"><span className="dot subprocess"></span>Subprocess</span>
        <span className="legend-item"><span className="dot dataentity"></span>Data Entity</span>
        <span className="legend-item"><span className="dot dataelement"></span>Data Element</span>
        <span className="legend-item"><span className="dot orgunit"></span>Org Unit</span>
        <span className="legend-item"><span className="dot applicationcatalog"></span>Application</span>
      </div>
    </div>
  )
}

export default CompassVisualizer
