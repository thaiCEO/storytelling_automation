<script setup lang="ts">
defineProps<{ modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()

const formats = [
  { value: 'youtube', label: 'YouTube', sub: '16:9 landscape · 1920×1080', icon: '📺', box: 'h-[45px] w-20' },
  { value: 'tiktok', label: 'TikTok / Reels', sub: '9:16 vertical · 1080×1920', icon: '📱', box: 'h-20 w-[45px]' },
]
</script>

<template>
  <div class="grid grid-cols-2 gap-3">
    <button
      v-for="f in formats"
      :key="f.value"
      type="button"
      class="rounded-xl border p-3 text-center transition"
      :class="modelValue === f.value
        ? 'border-amber-400 ring-2 ring-amber-400/40'
        : 'border-zinc-700 hover:border-zinc-500'"
      @click="$emit('update:modelValue', f.value)"
    >
      <div class="flex h-24 items-center justify-center">
        <div
          class="flex items-center justify-center rounded border-2"
          :class="[f.box, modelValue === f.value ? 'border-amber-400 text-amber-300' : 'border-zinc-600 text-zinc-500']"
        >
          {{ f.icon }}
        </div>
      </div>
      <div class="mt-1 text-sm font-semibold">{{ f.label }}</div>
      <div class="text-xs text-zinc-400">{{ f.sub }}</div>
    </button>
  </div>
</template>
