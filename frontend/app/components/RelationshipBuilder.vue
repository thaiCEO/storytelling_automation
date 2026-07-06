<script lang="ts">
// Optional edges the user draws on /create, keyed by asset NAME (bible ids
// don't exist yet). Sent as StoryInput.relationship_hints; the backend
// resolves the names to generated characters/objects after Pass 2.
export interface RelationshipHint {
  source: string
  target: string
  type: string
  label: string
}

// direction reads source -> target; labels spell that out so users pick right
export const RELATIONSHIP_OPTIONS: { value: string; label: string }[] = [
  { value: 'commands', label: 'commands (boss → underling)' },
  { value: 'parent_of', label: 'parent of (parent → child)' },
  { value: 'sibling_of', label: 'sibling of' },
  { value: 'ally_of', label: 'ally of' },
  { value: 'enemy_of', label: 'enemy of' },
  { value: 'loves', label: 'loves' },
  { value: 'mentors', label: 'mentors (mentor → student)' },
  { value: 'owns', label: 'owns (character → object)' },
  { value: 'uses', label: 'uses (character → object)' },
]
</script>

<script setup lang="ts">
const hints = defineModel<RelationshipHint[]>({ default: () => [] })
// names of the reference boxes, offered as autocomplete for source/target
const props = defineProps<{ names: string[] }>()

const suggestions = computed(() => [...new Set(props.names.map(n => n.trim()).filter(Boolean))])

function add() {
  hints.value = [...hints.value, { source: '', target: '', type: 'commands', label: '' }]
}
function remove(i: number) {
  hints.value = hints.value.filter((_, j) => j !== i)
}
</script>

<template>
  <div>
    <button
      type="button"
      class="rounded-lg border border-zinc-700 px-3 py-1.5 text-sm hover:border-amber-400 hover:text-amber-300"
      @click="add"
    >
      + 🔗 Relationship
    </button>

    <datalist id="ref-names">
      <option v-for="n in suggestions" :key="n" :value="n" />
    </datalist>

    <div v-if="hints.length" class="mt-3 space-y-2">
      <div
        v-for="(h, i) in hints"
        :key="i"
        class="flex flex-wrap items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 p-2"
      >
        <input
          v-model.trim="h.source"
          list="ref-names"
          placeholder="Vex"
          class="min-w-24 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm placeholder:text-zinc-600 focus:border-amber-400 focus:outline-none"
        >
        <select
          v-model="h.type"
          class="rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-xs text-amber-300 focus:border-amber-400 focus:outline-none"
        >
          <option v-for="r in RELATIONSHIP_OPTIONS" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
        <input
          v-model.trim="h.target"
          list="ref-names"
          placeholder="Grub"
          class="min-w-24 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm placeholder:text-zinc-600 focus:border-amber-400 focus:outline-none"
        >
        <input
          v-model.trim="h.label"
          placeholder="note (optional)"
          class="min-w-20 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-xs placeholder:text-zinc-600 focus:border-amber-400 focus:outline-none"
        >
        <button
          type="button"
          aria-label="Remove relationship"
          class="rounded-md px-2 py-1 text-xs text-red-400 hover:text-red-300"
          @click="remove(i)"
        >
          ✕
        </button>
      </div>
    </div>

    <p v-if="hints.length" class="mt-2 text-xs text-zinc-500">
      Reads left → right. Names should match your reference boxes (or just type a
      name and the AI will create that character).
    </p>
  </div>
</template>
