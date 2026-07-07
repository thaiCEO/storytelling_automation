export interface Estimate {
  total: number
  breakdown: { llm: number; images: number; tts: number; hook?: number }
  scenes: number
  words: number
}

export interface StoryStatus {
  story_id: string
  state: string
  progress: { done: number; total: number }
  error: string | null
  retryable: boolean
  warnings: string[]
  cost: { total: number; by_stage: Record<string, number> }
  estimate: Estimate | null
  over_budget: boolean
}

export interface BibleAsset {
  id: string
  name: string
  visual_dna: string
  reference_image_url: string | null
}

export interface BibleCharacter extends BibleAsset {
  role: string
}

export interface BibleRelationship {
  source: string
  target: string
  type: string
  label: string
}

export interface StoryBible {
  style: string
  world: string
  characters: BibleCharacter[]
  locations: BibleAsset[]
  objects: BibleAsset[]
  relationships: BibleRelationship[]
}

export interface BibleResponse {
  story_id: string
  title: string | null
  state: string
  bible: StoryBible
}

export interface StoryResult {
  story_id: string
  video_url: string
  thumbnail_url: string
  srt_url: string | null
  cost: { total: number; by_stage: Record<string, number> }
  warnings: string[]
}

export const useStoryApi = () => ({
  estimate: (params: { duration_minutes: number; image_model: string; hook_enabled?: boolean }) =>
    $fetch<Estimate>('/api/estimate', { params }),

  createStory: (body: Record<string, unknown>) =>
    $fetch<{ story_id: string }>('/api/stories', { method: 'POST', body }),

  uploadReference: (id: string, form: FormData) =>
    $fetch<{
      kind: string
      name: string
      view: string
      url: string
      is_character_sheet: boolean
    }>(`/api/stories/${id}/references`, {
      method: 'POST',
      body: form,
    }),

  getStatus: (id: string) => $fetch<StoryStatus>(`/api/stories/${id}/status`),

  retry: (id: string) => $fetch(`/api/stories/${id}/retry`, { method: 'POST' }),

  getSettings: () => $fetch<{ default_voice: 'male' | 'female' }>('/api/settings'),

  saveSettings: (body: { default_voice: 'male' | 'female' }) =>
    $fetch('/api/settings', { method: 'PUT', body }),

  getResult: (id: string) => $fetch<StoryResult>(`/api/stories/${id}/result`),

  getBible: (id: string) => $fetch<BibleResponse>(`/api/stories/${id}/bible`),
})
