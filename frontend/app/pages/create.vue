<script setup lang="ts">
import type { Estimate } from '~/composables/useStoryApi'
import type { RefAsset } from '~/components/ReferenceAssets.vue'
import type { RelationshipHint } from '~/components/RelationshipBuilder.vue'

const api = useStoryApi()
const router = useRouter()

const form = reactive({
  topic: '',
  genre: 'sci-fi',
  tone: 'emotional, cinematic',
  target_audience: '18-35 general',
  duration_minutes: 7,
  visual_style: 'cinematic, moody lighting, film grain',
  narrator_style: 'deep, measured, documentary-like',
  narrator_voice: 'male',
  ending: 'bittersweet',
  language: 'en',
  image_style: 'cinematic_realistic',
  image_model: 'auto',
  video_format: 'youtube',
  subtitles: 'burned',
  hook_enabled: false,
})

const wordCount = computed(() => form.topic.trim() ? form.topic.trim().split(/\s+/).length : 0)
const topicValid = computed(() => wordCount.value >= 10 && wordCount.value <= 50)

// live cost estimate — updates as slider or model change
const estimate = ref<Estimate | null>(null)
watch(
  () => [form.duration_minutes, form.image_model, form.hook_enabled],
  async () => {
    estimate.value = await api
      .estimate({
        duration_minutes: form.duration_minutes,
        image_model: form.image_model,
        hook_enabled: form.hook_enabled,
      })
      .catch(() => null)
  },
  { immediate: true },
)

// reference image boxes (optional, user-owned photos) — see ReferenceAssets.vue
const refAssets = ref<RefAsset[]>([])
const rightsConfirmed = ref(false)

// optional relationships the user draws — villain→minion, uses object, etc.
const relationshipHints = ref<RelationshipHint[]>([])
const refNames = computed(() => refAssets.value.map(a => a.name))

// narrator voice: pre-fill from the saved server-side default, optionally
// save the current pick back as the default for future videos
const voiceOptions = [
  { value: 'male', label: 'Daniel (Male, English)', emoji: '🧔' },
  { value: 'female', label: 'Eve (Female, English)', emoji: '👩' },
]
const voiceLanguageLabel = 'English (EN)'
const voiceLanguageDescription = 'Narration and AI voice are generated in English only.'
const saveVoiceDefault = ref(false)
onMounted(async () => {
  try {
    form.narrator_voice = (await api.getSettings()).default_voice
  } catch { /* backend not up yet — keep the male default */ }
})

const surpriseTopics = [
  'A lighthouse keeper discovers the light he tends each night is the only thing keeping an ancient sea creature asleep beneath the waves',
  'A street food vendor in a floating city finds a recipe that lets people taste memories, and a stranger orders one she was meant to forget',
  'The last librarian on Earth guards books from a regime that erases history, until her own past appears in a banned manuscript',
  'A boy who repairs broken robots finds one that claims to remember a war that has not happened yet and begs him to hide it',
  'Two rival storm chasers get trapped inside a hurricane that never moves, and discover a village living quietly in its eye',
]

function surpriseMe() {
  form.topic = surpriseTopics[Math.floor(Math.random() * surpriseTopics.length)]!
  form.genre = ['sci-fi', 'fantasy', 'horror', 'drama', 'thriller', 'mystery'][Math.floor(Math.random() * 6)]!
  form.ending = ['happy', 'tragic', 'bittersweet', 'twist', 'open'][Math.floor(Math.random() * 5)]!
  form.image_style = ['cartoon_3d', 'anime', 'storybook_2d', 'cinematic_realistic'][Math.floor(Math.random() * 4)]!
}

const submitting = ref(false)
const error = ref('')

