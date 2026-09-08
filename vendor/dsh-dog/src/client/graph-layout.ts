/** Deterministic browser-side layout for containment and dependency edges. */

import type { DogGraphInput } from '../model.ts'

export const GOAL_WIDTH = 218
export const GOAL_HEIGHT = 88
const HORIZONTAL_GAP = 44
const VERTICAL_GAP = 92
const CANVAS_PADDING_X = 56
const CANVAS_PADDING_Y = 48
const MIN_CANVAS_WIDTH = 700

export interface PositionedGoal {
  readonly id: string
  readonly x: number
  readonly y: number
  readonly width: number
  readonly height: number
  readonly depth: number
}

export interface PositionedEdge {
  readonly id: string
  readonly kind: 'contains' | 'dependsOn'
  readonly source: string
  readonly target: string
  readonly path: string
}

export interface DagLayout {
  readonly width: number
  readonly height: number
  readonly nodes: readonly PositionedGoal[]
  readonly edges: readonly PositionedEdge[]
}

/** Lay containment levels top-to-bottom while retaining declared node order within a level. */
export function layoutDag(graph: DogGraphInput): DagLayout {
  const parents = new Map<string, string[]>()
  for (const edge of graph.contains) {
    const values = parents.get(edge.child) ?? []
    values.push(edge.parent)
    parents.set(edge.child, values)
  }
  const depths = new Map<string, number>()
  const visiting = new Set<string>()
  const depthOf = (id: string): number => {
    const known = depths.get(id)
    if (known !== undefined) return known
    if (id === graph.root) {
      depths.set(id, 0)
      return 0
    }
    if (visiting.has(id)) return 0
    visiting.add(id)
    const incoming = parents.get(id) ?? []
    const depth = incoming.length === 0 ? 0 : Math.max(...incoming.map(parent => depthOf(parent) + 1))
    visiting.delete(id)
    depths.set(id, depth)
    return depth
  }

  const layers = new Map<number, string[]>()
  for (const id of Object.keys(graph.nodes)) {
    const depth = depthOf(id)
    const layer = layers.get(depth) ?? []
    layer.push(id)
    layers.set(depth, layer)
  }
  const layerEntries = [...layers.entries()].sort(([left], [right]) => left - right)
  const widest = Math.max(1, ...layerEntries.map(([, ids]) => ids.length))
  const naturalWidth = widest * GOAL_WIDTH + Math.max(0, widest - 1) * HORIZONTAL_GAP + CANVAS_PADDING_X * 2
  const width = Math.max(MIN_CANVAS_WIDTH, naturalWidth)
  const positioned: PositionedGoal[] = []
  for (const [depth, ids] of layerEntries) {
    const layerWidth = ids.length * GOAL_WIDTH + Math.max(0, ids.length - 1) * HORIZONTAL_GAP
    const startX = (width - layerWidth) / 2
    ids.forEach((id, index) => positioned.push({
      id,
      x: startX + index * (GOAL_WIDTH + HORIZONTAL_GAP),
      y: CANVAS_PADDING_Y + depth * (GOAL_HEIGHT + VERTICAL_GAP),
      width: GOAL_WIDTH,
      height: GOAL_HEIGHT,
      depth,
    }))
  }
  const maximumDepth = Math.max(0, ...positioned.map(node => node.depth))
  const height = CANVAS_PADDING_Y * 2 + GOAL_HEIGHT + maximumDepth * (GOAL_HEIGHT + VERTICAL_GAP)
  const byId = new Map(positioned.map(node => [node.id, node]))
  const edges: PositionedEdge[] = []
  graph.contains.forEach((edge, index) => {
    const source = byId.get(edge.parent)
    const target = byId.get(edge.child)
    if (source === undefined || target === undefined) return
    edges.push({
      id: `contains:${index}:${edge.parent}:${edge.child}`,
      kind: 'contains',
      source: edge.parent,
      target: edge.child,
      path: containmentPath(source, target),
    })
  })
  graph.dependsOn.forEach((edge, index) => {
    const source = byId.get(edge.source)
    const target = byId.get(edge.target)
    if (source === undefined || target === undefined) return
    edges.push({
      id: `depends:${index}:${edge.source}:${edge.target}`,
      kind: 'dependsOn',
      source: edge.source,
      target: edge.target,
      // "source depends on target" means target runs first, so the edge is
      // drawn target -> source (dependency arrow points at the dependent).
      path: dependencyPath(target, source, index),
    })
  })
  return { width, height, nodes: positioned, edges }
}

function containmentPath(source: PositionedGoal, target: PositionedGoal): string {
  const startX = source.x + source.width / 2
  const startY = source.y + source.height
  const endX = target.x + target.width / 2
  const endY = target.y
  const middleY = startY + (endY - startY) / 2
  return `M ${startX} ${startY} C ${startX} ${middleY}, ${endX} ${middleY}, ${endX} ${endY}`
}

function dependencyPath(source: PositionedGoal, target: PositionedGoal, index: number): string {
  const sourceCenterX = source.x + source.width / 2
  const targetCenterX = target.x + target.width / 2
  const rightward = targetCenterX >= sourceCenterX
  const startX = rightward ? source.x + source.width : source.x
  const endX = rightward ? target.x : target.x + target.width
  const startY = source.y + source.height / 2
  const endY = target.y + target.height / 2
  const bend = (rightward ? 1 : -1) * (54 + (index % 3) * 12)
  return `M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`
}
