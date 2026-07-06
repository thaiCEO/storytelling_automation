---
name: asset-bible
description: Create and manage the Asset Bible (characters, locations, objects, style) that guarantees visual consistency across all scenes. Use this skill whenever working on character/location/object definitions, visual DNA writing, consistency problems between images, or user-uploaded reference images for characters, locations, or objects.
---

# Asset Bible (Stage 2 — inside the story engine)

Single source of truth for everything visual. Every image prompt is built by
code from this file — never free-hand.

## Schema (`bible.json`)

```json
{
  "style": "cinematic sci-fi, moody lighting, film grain, anamorphic",
  "characters": [
    {
      "id": "char_rot",
      "name": "Rot",
      "role": "protagonist",
      "visual_dna": "30-year-old Khmer male hunter, scarred left cheek, short black hair, worn leather armor with glowing blue circuit lines, cybernetic left arm",
      "reference_image_url": null
    }
  ],
  "locations": [
    {
      "id": "loc_ruins",
      "name": "Dead City",
      "visual_dna": "ruined megacity overgrown with vines, broken skyscrapers, orange dusk haze",
      "reference_image_url": null
    }
  ],
  "objects": [
    {
      "id": "obj_blade",
      "name": "Plasma Blade",
      "visual_dna": "curved sword with translucent orange energy edge, black hilt",
      "reference_image_url": null
    }
  ],
  "relationships": [
    { "source": "char_vex", "target": "char_krail", "type": "commands", "label": "iron-fisted father" },
    { "source": "char_rot", "target": "obj_blade", "type": "uses", "label": "" }
  ]
}
```

## Roles & relationships

