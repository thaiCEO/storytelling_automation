<script setup lang="ts">
import type { StoryBible } from '~/composables/useStoryApi'

const props = defineProps<{
  bible: StoryBible
  selectedId: string | null
}>()
const emit = defineEmits<{ select: [id: string | null] }>()

const VIEW_W = 900
const VIEW_H = 560
const NODE_W = 150
const NODE_H = 56

export interface RoleStyle { color: string; emoji: string; label: string }

const ROLE_STYLE: Record<string, RoleStyle> = {
  protagonist: { color: '#fbbf24', emoji: '🌟', label: 'Protagonist' },
  deuteragonist: { color: '#fcd34d', emoji: '✨', label: 'Deuteragonist' },
  villain: { color: '#ef4444', emoji: '😈', label: 'Villain' },
  villain_lieutenant: { color: '#f87171', emoji: '🗡️', label: 'Lieutenant' },
  minion: { color: '#fda4af', emoji: '🪓', label: 'Minion' },
  mentor: { color: '#38bdf8', emoji: '🧙', label: 'Mentor' },
  ally: { color: '#34d399', emoji: '🤝', label: 'Ally' },
  love_interest: { color: '#f472b6', emoji: '❤️', label: 'Love interest' },
  supporting: { color: '#a78bfa', emoji: '👤', label: 'Supporting' },
}
const OBJECT_STYLE: RoleStyle = { color: '#71717a', emoji: '📦', label: 'Object' }

const EDGE_STYLE: Record<string, { color: string; label: string; directed: boolean; dashed?: boolean }> = {
  enemy_of: { color: '#ef4444', label: 'enemy of', directed: false },
  ally_of: { color: '#34d399', label: 'ally of', directed: false },
  sibling_of: { color: '#a78bfa', label: 'sibling of', directed: false },
  parent_of: { color: '#a78bfa', label: 'parent of', directed: true },
  commands: { color: '#fb923c', label: 'commands', directed: true },
  mentors: { color: '#38bdf8', label: 'mentors', directed: true },
  loves: { color: '#f472b6', label: 'loves', directed: true },
  owns: { color: '#71717a', label: 'owns', directed: true, dashed: true },
  uses: { color: '#71717a', label: 'uses', directed: true, dashed: true },
}

function roleStyle(role: string): RoleStyle {
  return ROLE_STYLE[role] ?? ROLE_STYLE.supporting
}

function truncate(name: string): string {
  return name.length > 16 ? name.slice(0, 15) + '…' : name
}

interface GraphNode {
  id: string
  name: string
  cx: number
  cy: number
  style: RoleStyle
  isObject: boolean
}

// deterministic three-band layout: supporting cast left, heroes centre,
// villain hierarchy as a tree on the right, objects along the bottom
const nodes = computed<GraphNode[]>(() => {
  const chars = props.bible.characters
  const rels = props.bible.relationships

  // villain tree depth: BFS over `commands` from villain roots
  // (visited set + depth cap guard against LLM-emitted cycles)
  const depth = new Map<string, number>()
  const heroRoles = new Set(['protagonist', 'deuteragonist'])
  const queue: Array<[string, number]> = chars
    .filter(c => c.role === 'villain')
    .map(c => [c.id, 0])
  while (queue.length) {
    const [id, d] = queue.shift()!
    if (depth.has(id) || d > 3) continue
    depth.set(id, d)
    for (const r of rels) {
      if (r.type !== 'commands' || r.source !== id) continue
      const target = chars.find(c => c.id === r.target)
      if (target && !heroRoles.has(target.role)) queue.push([r.target, d + 1])
    }
  }
  for (const c of chars) {
    if (depth.has(c.id)) continue
    if (c.role === 'villain_lieutenant') depth.set(c.id, 1)
    else if (c.role === 'minion') depth.set(c.id, 2)
  }

  const villains = chars.filter(c => depth.has(c.id))
  const heroes = chars.filter(c => !depth.has(c.id) && heroRoles.has(c.role))
  const support = chars.filter(c => !depth.has(c.id) && !heroRoles.has(c.role))

  const spreadY = (n: number, i: number, top = 100, bottom = 400) =>
    n <= 1 ? (top + bottom) / 2 : top + (i * (bottom - top)) / (n - 1)

  const out: GraphNode[] = []
  support.forEach((c, i) =>
    out.push({ id: c.id, name: c.name, cx: 110, cy: spreadY(support.length, i), style: roleStyle(c.role), isObject: false }))
  heroes.forEach((c, i) =>
    out.push({ id: c.id, name: c.name, cx: 340, cy: spreadY(heroes.length, i, 170, 300), style: roleStyle(c.role), isObject: false }))

  const rows = new Map<number, typeof villains>()
  for (const c of villains) {
    const d = depth.get(c.id)!
    if (!rows.has(d)) rows.set(d, [])
    rows.get(d)!.push(c)
  }
  for (const [d, row] of rows) {
    row.forEach((c, i) => {
      const cx = Math.min(815, Math.max(500, 650 - (row.length - 1) * 85 + i * 170))
      out.push({ id: c.id, name: c.name, cx, cy: 90 + d * 112, style: roleStyle(c.role), isObject: false })
    })
  }

  // objects: bottom band, pulled under the characters that own/use them
  const objXs = props.bible.objects.map((o, i) => {
    const owners = rels
      .filter(r => (r.type === 'owns' || r.type === 'uses') && r.target === o.id)
      .map(r => out.find(n => n.id === r.source)?.cx)
      .filter((x): x is number => x !== undefined)
    const fallback = 150 + (i * 600) / Math.max(props.bible.objects.length - 1, 1)
    return { o, cx: owners.length ? owners.reduce((a, b) => a + b, 0) / owners.length : fallback }
  })
  objXs.sort((a, b) => a.cx - b.cx)
  let prev = -Infinity
  for (const entry of objXs) {
    entry.cx = Math.min(815, Math.max(85, Math.max(entry.cx, prev + 170)))
    prev = entry.cx
    out.push({ id: entry.o.id, name: entry.o.name, cx: entry.cx, cy: 500, style: OBJECT_STYLE, isObject: true })
  }
  return out
})

