<script setup lang="ts">
defineProps<{
  options: { value: string; label: string; emoji?: string }[]
  modelValue: string
}>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div class="flex flex-wrap gap-2">
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      class="rounded-full border px-4 py-1.5 text-sm transition"
      :class="modelValue === o.value
        ? 'border-amber-400 bg-amber-400/15 text-amber-300'
        : 'border-zinc-700 text-zinc-300 hover:border-zinc-500'"
      @click="$emit('update:modelValue', o.value)"
    >
      <span v-if="o.emoji" class="mr-1">{{ o.emoji }}</span>{{ o.label }}
    </button>
  </div>
</template>
