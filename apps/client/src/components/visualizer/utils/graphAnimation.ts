import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { Node, Relationship } from '@neo4j-nvl/base'

export const ANIMATION_DELAY = 80
export const ANIMATION_BATCH_SIZE = 5
export const ANIMATION_NODE_LIMIT = 80

export interface AnimatableNode extends Node {
  traversalOrder: number
}

export interface AnimatableRelationship extends Relationship {
  traversalOrder: number
}

export interface GraphAnimationCallbacks {
  setVisibleNodes: Dispatch<SetStateAction<Node[]>>
  setVisibleRels: Dispatch<SetStateAction<Relationship[]>>
  setAnimating: (value: boolean) => void
  onComplete?: () => void
}

export function filterValidRelationships<T extends Relationship>(
  rels: T[],
  nodeIds: Set<string>,
): T[] {
  return rels.filter(rel => nodeIds.has(String(rel.from)) && nodeIds.has(String(rel.to)))
}

export function runGraphAnimation(
  nodes: AnimatableNode[],
  rels: AnimatableRelationship[],
  animationRef: MutableRefObject<ReturnType<typeof setTimeout> | null>,
  callbacks: GraphAnimationCallbacks,
) {
  const { setVisibleNodes, setVisibleRels, setAnimating, onComplete } = callbacks

  if (animationRef.current) clearTimeout(animationRef.current)

  const nodeIds = new Set(nodes.map(n => String(n.id)))
  const validRels = filterValidRelationships(rels, nodeIds)

  const allNvlNodes = nodes.map(n => ({
    id: n.id,
    captions: n.captions,
    color: n.color,
    size: n.size,
    x: n.x,
    y: n.y,
  }))
  const allNvlRels = validRels.map(r => ({
    id: r.id,
    from: r.from,
    to: r.to,
    captions: r.captions,
    color: '#000000',
  }))

  if (nodes.length > ANIMATION_NODE_LIMIT) {
    setVisibleNodes(allNvlNodes)
    setVisibleRels(allNvlRels)
    setAnimating(false)
    onComplete?.()
    return
  }

  setVisibleNodes([])
  setVisibleRels([])
  setAnimating(true)

  const sortedNodes = [...nodes].sort((a, b) => a.traversalOrder - b.traversalOrder)
  const sortedRels = [...validRels].sort((a, b) => a.traversalOrder - b.traversalOrder)
  const orderById = new Map(sortedNodes.map(n => [String(n.id), n.traversalOrder]))
  let nodeIndex = 0
  let relIndex = 0

  const animate = () => {
    if (nodeIndex >= sortedNodes.length) {
      if (relIndex < sortedRels.length) {
        const remaining = sortedRels.slice(relIndex).map(r => ({
          id: r.id,
          from: r.from,
          to: r.to,
          captions: r.captions,
          color: '#000000',
        }))
        setVisibleRels(prev => [...prev, ...remaining])
      }
      setAnimating(false)
      onComplete?.()
      return
    }

    const batchEnd = Math.min(nodeIndex + ANIMATION_BATCH_SIZE, sortedNodes.length)
    const batchNodes = sortedNodes.slice(nodeIndex, batchEnd)
    const maxOrderInBatch = batchNodes[batchNodes.length - 1].traversalOrder

    const newNvlNodes = batchNodes.map(n => ({
      id: n.id,
      captions: n.captions,
      color: n.color,
      size: n.size,
      x: n.x,
      y: n.y,
    }))

    const newNvlRels: Relationship[] = []
    while (relIndex < sortedRels.length) {
      const rel = sortedRels[relIndex]
      const sourceOrder = orderById.get(String(rel.from)) ?? Infinity
      const targetOrder = orderById.get(String(rel.to)) ?? Infinity
      if (sourceOrder <= maxOrderInBatch && targetOrder <= maxOrderInBatch) {
        newNvlRels.push({
          id: rel.id,
          from: rel.from,
          to: rel.to,
          captions: rel.captions,
          color: '#000000',
        })
        relIndex++
      } else {
        break
      }
    }

    setVisibleNodes(prev => [...prev, ...newNvlNodes])
    if (newNvlRels.length > 0) setVisibleRels(prev => [...prev, ...newNvlRels])

    nodeIndex = batchEnd
    animationRef.current = setTimeout(animate, ANIMATION_DELAY)
  }

  animate()
}
