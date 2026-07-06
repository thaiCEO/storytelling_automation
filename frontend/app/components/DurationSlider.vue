<script setup lang="ts">
import type { Estimate } from '~/composables/useStoryApi'

const props = defineProps<{ modelValue: number; estimate: Estimate | null }>()
defineEmits<{ 'update:modelValue': [value: number] }>()

const breakdown = computed(() => ({
  llm: props.estimate?.breakdown.llm ?? 0,
  images: props.estimate?.breakdown.images ?? 0,
  tts: props.estimate?.breakdown.tts ?? 0,
  hook: props.estimate?.breakdown.hook ?? 0,
}))
</script>

<template>
  <div>
    <div class="flex items-baseline justify-between">
      <span class="text-2xl font-bold text-amber-300">{{ modelValue }} min</span>
      <span v-if="estimate" class="text-sm text-zinc-400">
        ≈ <span class="font-semibold text-emerald-400">${{ estimate.total.toFixed(2) }}</span>
        · {{ estimate.scenes }} scenes · {{ estimate.words }} words
      </span>
    </div>
    <input
      type="range"
      min="1"
      max="15"
      step="1"
      :value="modelValue"
      class="mt-2 w-full accent-amber-400"
      @input="$emit('update:modelValue', Number(($event.target as HTMLInputElement).value))"
    >
    <div class="mt-1 flex justify-between text-xs text-zinc-500">
      <span>1 min</span><span>7 min</span><span>15 min</span>
    </div>
    <div v-if="estimate" class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
      <span>LLM ${{ breakdown.llm.toFixed(2) }}</span>
      <span>Images ${{ breakdown.images.toFixed(2) }}</span>
      <span>Voice ${{ breakdown.tts.toFixed(2) }}</span>
      <span>Hook ${{ breakdown.hook.toFixed(2) }}</span>
    </div>
  </div>
</template>
