<script setup lang="ts">
defineProps<{ modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()

const genres = [
  { value: 'sci-fi', label: 'Sci-Fi', emoji: '🚀' },
  { value: 'fantasy', label: 'Fantasy', emoji: '🐉' },
  { value: 'horror', label: 'Horror', emoji: '👻' },
  { value: 'drama', label: 'Drama', emoji: '🎭' },
  { value: 'thriller', label: 'Thriller', emoji: '🔪' },
  { value: 'mystery', label: 'Mystery', emoji: '🕵️' },
]
</script>

<template>
  <ChipSelect
    :options="genres"
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
  />
</template>