const nodeById = computed(() => new Map(nodes.value.map(n => [n.id, n])))

interface GraphEdge {
  key: string
  path: string
  color: string
  label: string
  labelX: number
  labelY: number
  dashed: boolean
  directed: boolean
  source: string
  target: string
}

const edges = computed<GraphEdge[]>(() => {
  const byId = nodeById.value
  const rels = props.bible.relationships.filter(r => byId.has(r.source) && byId.has(r.target))

  // parallel edges between the same pair get spread curvatures
  const groups = new Map<string, number>()
  const groupIndex = rels.map((r) => {
    const key = [r.source, r.target].sort().join('|')
    const i = groups.get(key) ?? 0
    groups.set(key, i + 1)
    return i
  })

  return rels.map((r, i) => {
    const s = byId.get(r.source)!
    const t = byId.get(r.target)!
    const style = EDGE_STYLE[r.type] ?? EDGE_STYLE.ally_of
    const dx = t.cx - s.cx
    const dy = t.cy - s.cy
    const len = Math.hypot(dx, dy) || 1
    const nx = -dy / len
    const ny = dx / len
    const curv = [18, -40, 62, -84][groupIndex[i]! % 4]!
    const ctrlX = (s.cx + t.cx) / 2 + nx * curv
    const ctrlY = (s.cy + t.cy) / 2 + ny * curv

    // anchor edges on the node border, not the centre (pad keeps the
    // arrowhead clear of the stroke)
    const anchor = (n: GraphNode, tx: number, ty: number) => {
      const adx = tx - n.cx
      const ady = ty - n.cy
      const scale = 1 / Math.max(Math.abs(adx) / (NODE_W / 2 + 7), Math.abs(ady) / (NODE_H / 2 + 7), 1e-6)
      return { x: n.cx + adx * Math.min(scale, 1), y: n.cy + ady * Math.min(scale, 1) }
    }
    const p0 = anchor(s, ctrlX, ctrlY)
    const p1 = anchor(t, ctrlX, ctrlY)

    return {
      key: `${r.source}-${r.type}-${r.target}-${i}`,
      path: `M ${p0.x} ${p0.y} Q ${ctrlX} ${ctrlY} ${p1.x} ${p1.y}`,
      color: style.color,
      label: style.label,
      labelX: 0.25 * p0.x + 0.5 * ctrlX + 0.25 * p1.x,
      labelY: 0.25 * p0.y + 0.5 * ctrlY + 0.25 * p1.y,
      dashed: style.dashed ?? false,
      directed: style.directed,
      source: r.source,
      target: r.target,
    }
  })
})

const arrowColors = computed(() => [...new Set(edges.value.filter(e => e.directed).map(e => e.color))])

