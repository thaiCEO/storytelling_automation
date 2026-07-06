<script setup lang="ts">
defineProps<{ modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()

const endings = [
  { value: 'happy', label: 'Happy', emoji: '😊' },
  { value: 'tragic', label: 'Tragic', emoji: '💔' },
  { value: 'bittersweet', label: 'Bittersweet', emoji: '🥲' },
  { value: 'twist', label: 'Twist', emoji: '🌀' },
  { value: 'open', label: 'Open', emoji: '🌫️' },
]
</script>

<template>
  <ChipSelect
    :options="endings"
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
  />
</template>
