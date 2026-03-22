import type { Node, Relationship } from '@neo4j-nvl/base'
import type { ApiNode, ApiResponse } from '../types'

const LABEL_COLORS: Record<string, string> = {
  Capability: '#FF6B6B',
  Process: '#4ECDC4',
  Subprocess: '#45B7D1',
  DataEntity: '#A990D5',
  DataElements: '#F7B731',
  DataElement: '#F7B731',
}

export interface TransformResult {
  nodes: TraversalNode[]
  rels: TraversalRelationship[]
  parentMap: Map<string, string>
  rootId: string | null
}

export interface TraversalNode extends Node {
  traversalOrder: number
  originalColor: string
  label: string
  properties: Record<string, unknown>
}

export interface TraversalRelationship extends Relationship {
  traversalOrder: number
}

export function transformApiResponseToNvl(data: ApiResponse): TransformResult {
  const nodes: TraversalNode[] = []
  const rels: TraversalRelationship[] = []
  const seenNodes = new Set<string>()
  const seenRels = new Set<string>()
  const parentMap = new Map<string, string>()
  let relId = 0
  let nodeIndex = 0
  let rootId: string | null = null

  function processNode(node: ApiNode, depth: number = 0, parentAngle: number = 0, parentId: string | null = null): string {
    const nodeId = node.internal_id.toString()
    if (!seenNodes.has(nodeId)) {
      seenNodes.add(nodeId)
      if (depth === 0) rootId = nodeId
      if (parentId !== null) parentMap.set(nodeId, parentId)

      const label = node.labels[0] || 'Node'
      const name = node.properties.name || `${label} ${node.properties.uid}`
      const color = LABEL_COLORS[label] || '#607D8B'
      const radius = 150 + depth * 250
      const angleSpread = (Math.PI * 2) / Math.max(8, nodeIndex + 1)
      const x = Math.cos(nodeIndex * angleSpread + parentAngle) * radius
      const y = Math.sin(nodeIndex * angleSpread + parentAngle) * radius
      const currentOrder = nodeIndex++

      nodes.push({
        id: nodeId,
        captions: [{ value: name }],
        color,
        originalColor: color,
        size: 30,
        x,
        y,
        traversalOrder: currentOrder,
        label,
        properties: { ...node.properties, labels: node.labels },
      })
    }

    if (node.relationships) {
      for (const [relType, relatedNodes] of Object.entries(node.relationships)) {
        for (let i = 0; i < relatedNodes.length; i++) {
          const childAngle = parentAngle + (i * (Math.PI * 2) / Math.max(relatedNodes.length, 1))
          const targetId = processNode(relatedNodes[i], depth + 1, childAngle, nodeId)
          const relKey = `${nodeId}-${relType}-${targetId}`
          if (!seenRels.has(relKey)) {
            seenRels.add(relKey)
            rels.push({
              id: `rel_${relId}`,
              from: nodeId,
              to: targetId,
              captions: [{ value: relType, styles: ['bold'] }],
              color: '#000000',
              traversalOrder: relId++,
            })
          }
        }
      }
    }
    return nodeId
  }

  if (data.root) processNode(data.root)
  return { nodes, rels, parentMap, rootId }
}
