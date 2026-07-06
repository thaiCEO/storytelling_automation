<script setup lang="ts">
import type { StoryBible, BibleAsset, BibleCharacter } from '~/composables/useStoryApi'

const props = defineProps<{
  bible: StoryBible
  selectedId: string | null
}>()
const emit = defineEmits<{ select: [id: string] }>()

const ROLE_LABEL: Record<string, { label: string; classes: string }> = {
  protagonist: { label: '🌟 Protagonist', classes: 'border-amber-400/50 text-amber-300' },
  deuteragonist: { label: '✨ Deuteragonist', classes: 'border-amber-300/50 text-amber-200' },
  villain: { label: '😈 Villain', classes: 'border-red-500/50 text-red-400' },
  villain_lieutenant: { label: '🗡️ Lieutenant', classes: 'border-red-400/50 text-red-300' },
  minion: { label: '🪓 Minion', classes: 'border-rose-300/50 text-rose-300' },
  mentor: { label: '🧙 Mentor', classes: 'border-sky-400/50 text-sky-300' },
  ally: { label: '🤝 Ally', classes: 'border-emerald-400/50 text-emerald-300' },
  love_interest: { label: '❤️ Love interest', classes: 'border-pink-400/50 text-pink-300' },
  supporting: { label: '👤 Supporting', classes: 'border-violet-400/50 text-violet-300' },
}
const OBJECT_BADGE = { label: '📦 Object', classes: 'border-zinc-600 text-zinc-400' }

const VERBS: Record<string, string> = {
  parent_of: 'is the parent of',
  sibling_of: 'is a sibling of',
  commands: 'commands',
  ally_of: 'is allied with',
  enemy_of: 'is the enemy of',
  loves: 'loves',
  mentors: 'mentors',
  owns: 'owns',
  uses: 'uses',
}

const selected = computed<BibleAsset | BibleCharacter | null>(() => {
  if (!props.selectedId) return null
  return (
    props.bible.characters.find(a => a.id === props.selectedId)
    ?? props.bible.objects.find(a => a.id === props.selectedId)
    ?? null
  )
})

const badge = computed(() => {
  if (!selected.value) return OBJECT_BADGE
  const role = (selected.value as BibleCharacter).role
  return role ? (ROLE_LABEL[role] ?? ROLE_LABEL.supporting!) : OBJECT_BADGE
})

function assetName(id: string): string {
  return props.bible.characters.find(a => a.id === id)?.name
    ?? props.bible.objects.find(a => a.id === id)?.name
    ?? id
}

// relationship sentences for the selected node, each linking to the other end
const sentences = computed(() => {
  if (!props.selectedId) return []
  return props.bible.relationships
    .filter(r => r.source === props.selectedId || r.target === props.selectedId)
    .map((r) => {
      const otherId = r.source === props.selectedId ? r.target : r.source
      return {
        key: `${r.source}-${r.type}-${r.target}`,
        text: `${assetName(r.source)} ${VERBS[r.type] ?? r.type} ${assetName(r.target)}`,
        note: r.label,
        otherId,
      }
    })
})
</script>

<template>
  <aside class="rounded-xl border border-zinc-800 p-4">
    <template v-if="selected">
      <img
        v-if="selected.reference_image_url"
        :src="selected.reference_image_url"
        :alt="selected.name"
        class="mb-3 aspect-video w-full rounded-lg border border-zinc-800 object-cover"
      >
      <div class="flex items-start justify-between gap-2">
        <h2 class="text-lg font-bold">{{ selected.name }}</h2>
        <span class="whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold" :class="badge.classes">
          {{ badge.label }}
        </span>
      </div>

      <p class="mt-2 text-sm leading-relaxed text-zinc-400">{{ selected.visual_dna }}</p>

      <h3 class="mt-4 mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">Relationships</h3>
      <ul v-if="sentences.length" class="space-y-1.5">
        <li v-for="s in sentences" :key="s.key">
          <button
            class="w-full rounded-lg border border-zinc-800 px-3 py-2 text-left text-sm text-zinc-300 transition hover:border-amber-400/60 hover:text-amber-200"
            @click="emit('select', s.otherId)"
          >
            {{ s.text }}
            <span v-if="s.note" class="text-xs text-zinc-500">({{ s.note }})</span>
          </button>
        </li>
      </ul>
      <p v-else class="text-sm text-zinc-500">No relationships recorded for this one.</p>
    </template>

    <div v-else class="py-10 text-center text-sm text-zinc-500">
      <div class="mb-2 text-2xl">🕸️</div>
      Click a node to inspect it —<br>role, look and every connection.
    </div>
  </aside>
</template>