const hoverId = ref<string | null>(null)
const focusId = computed(() => hoverId.value ?? props.selectedId)
const neighborIds = computed(() => {
  if (!focusId.value) return null
  const ids = new Set([focusId.value])
  for (const e of edges.value) {
    if (e.source === focusId.value) ids.add(e.target)
    if (e.target === focusId.value) ids.add(e.source)
  }
  return ids
})

function nodeOpacity(id: string): number {
  if (!neighborIds.value) return 1
  return neighborIds.value.has(id) ? 1 : 0.25
}
function edgeActive(e: GraphEdge): boolean {
  return !!focusId.value && (e.source === focusId.value || e.target === focusId.value)
}
function edgeOpacity(e: GraphEdge): number {
  if (!focusId.value) return 0.9
  return edgeActive(e) ? 1 : 0.12
}

const legend = computed(() => {
  const roles = [...new Set(props.bible.characters.map(c => c.role))]
  const items = roles.map(r => roleStyle(r))
  if (props.bible.objects.length) items.push(OBJECT_STYLE)
  return items
})
</script>

<template>
  <div>
    <svg
      :viewBox="`0 0 ${VIEW_W} ${VIEW_H}`"
      class="w-full select-none rounded-xl border border-zinc-800 bg-zinc-950"
      @click="emit('select', null)"
    >
      <defs>
        <marker
          v-for="color in arrowColors"
          :id="`arrow-${color.slice(1)}`"
          :key="color"
          markerWidth="8"
          markerHeight="8"
          refX="7"
          refY="4"
          orient="auto"
          markerUnits="userSpaceOnUse"
        >
          <path d="M 0 0.5 L 8 4 L 0 7.5 Z" :fill="color" />
        </marker>
      </defs>

      <!-- edges under nodes -->
      <g v-for="e in edges" :key="e.key" class="transition-opacity duration-200" :opacity="edgeOpacity(e)">
        <path
          :d="e.path"
          fill="none"
          :stroke="e.color"
          :stroke-width="edgeActive(e) ? 2.5 : 1.5"
          :stroke-dasharray="e.dashed ? '6 4' : undefined"
          :marker-end="e.directed ? `url(#arrow-${e.color.slice(1)})` : undefined"
        />
        <g>
          <rect
            :x="e.labelX - (e.label.length * 5.4 + 12) / 2"
            :y="e.labelY - 9"
            :width="e.label.length * 5.4 + 12"
            height="18"
            rx="9"
            fill="#09090b"
            :stroke="e.color"
            stroke-opacity="0.45"
          />
          <text
            :x="e.labelX"
            :y="e.labelY + 3.5"
            text-anchor="middle"
            font-size="9.5"
            fill="#d4d4d8"
          >{{ e.label }}</text>
        </g>
      </g>

      <!-- nodes -->
      <g
        v-for="n in nodes"
        :key="n.id"
        class="cursor-pointer transition-opacity duration-200"
        :opacity="nodeOpacity(n.id)"
        @click.stop="emit('select', selectedId === n.id ? null : n.id)"
        @mouseenter="hoverId = n.id"
        @mouseleave="hoverId = null"
      >
        <rect
          :x="n.cx - NODE_W / 2"
          :y="n.cy - NODE_H / 2"
          :width="NODE_W"
          :height="NODE_H"
          rx="12"
          fill="#18181b"
          :stroke="n.style.color"
          :stroke-width="selectedId === n.id ? 3 : 1.5"
          :stroke-dasharray="n.isObject ? '5 4' : undefined"
        />
        <text :x="n.cx - 52" :y="n.cy + 8" text-anchor="middle" font-size="22">{{ n.style.emoji }}</text>
        <text :x="n.cx + 12" :y="n.cy - 2" text-anchor="middle" font-size="12.5" font-weight="600" fill="#f4f4f5">
          {{ truncate(n.name) }}
        </text>
        <text
          :x="n.cx + 12"
          :y="n.cy + 15"
          text-anchor="middle"
          font-size="8.5"
          letter-spacing="1"
          :fill="n.style.color"
        >{{ n.style.label.toUpperCase() }}</text>
      </g>
    </svg>

    <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-zinc-400">
      <span v-for="item in legend" :key="item.label" class="inline-flex items-center gap-1.5">
        <span class="h-2.5 w-2.5 rounded-full" :style="{ backgroundColor: item.color }" />
        {{ item.label }}
      </span>
    </div>
  </div>
</template>
