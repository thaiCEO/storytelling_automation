<script setup lang="ts">
const emit = defineEmits<{
  apply: [preset: { tone: string; visual_style: string; narrator_style: string }]
}>()

const presets = [
  {
    name: '🎥 Documentary',
    tone: 'grounded, reflective',
    visual_style: 'cinematic, natural light, handheld realism',
    narrator_style: 'deep, measured, documentary-like',
  },
  {
    name: '🌌 Epic',
    tone: 'grand, awe-inspiring',
    visual_style: 'epic scale, dramatic skies, sweeping vistas, volumetric light',
    narrator_style: 'powerful, resonant, mythic',
  },
  {
    name: '🕯️ Dark & moody',
    tone: 'tense, foreboding',
    visual_style: 'low-key lighting, deep shadows, desaturated palette, film grain',
    narrator_style: 'slow, hushed, ominous',
  },
  {
    name: '💛 Warm & hopeful',
    tone: 'tender, uplifting',
    visual_style: 'golden hour glow, soft focus, warm palette',
    narrator_style: 'warm, gentle, intimate',
  },
]
</script>

<template>
  <div class="flex flex-wrap gap-2">
    <button
      v-for="p in presets"
      :key="p.name"
      type="button"
      class="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 transition hover:border-amber-400 hover:text-amber-300"
      @click="emit('apply', p)"
    >
      {{ p.name }}
    </button>
  </div>
</template>
