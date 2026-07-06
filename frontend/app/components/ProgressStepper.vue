<script setup lang="ts">
import type { StoryStatus } from '~/composables/useStoryApi'

const props = defineProps<{ status: StoryStatus }>()

interface Step {
  key: string
  label: string
  note?: string
  running: string
  done: string
  withProgress?: boolean
}

const steps: Step[] = [
  { key: 'story', label: 'Story', running: 'story_running', done: 'story_done' },
  { key: 'images', label: 'Images', running: 'images_running', done: 'images_done', withProgress: true },
  { key: 'voice', label: 'Voice', note: 'English narration', running: 'voice_running', done: 'voice_done', withProgress: true },
  { key: 'subtitles', label: 'Subtitles', running: 'subtitles_running', done: 'subtitles_done' },
  { key: 'hook', label: 'Short hook', note: 'Seedance 2.0 Mini', running: 'hook_running', done: 'hook_done', withProgress: true },
  { key: 'render', label: 'Render', running: 'render_running', done: 'done', withProgress: true },
]

const order = [
  'created',
  'story_running', 'story_done',
  'images_running', 'images_done',
  'voice_running', 'voice_done',
  'subtitles_running', 'subtitles_done',
  'hook_running', 'hook_done',
  'render_running', 'done',
]

function stepState(step: Step): 'done' | 'running' | 'failed' | 'pending' {
  const s = props.status.state
  if (s === `failed_${step.key}`) return 'failed'
  if (s === step.running) return 'running'
  const idx = order.indexOf(s)
  if (idx >= 0 && idx >= order.indexOf(step.done)) return 'done'
  if (s.startsWith('failed_')) {
    // stages before the failed one are complete
    const failedIdx = steps.findIndex(st => `failed_${st.key}` === s)
    const myIdx = steps.findIndex(st => st.key === step.key)
    return myIdx < failedIdx ? 'done' : 'pending'
  }
  return 'pending'
}
</script>

<template>
  <ol class="space-y-3">
    <li
      v-for="step in steps"
      :key="step.key"
      class="flex items-center gap-3 rounded-xl border px-4 py-3"
      :class="{
        'border-emerald-500/40 bg-emerald-500/5': stepState(step) === 'done',
        'border-amber-400/60 bg-amber-400/5': stepState(step) === 'running',
        'border-red-500/60 bg-red-500/5': stepState(step) === 'failed',
        'border-zinc-800': stepState(step) === 'pending',
      }"
    >
      <span class="w-6 text-center text-lg">
        <template v-if="stepState(step) === 'done'">✓</template>
        <template v-else-if="stepState(step) === 'running'">
          <span class="inline-block animate-spin">◌</span>
        </template>
        <template v-else-if="stepState(step) === 'failed'">✗</template>
        <template v-else>·</template>
      </span>
      <div class="min-w-0">
        <div class="font-medium leading-tight">{{ step.label }}</div>
        <div v-if="step.note" class="text-xs text-zinc-500">{{ step.note }}</div>
      </div>
      <span
        v-if="step.withProgress && stepState(step) === 'running' && status.progress.total"
        class="text-sm text-zinc-400"
      >
        {{ status.progress.done }}/{{ status.progress.total }}
      </span>
      <div
        v-if="step.withProgress && stepState(step) === 'running' && status.progress.total"
        class="ml-auto h-1.5 w-40 overflow-hidden rounded bg-zinc-800"
      >
        <div
          class="h-full bg-amber-400 transition-all"
          :style="{ width: `${(status.progress.done / status.progress.total) * 100}%` }"
        />
      </div>
    </li>
  </ol>
</template>