Every character carries a `role` and the bible carries a top-level
`relationships` array — both power the `/stories/{id}/bible` graph page and
give Pass 3/4 the conflict logic (enemies drive conflict, subordinates act on
their leader's orders).

**Roles** (`CHARACTER_ROLES` in `models.py`): `protagonist` |
`deuteragonist` | `villain` | `villain_lieutenant` | `minion` | `mentor` |
`ally` | `love_interest` | `supporting`. Exactly one protagonist per story.

**Relationship types** (`RELATIONSHIP_TYPES`): `parent_of` | `sibling_of` |
`commands` | `ally_of` | `enemy_of` | `loves` | `mentors` | `owns` | `uses`.

Direction conventions — ONE edge per pair, never reciprocated:

- `parent_of` = parent→child (covers family lines / descendants)
- `commands` = leader→subordinate (whole villain chain:
  villain → villain_lieutenant → minion)
- `mentors` = mentor→student; `loves` = who→whom (`label: "mutual"` if returned)
- `owns` / `uses` = character→object ONLY; locations never appear in
  relationships
- symmetric types (`sibling_of`, `ally_of`, `enemy_of`) emitted once

Both fields are **soft-validated** (`normalize_bible()` in
`story_engine.py`), never hard-failed: unknown roles fall back to
`supporting`, aliases are mapped (`hero`→protagonist, `child_of`→flipped
`parent_of`, `serves`→flipped `commands`, …), and edges with unknown ids,
location endpoints, self-loops or unknown types are dropped with a
`bible_normalized` warning in `pipeline.log`. Old bibles without these fields
parse fine (role defaults to `supporting`, relationships to `[]`).

**User-specified roles & relationships (input-time).** On `/create` the user
can optionally tag a character reference box with a `role` and draw
relationships (villain→minion, uses object, parent→child…) in the
RelationshipBuilder. These arrive as `reference_images[].role` and
`StoryInput.relationship_hints` (keyed by NAME). Pass 2 receives a
"USER-SPECIFIED ROLES & RELATIONSHIPS (honor these)" block; then
`apply_user_hints()` (before `normalize_bible`) overrides the matched
character's role and force-appends each drawn edge, resolving names→ids by
fuzzy match. Unresolvable hints are skipped with a `bible_user_hint` warning.
Everything is optional — no hints = full LLM auto-generation.

## Visual DNA writing rules (enforce in the LLM prompt)

1. Concrete nouns + measurable attributes only. Ban vague words:
   "beautiful", "cool", "interesting", "unique".
2. 15–35 words per asset. Long enough to lock identity, short enough to fit
   the image prompt budget.
3. Include for characters: age, ethnicity/build, face detail, hair, outfit,
   one signature feature (the thing viewers recognize).
4. Include for locations: architecture/terrain, scale, color palette,
   atmosphere. NO time-of-day here — that lives per-scene.
5. Objects: shape, material, color, one distinctive detail.
5b. **Match the chosen `image_style`** (see `skills/image-pipeline.md`):
   `bible.style` starts from that preset's style anchor, and visual_dna
   wording must fit it — e.g. for `cartoon_3d` describe "rounded friendly
   face, big expressive eyes"; for `storybook_2d` describe "soft pencil line,
   watercolor wash, childlike proportions"; for `cinematic_realistic` use
   photographic language, not cartoon/anime wording. Tell the LLM the chosen
   style in the Bible prompt.
6. Keep asset counts small: ≤6 characters (hard cap — use the FEWEST the
   story needs, 2–4 is typical; go higher only for hierarchies/ensembles),
   ≤4 locations, ≤3 objects for a 7-minute video. More assets = more
   consistency risk.

## Bible generation prompt (Pass 2)

The authoritative prompt is `PASS2_SYSTEM` in
`backend/app/pipeline/story_engine.py`. Key rules (abridged):

```
- Derive every asset from the premise. Max 6 characters (use the FEWEST the
  story needs — 2-4 is typical), 4 locations, 3 objects.
- Every character gets a "role" (one of the 9); exactly one protagonist.
  Henchmen premise → villain -commands-> villain_lieutenant -commands-> minion.
- "relationships": every character in at least one relationship; types and
  directions per the conventions above; source/target must be defined ids;
  locations never appear; symmetric types once only.
- visual_dna: 15-35 words, concrete and repeatable. No vague adjectives.
  No time-of-day or weather in location DNA.
- style: one line combining the user's visual_style with genre-appropriate
  cinematography language.
- If a USER REFERENCE IMAGE is listed for an asset hint, still write full
  visual_dna describing what is IN that image (you will be shown the image),
  and set reference_image_url to the given URL.
```

## User-uploaded reference images (supported!)

Users may upload their own photo/art for a character, location, or object
(e.g. their own face, their shop, a product).

Flow:

1. **Upload (Nuxt → FastAPI):** `POST /api/stories/{id}/references`
   (multipart). FastAPI forwards to Atlas Cloud
   `POST /api/v1/model/uploadMedia` → returns a public `download_url`.
   Store `{asset_hint, url}` on the story input.
2. **Bible pass:** send the image to Sonnet (vision) so it writes accurate
   `visual_dna` describing the upload, and set `reference_image_url`.
3. **Image pipeline consequence:** any scene whose cast/location/props include
   an asset with `reference_image_url` MUST use the **edit endpoint**
   (`openai/gpt-image-2/edit`) with `images: [reference_image_url, ...]` and
   `input_fidelity: "high"` instead of plain text-to-image. Details in
   `skills/image-pipeline.md`.
4. Validation: uploaded files ≤10 MB, JPG/PNG only, reject faces of minors,
   and confirm the user owns/has rights to the image (checkbox in UI).

### UI + API shape (reference boxes)

Each reference is a **box** on `/create`: kind (character / location / object)
+ user-typed **name** (e.g. "KAIRA") + optionally **one picture** shown as the
box preview. `POST /api/stories/{id}/references` form fields:
`kind`, `name`, `view` (characters only), `role` (characters, optional),
`rights_confirmed`, `file`.

**Picture is optional.** A box without a picture is a *hint-only* reference:
it rides in the `POST /api/stories` body as a `ReferenceImage` with `url=""`
(never sent to vision) — its name + `role` still steer Pass 2 via
`_user_hint_block()`. Character boxes carry an optional `role` dropdown, and
users can **draw relationship lines between boxes** (🔗 click-to-link +
table rows) — sent as `StoryInput.relationship_hints`
(`{source, target, type, label}` keyed by box NAME). After Pass 2,
`apply_user_hints()` fuzzy-matches the names to generated assets, forces the
user's roles, and wires the drawn edges into `bible.relationships`
(unresolvable hints are skipped with a `bible_user_hint` warning in
`pipeline.log`).

`view` values: `front` (master identity — becomes the asset's
`reference_image_url`), `side`, `back`, `pose`, `expression`. A character can
have several boxes with the same name and different views; non-front views are
appended after the master image in `scene_reference_urls()` (images.py) so
profile/back/action shots stay on-model.

## Multi-view character reference pack (prompt templates)

When the user has no photo, generate the reference set with these prompts
(text-to-image, 16:9), then upload each result as a reference box with the
matching `view`. Example pack for "KAIRA":

**`ref_front` — master identity → `view=front`**

```
Full-body FRONT view character reference of KAIRA, a battle-scarred Khmer woman
around 30, athletic and lean, short dark undercut hair, thin diagonal scar on the
left cheek, weathered brown skin. Matte-black tactical exo-armor with thin glowing
teal energy lines, torn dark grey hunter's cloak over one shoulder, folding plasma
glaive on her back, magnetic rail-pistol at hip. Neutral standing pose facing camera,
clean neutral grey studio background, even soft reference lighting, full body head to
boots, photorealistic, character design reference, 16:9. MASTER IDENTITY REFERENCE.
```

**`ref_side` — for side-scroll spine → `view=side`**

```
Full-body exact LEFT-PROFILE side view of KAIRA (same identity), neutral stance,
precise 90-degree profile, clean neutral grey studio background, even soft lighting,
full body, sharp readable silhouette, photorealistic, character reference, 16:9.
```

**`ref_back` → `view=back`**

```
Full-body BACK view of KAIRA (same identity), showing the plasma glaive across her
back, the hood and drape of the torn grey cloak, teal energy lines down the spine.
Neutral stance, clean neutral grey studio background, even lighting, full body,
photorealistic, character reference, 16:9.
```

**`pose_run` — main chase action → `view=pose`**

```
KAIRA (same identity) in a full SIDE-PROFILE dynamic sprinting pose, mid-stride,
leaning forward hard, cloak and hair trailing, urgent. Left-facing profile for
side-scroll chase, slight motion blur on limbs, clean background for compositing,
photorealistic, action reference, 16:9.
```

**`expr_fear` — reaction insert → `view=expression`**

```
Tight CLOSE-UP portrait of KAIRA's face (same identity, cheek scar), eyes wide with
fear, sharp intake of breath, rain and sweat on her skin, faint red glow on her face.
Shallow depth of field, cold key light, photorealistic, cinematic, 16:9.
```

**`expr_determined` — hero beat → `view=expression`**

```
Tight CLOSE-UP portrait of KAIRA's face (same identity, cheek scar), jaw set, brows
lowered, fierce determined stare, teal rim light on one side, rain on her skin.
Shallow depth of field, photorealistic, cinematic, 16:9.
```

Pack rules:

1. `ref_front` FIRST — every later prompt says "(same identity)" and is
   generated via the **edit endpoint with ref_front attached** so the views
   actually match. Never generate views independently.
2. Neutral grey studio background + even lighting for ref_* views; drama
   (rain, rim light) only in pose/expression shots.
3. Repeat the signature feature (cheek scar, teal energy lines) in every
   prompt — it is the identity lock.
4. One picture per box in the UI; the front view is the picture the box
   shows and the master `reference_image_url`.

## Per-scene dynamic state (lives in script.json, not the Bible)

- `time_of_day` + `weather` — continuity-tracked scene to scene.
- `character_state` — 2-4 words ("exhausted, bleeding") appended after the
  character's visual_dna in the final prompt.
- `camera` — shot grammar; rule: never two consecutive close-ups.

## Common failure → fix

| Symptom | Fix |
|---|---|
| Character's face drifts between scenes | visual_dna too short — add face detail + signature feature; or attach a generated scene-1 image as reference for all later scenes via the edit endpoint |
| Location looks different every scene | time-of-day leaked into location DNA — move it to per-scene fields |
| Style flip-flops (photo vs anime) | `style` string missing from prompt builder — it must be appended to EVERY prompt |
