import type { Node, Relationship } from '@neo4j-nvl/base'
import type { PmoApiNode, PmoFlatGraphResponse } from '../pmoTypes'
import { PMO_LABEL_COLORS } from '../pmoTypes'
import { filterValidRelationships } from './graphAnimation'

export interface PmoTransformResult {
  nodes: PmoTraversalNode[]
  rels: PmoTraversalRelationship[]
  parentMap: Map<string, string>
  rootId: string | null
}

export interface PmoTraversalNode extends Node {
  traversalOrder: number
  originalColor: string
  label: string
  properties: Record<string, unknown>
}

export interface PmoTraversalRelationship extends Relationship {
  traversalOrder: number
}

const COMPONENT_SPACING = 900

function resolveDisplayName(node: PmoApiNode): string {
  const props = node.properties
  const label = node.labels[0] || 'Node'
  return (
    (props.name as string) ||
    (props.description as string) ||
    (props.systemName as string) ||
    (props.artefactType as string) ||
    (props.outcome as string) ||
    (props.instanceUri as string) ||
    (props.uri as string) ||
    `${label}`
  )
}

export function transformPmoFlatGraphToNvl(data: PmoFlatGraphResponse): PmoTransformResult {
  const nodes: PmoTraversalNode[] = []
  const rels: PmoTraversalRelationship[] = []
  const parentMap = new Map<string, string>()
  const nodeById = new Map<string, PmoApiNode>()
  let relId = 0

  for (const node of data.nodes) {
    nodeById.set(String(node.internal_id), node)
  }

  if (nodeById.size === 0) {
    return { nodes, rels, parentMap, rootId: null }
  }

  const rootId = String(data.root_id)
  const effectiveRootId = nodeById.has(rootId) ? rootId : nodeById.keys().next().value!

  const adjacency = new Map<string, Array<{ targetId: string; relType: string }>>()
  for (const rel of data.relationships) {
    const from = String(rel.start_node_id)
    const to = String(rel.end_node_id)
    if (!nodeById.has(from) || !nodeById.has(to)) continue
    adjacency.set(from, [...(adjacency.get(from) || []), { targetId: to, relType: rel.type }])
    adjacency.set(to, [...(adjacency.get(to) || []), { targetId: from, relType: rel.type }])
  }

  const visited = new Set<string>()
  const orderedSeeds = [
    effectiveRootId,
    ...Array.from(nodeById.keys()).filter(id => id !== effectiveRootId),
  ]
  let nodeIndex = 0
  let componentIndex = 0

  for (const seedId of orderedSeeds) {
    if (visited.has(seedId)) continue

    const componentOffsetX = componentIndex * COMPONENT_SPACING
    componentIndex++

    const queue: Array<{ id: string; depth: number; parentId: string | null; angle: number }> = [
      { id: seedId, depth: 0, parentId: null, angle: 0 },
    ]

    while (queue.length > 0) {
      const { id, depth, parentId, angle } = queue.shift()!
      if (visited.has(id)) continue
      visited.add(id)

      const apiNode = nodeById.get(id)
      if (!apiNode) continue

      if (parentId !== null) parentMap.set(id, parentId)

      const label = apiNode.labels[0] || 'Node'
      const name = resolveDisplayName(apiNode)
      const color = PMO_LABEL_COLORS[label] || '#607D8B'
      const radius = 150 + depth * 250
      const angleSpread = (Math.PI * 2) / Math.max(8, nodeIndex + 1)
      const x = componentOffsetX + Math.cos(nodeIndex * angleSpread + angle) * radius
      const y = Math.sin(nodeIndex * angleSpread + angle) * radius

      nodes.push({
        id,
        captions: [{ value: name }],
        color,
        originalColor: color,
        size: 30,
        x,
        y,
        traversalOrder: nodeIndex++,
        label,
        properties: { ...apiNode.properties, labels: apiNode.labels },
      })

      const neighbors = adjacency.get(id) || []
      neighbors.forEach((neighbor, index) => {
        if (visited.has(neighbor.targetId)) return
        const childAngle = angle + (index * (Math.PI * 2)) / Math.max(neighbors.length, 1)
        queue.push({ id: neighbor.targetId, depth: depth + 1, parentId: id, angle: childAngle })
      })
    }
  }

  const seenRels = new Set<string>()
  for (const rel of data.relationships) {
    const from = String(rel.start_node_id)
    const to = String(rel.end_node_id)
    const relKey = `${from}-${rel.type}-${to}`
    if (!nodeById.has(from) || !nodeById.has(to) || seenRels.has(relKey)) continue
    seenRels.add(relKey)
    rels.push({
      id: `rel_${relId}`,
      from,
      to,
      captions: [{ value: rel.type, styles: ['bold'] }],
      color: '#000000',
      traversalOrder: relId++,
    })
  }

  const nodeIds = new Set(nodes.map(n => String(n.id)))
  const validRels = filterValidRelationships(rels, nodeIds)

  return { nodes, rels: validRels, parentMap, rootId: effectiveRootId }
}

export function transformPmoApiResponseToNvl(data: PmoFlatGraphResponse): PmoTransformResult {
  return transformPmoFlatGraphToNvl(data)
}
