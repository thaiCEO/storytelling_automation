<script setup lang="ts">
defineProps<{ modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()

// Khmer labels per skills/image-pipeline.md
const styles = [
  { value: 'cartoon_3d', label: 'តុក្កតា 3D', sub: 'Cartoon 3D', img: '/styles/cartoon_3d.png' },
  { value: 'anime', label: 'អានីមេ', sub: 'Anime', img: '/styles/anime.png' },
  { value: 'storybook_2d', label: 'រឿងនិទាន 2D', sub: 'Storybook 2D', img: '/styles/storybook_2d.svg' },
  { value: 'cinematic_realistic', label: 'ដូចមនុស្សពិត', sub: 'Cinematic realistic', img: '/styles/cinematic_realistic.png' },
]
</script>

<template>
  <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
    <button
      v-for="s in styles"
      :key="s.value"
      type="button"
      class="overflow-hidden rounded-xl border text-left transition"
      :class="modelValue === s.value
        ? 'border-amber-400 ring-2 ring-amber-400/40'
        : 'border-zinc-700 hover:border-zinc-500'"
      @click="$emit('update:modelValue', s.value)"
    >
      <img :src="s.img" :alt="s.sub" class="aspect-video w-full object-cover">
      <div class="p-2">
        <div class="text-sm font-semibold">{{ s.label }}</div>
        <div class="text-xs text-zinc-400">{{ s.sub }}</div>
      </div>
    </button>
  </div>
</template>
