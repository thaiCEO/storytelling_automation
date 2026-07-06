<script setup lang="ts">
const props = defineProps<{
  imageModel: string
  tone: string
  targetAudience: string
  visualStyle: string
  narratorStyle: string
  subtitles: string
  durationMinutes: number
  hookEnabled: boolean
}>()

const emit = defineEmits<{
  'update:imageModel': [v: string]
  'update:tone': [v: string]
  'update:targetAudience': [v: string]
  'update:visualStyle': [v: string]
  'update:narratorStyle': [v: string]
  'update:subtitles': [v: string]
}>()

type ImageModelOption = {
  value: string
  label: string
  hint: string
  editModel?: string
  editRunCost?: string
}

const open = ref(false)
const api = useStoryApi()

// Live per-model cost next to each radio option.
const modelCosts = ref<Record<string, number>>({})
watch(
  () => [props.durationMinutes, props.hookEnabled],
  async (mins) => {
    const models = ['auto', 'gpt-image-2', 'nano-banana-2', 'flux-schnell', 'grok-imagine']
    const results = await Promise.all(
      models.map(m => api.estimate({
        duration_minutes: Number(mins[0]),
        image_model: m,
        hook_enabled: Boolean(mins[1]),
      }).catch(() => null)),
    )
    const costs: Record<string, number> = {}
    models.forEach((m, i) => { if (results[i]) costs[m] = results[i]!.breakdown.images })
    modelCosts.value = costs
  },
  { immediate: true },
)

const imageModels: ImageModelOption[] = [
  { value: 'auto', label: 'Auto (hybrid)', hint: 'best quality-per-dollar - characters via Nano Banana 2, landscapes via GPT Image 2' },
  { value: 'gpt-image-2', label: 'GPT Image 2', hint: 'cheapest' },
  { value: 'nano-banana-2', label: 'Nano Banana 2', hint: 'strongest character consistency, native 16:9' },
  { value: 'flux-schnell', label: 'Flux Schnell', hint: 'fast Black Forest Labs model; references use Flux 2 Pro Edit' },
  {
    value: 'grok-imagine',
    label: 'Grok Imagine',
    hint: 'premium xAI model; references use Grok Imagine Edit',
    editModel: 'xai/grok-imagine-image/edit',
    editRunCost: '$0.022 per run',
  },
]
</script>

<template>
  <div class="rounded-xl border border-zinc-800">
    <button
      type="button"
      class="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-zinc-300"
      @click="open = !open"
    >
      Advanced
      <span class="text-zinc-500">{{ open ? '^' : 'v' }}</span>
    </button>

    <div v-show="open" class="space-y-5 border-t border-zinc-800 p-4">
      <div>
        <div class="mb-2 text-sm font-medium text-zinc-300">Image model</div>
        <label
          v-for="m in imageModels"
          :key="m.value"
          class="mb-1 flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-zinc-900"
        >
          <input
            type="radio"
            name="image_model"
            :value="m.value"
            :checked="imageModel === m.value"
            class="mt-0.5 accent-amber-400"
            @change="emit('update:imageModel', m.value)"
          >
          <span class="min-w-0 flex-1">
            <span class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>{{ m.label }}</span>
              <span v-if="modelCosts[m.value] != null" class="text-xs text-emerald-400">
                ~${{ modelCosts[m.value]!.toFixed(2) }} images
              </span>
            </span>
            <span class="mt-0.5 block text-xs text-zinc-500">{{ m.hint }}</span>
            <span v-if="m.editModel" class="mt-1 block break-words text-xs text-amber-300">
              {{ m.editModel }} - {{ m.editRunCost }}
            </span>
          </span>
        </label>
      </div>

      <label class="flex items-center gap-2 text-sm text-zinc-300">
        <input
          type="checkbox"
          class="accent-amber-400"
          :checked="subtitles === 'burned'"
          @change="emit('update:subtitles', ($event.target as HTMLInputElement).checked ? 'burned' : 'off')"
        >
        Subtitles on video
      </label>

      <div class="grid grid-cols-2 gap-3">
        <label class="text-sm">
          <span class="text-zinc-400">Tone</span>
          <input
            :value="tone"
            class="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm"
            @input="emit('update:tone', ($event.target as HTMLInputElement).value)"
          >
        </label>
        <label class="text-sm">
          <span class="text-zinc-400">Target audience</span>
          <input
            :value="targetAudience"
            class="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm"
            @input="emit('update:targetAudience', ($event.target as HTMLInputElement).value)"
          >
        </label>
        <label class="text-sm">
          <span class="text-zinc-400">Visual style</span>
          <input
            :value="visualStyle"
            class="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm"
            @input="emit('update:visualStyle', ($event.target as HTMLInputElement).value)"
          >
        </label>
        <label class="text-sm">
          <span class="text-zinc-400">Narrator style</span>
          <input
            :value="narratorStyle"
            class="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm"
            @input="emit('update:narratorStyle', ($event.target as HTMLInputElement).value)"
          >
        </label>
      </div>

      <div>
        <div class="mb-2 text-sm font-medium text-zinc-300">Style presets</div>
        <StylePresets
          @apply="(p) => {
            emit('update:tone', p.tone)
            emit('update:visualStyle', p.visual_style)
            emit('update:narratorStyle', p.narrator_style)
          }"
        />
      </div>
    </div>
  </div>
</template>