async function submit() {
  if (!topicValid.value) { error.value = 'Topic must be 10–50 words.'; return }
  if (refAssets.value.some(a => !a.name.trim())) {
    error.value = 'Please give every reference box a name (e.g. KAIRA).'
    return
  }
  // pictures are optional — a box without one is a hint (name + role) only
  const uploads = refAssets.value.filter(a => a.file)
  if (uploads.length && !rightsConfirmed.value) {
    error.value = 'Please confirm you own the rights to the uploaded images.'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    if (saveVoiceDefault.value) {
      await api.saveSettings({ default_voice: form.narrator_voice as 'male' | 'female' })
        .catch(() => {}) // saving the preference must never block the story
    }
    const relationship_hints = relationshipHints.value.filter(h => h.source && h.target)
    // boxes without a picture ride along in the body as hint-only references
    // (url stays empty); boxes with a picture are uploaded after creation
    const hintOnlyRefs = refAssets.value
      .filter(a => !a.file)
      .map(a => ({
        kind: a.kind,
        name: a.name.trim(),
        view: a.kind === 'character' ? a.view : 'front',
        mode: a.kind === 'location' ? a.mode : 'exact',
        role: a.kind === 'character' ? a.role : '',
        is_character_sheet: a.kind === 'character' ? a.is_character_sheet : false,
      }))
    const { story_id } = await api.createStory({
      ...form,
      language: 'en',
      relationship_hints,
      reference_images: hintOnlyRefs,
      autostart: uploads.length === 0,
    })
    if (uploads.length) {
      for (const a of uploads) {
        const fd = new FormData()
        fd.append('kind', a.kind)
        fd.append('name', a.name.trim())
        fd.append('view', a.kind === 'character' ? a.view : 'front')
        fd.append('mode', a.kind === 'location' ? a.mode : 'exact')
        fd.append('is_character_sheet', a.kind === 'character' && a.is_character_sheet ? 'true' : 'false')
        if (a.kind === 'character' && a.role) fd.append('role', a.role)
        fd.append('rights_confirmed', 'true')
        fd.append('file', a.file!)
        await api.uploadReference(story_id, fd)
      }
      await api.retry(story_id) // start the pipeline now that refs are attached
    }
    router.push(`/stories/${story_id}`)
  } catch (e: any) {
    error.value = e?.data?.detail ?? e?.message ?? 'Failed to create story'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="space-y-8" @submit.prevent="submit">
    <section>
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold">Create a story video</h1>
        <button
          type="button"
          class="rounded-lg border border-zinc-700 px-3 py-1.5 text-sm hover:border-amber-400 hover:text-amber-300"
          @click="surpriseMe"
        >
          🎲 Surprise me
        </button>
      </div>
      <textarea
        v-model="form.topic"
        rows="4"
        placeholder="What is your story about? Give it a clear conflict… (10–50 words)"
        class="mt-4 w-full rounded-xl border border-zinc-700 bg-zinc-900 p-4 text-base placeholder:text-zinc-500 focus:border-amber-400 focus:outline-none"
      />
      <div class="mt-1 text-right text-xs" :class="topicValid ? 'text-emerald-400' : 'text-zinc-500'">
        {{ wordCount }} / 10–50 words
      </div>
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">Genre</h2>
      <GenreChips v-model="form.genre" />
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">Ending</h2>
      <EndingChips v-model="form.ending" />
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">Video format</h2>
      <FormatCards v-model="form.video_format" />
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">Narrator voice · សំឡេងអ្នកនិយាយ</h2>
      <ChipSelect :options="voiceOptions" v-model="form.narrator_voice" />
      <div class="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm">
        <div class="flex items-center justify-between gap-3">
          <span class="font-medium text-zinc-200">Voice language</span>
          <span class="rounded-full border border-emerald-400/40 px-2.5 py-1 text-xs font-semibold text-emerald-300">
            {{ voiceLanguageLabel }}
          </span>
        </div>
        <p class="mt-1 text-xs text-zinc-400">{{ voiceLanguageDescription }}</p>
      </div>
      <label class="mt-2 flex items-center gap-2 text-xs text-zinc-400">
        <input v-model="saveVoiceDefault" type="checkbox" class="accent-amber-400">
        💾 រក្សាទុកជា default សម្រាប់វីដេអូក្រោយៗ (save as my default narrator)
      </label>
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">Duration & cost</h2>
      <DurationSlider v-model="form.duration_minutes" :estimate="estimate" />
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">Opening hook</h2>
      <label
        class="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition"
        :class="form.hook_enabled
          ? 'border-amber-400 bg-amber-400/5 ring-1 ring-amber-400/30'
          : 'border-zinc-800 hover:border-zinc-600'"
      >
        <input v-model="form.hook_enabled" type="checkbox" class="mt-1 accent-amber-400">
        <span class="min-w-0">
          <span class="block text-sm font-semibold text-zinc-200">
            Add Seedance 2.0 Mini hook video
          </span>
          <span class="mt-1 block text-xs text-zinc-500">
            Optional 10-15s cinematic intro generated from the finished story frame,
            with native dialogue/audio, then prepended before the main video.
          </span>
          <span v-if="estimate?.breakdown.hook" class="mt-2 block text-xs text-emerald-400">
            Hook estimate: ${{ estimate.breakdown.hook.toFixed(2) }}
          </span>
        </span>
      </label>
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">Image style</h2>
      <StyleCards v-model="form.image_style" />
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">
        Reference images &amp; cast
        <span class="text-xs font-normal text-zinc-500">
          (optional — add characters/objects, picture optional per box.
          Use 🔗 to draw relationship lines between boxes: villain → minion,
          who uses which object…)
        </span>
      </h2>
      <ReferenceAssets
        v-model="refAssets"
        :hints="relationshipHints"
        @error="(m) => (error = m)"
        @link="(h) => relationshipHints.push(h)"
      />
      <p class="mt-2 text-xs text-zinc-500">
        🪄 Character / Object: upload រូប front តែ 1 សន្លឹកគ្រប់គ្រាន់ — ប្រព័ន្ធនឹងបង្កើត
        side / back / pose / expression ដោយស្វ័យប្រវត្តិ ដើម្បីឱ្យ AI យល់រាងកាយពេញ
        (full body) គ្រប់ scene។ Location: default = 🌍 World style — គ្រប់ scene
        បង្កើតកន្លែង/មុំខុសៗគ្នា តែស្ថិតក្នុងពិភពតែមួយ (ឧ. ពិភពឆ្នាំ 3000)។ ជ្រើស 📍 Exact
        place បើចង់ឃើញកន្លែងដដែលទាំងស្រុងគ្រប់ scene (ឧ. ហាងរបស់អ្នក)។
      </p>
      <label v-if="refAssets.some(a => a.file)" class="mt-3 flex items-center gap-2 text-xs text-zinc-400">
        <input v-model="rightsConfirmed" type="checkbox" class="accent-amber-400">
        I own or have the rights to use these images. No photos of minors.
      </label>
    </section>

    <section>
      <h2 class="mb-2 text-sm font-medium text-zinc-300">
        Relationships
        <span class="text-xs font-normal text-zinc-500">
          (optional — connect who is whose villain, minion, child, or which
          object they use. The AI honors these and fills in the rest.)
        </span>
      </h2>
      <RelationshipBuilder v-model="relationshipHints" :names="refNames" />
    </section>

    <AdvancedAccordion
      v-model:image-model="form.image_model"
      v-model:tone="form.tone"
      v-model:target-audience="form.target_audience"
      v-model:visual-style="form.visual_style"
      v-model:narrator-style="form.narrator_style"
      v-model:subtitles="form.subtitles"
      :duration-minutes="form.duration_minutes"
      :hook-enabled="form.hook_enabled"
    />

    <p v-if="error" class="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-2 text-sm text-red-300">
      {{ error }}
    </p>

    <button
      type="submit"
      :disabled="submitting || !topicValid"
      class="w-full rounded-xl bg-amber-400 py-3 font-bold text-zinc-950 transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {{ submitting ? 'Creating…' : `🎬 Generate video${estimate ? ` — $${estimate.total.toFixed(2)}` : ''}` }}
    </button>
  </form>
</template>
