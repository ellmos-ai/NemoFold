# NemoFold Jury Design Set

Claim-safe visual asset suite with deterministic SVG sources and host-rendered PNGs for NemoFold, a private, evidence-first document agent for explicitly approved folders.

---

## 1. Design Rationale & Concepts

This visual suite provides three original evidence-led design directions plus three cinematic Nautilus brand extensions tailored for YouTube and Devpost thumbnails. Every graphic adheres strictly to implemented local-first capabilities and verified product invariants.

### Concept A — `trust-voyage`
* **Theme**: Oceanic depth, calm negative space, and local authority.
* **Hero Art**: Atmospheric composition based on `sources/trust-voyage-background.png`, graded with dark teal scrim gradients (`#031218` to `#0B4A59`) and a soft radial vignette.
* **Composition**: Clean left-aligned editorial hierarchy paired with a structured *Local-First Trust Matrix* card highlighting approved folder boundaries (`Unapproved transfer fails closed`), persistent document memory (`Deterministic index, content hashes & action ledgers`), and local quote verification.
* **Status**: `Local core ready · Live cloud proof open`

### Concept B — `evidence-ledger`
* **Theme**: Light editorial evidence board and document traceability.
* **Canvas**: Warm ivory canvas (`#F7F1E7`) with subtle coordinate grid markings and coral accent trim.
* **Composition**: High-contrast editorial typography paired with generic structural schema cards describing implemented product contracts:
  * `QUESTION`: Document query scoped to explicitly approved folders.
  * `SELECTED SOURCE CHUNK`: Bounded context with character offsets and local extraction with source IDs, character offsets, and chunk boundaries.
  * `EXACT QUOTE + SOURCE LOCATION`: Verifiable verbatim passage pinned to source ID and line or page range; every promoted claim keeps an exact quote and source locator, with conflict hints remaining visible.
  * `COVERAGE: READ · CITED · UNSUPPORTED · UNREADABLE`: Auditable folder coverage accounting without silent omissions; run ledger and action journal stay local.
  * `REPORT CONTRACT → MD · TXT · PDF · DOCX · ODT`: Validated multi-format export with exact quotes and source locations; structured outputs for reports, receipts, and run ledgers; reversible file operations with safety gates.
* **Readability Optimization**: Thumbnail and social variants are simplified so no rendered font is smaller than 10 px, preserving structural labels and concise single-line descriptions per row.
* **Status**: `Local core ready`

### Concept C — `bounded-reasoning`
* **Theme**: Dark split-boundary campaign graphic illustrating local authority dominance.
* **Canvas**: Dark blueprint slate background (`#021218` to `#072F3A`) with technical accent guides.
* **Composition**: Asymmetric architectural split diagram:
  * **Zone A (Local Authority — ~56% dominant width)**: Approved files and memory, policy & privacy gates (`Fail closed: unapproved stays local`), local evidence verifiers, and the guarantee `NO ORIGINAL FILES OR HOST PATHS`.
  * **Zone B (Bounded Zone — ~34% bounded width)**: NVIDIA Nemotron on Nebius with strictly bounded parameters (`Optional reasoning`, `Selected context`, `Pseudonymized`, `Bounded budget`) and a return path leading directly back into local verification.
* **Status**: `Cloud proof: pending`

---

## 2. Brand Direction & Palette

| Token | Hex Value | Semantic Application |
| :--- | :--- | :--- |
| **Deep Teal Dark** | `#073B49` | Primary background fills, headers, brand badges |
| **Deep Teal Light** | `#0B4A59` | Secondary cards, container borders, subtle fills |
| **Warm Ivory** | `#F7F1E7` | Light editorial canvas (Concept B), primary text on dark cards |
| **Coral Accent** | `#FF6B4A` | Brand fold accent, quotation callouts, warning indicators |
| **Cyan Accent** | `#5AD2D0` | Eyebrow badges, tech highlights, trust boundary lines |
| **Emerald Verification** | `#1F9D72` | Verified status chips, checkmarks, local security badges |
| **Slate Primary** | `#0F172A` | Primary typography on ivory backgrounds |
| **Slate Secondary** | `#334155` | Supporting editorial text and metadata labels |

---

## 3. Typography

* **Primary Sans-Serif**: `Segoe UI, -apple-system, Arial, sans-serif` — Used for eyebrows, product brand titles, metadata labels, status chips, and matrix cards.
* **Editorial Serif**: `Georgia, 'Times New Roman', serif` — Used for main campaign headlines and verbatim quotation highlights for restrained editorial emphasis.

---

## 4. Safe-Claim Policy & Language Rules

In accordance with product truth guidelines:
1. **Working Tagline**: `Your files. Your rules. Your agent.` (verbatim).
2. **Approved Status Terms**:
   * `Local core ready`
   * `Live cloud proof open`
   * `Cloud proof: pending`
3. **Strict Negative Invariants**:
   * No claims of customers, production deployments, public availability, or benchmark numbers.
   * No simulation of completed competition runs, fake report hashes, fabricated line numbers, or artificial test metrics.
   * No absolute anti-hallucination guarantees (e.g. removed "without hallucinations" and "100% exact grounding").
   * No unproven assertions regarding cloud memory (removed "Stateless execution" and "Zero memory state"; replaced with verified properties: "Optional reasoning", "Selected context", "Pseudonymized", "Bounded budget").
   * Egress guarantees state `Fail closed: unapproved stays local`, `Unapproved transfer fails closed`, and `NO ORIGINAL FILES OR HOST PATHS`.

---

## 5. Provenance & Generation Path

### Reference Inputs in `sources/`
* `sources/nemofold-console-reference.png`: Product console reference and brand direction.
* `sources/nemofold-trust-boundary-reference.svg`: Architectural trust boundary reference.
* `sources/trust-voyage-background.png`: Text-free hero bitmap generated via the built-in image pipeline.
  * **Tool**: `OpenAI built-in imagegen`
  * **Taxonomy**: `stylized-concept`
  * **Note**: The project copy came from the generated output and was retained under the stable source filename.

### Final Image Generation Prompt
```text
Use case: stylized-concept
Asset type: 16:9 hackathon product banner background for NemoFold, a private evidence-first document agent
Primary request: text-free abstract visual suggesting a local trust boundary, persistent document memory, and a carefully bounded reasoning channel; elegant editorial technology art, not a UI screenshot
Scene/backdrop: deep midnight teal field with layered translucent document sheets, subtle concentric sonar rings, one warm coral bounded signal crossing a thin luminous boundary and returning as a verified emerald trace
Style/medium: premium restrained 3D/vector-like editorial illustration with crisp geometry and subtle paper texture
Composition/framing: wide landscape, main geometry weighted to the right, generous dark negative space on the left for later deterministic typography
Lighting/mood: calm, trustworthy, precise, private
Color palette: deep teal #073B49 and #0B4A59, warm ivory #F7F1E7, coral #FF6B4A, cyan #5AD2D0, emerald #1F9D72
Constraints: no text, no letters, no logos, no watermarks, no people, no brand marks, no fake application interface, no decorative clutter; leave the left 45 percent clean enough for typography
```

### Generation Engine
* `generate_assets.py`: Deterministic Python generator producing pure SVG vector files and rendering host-rendered raster PNGs using headless Google Chrome / Microsoft Edge (`--headless=new --screenshot`).
* Verified using Python Pillow (`PIL.Image`).

---

## 6. Deliverable Inventory & Asset Matrix

| Concept | Variant | Format | SVG Source | PNG Render | Target Dimensions | Verified Actual | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Trust Voyage** | Banner | SVG / PNG | `trust-voyage-banner.svg` | `trust-voyage-banner.png` | 1600 × 900 | 1600 × 900 | **VERIFIED** |
| **Trust Voyage** | Thumbnail | SVG / PNG | `trust-voyage-thumbnail.svg` | `trust-voyage-thumbnail.png` | 1280 × 720 | 1280 × 720 | **VERIFIED** |
| **Trust Voyage** | Social | SVG / PNG | `trust-voyage-social.svg` | `trust-voyage-social.png` | 1200 × 630 | 1200 × 630 | **VERIFIED** |
| **Evidence Ledger** | Banner | SVG / PNG | `evidence-ledger-banner.svg` | `evidence-ledger-banner.png` | 1600 × 900 | 1600 × 900 | **VERIFIED** |
| **Evidence Ledger** | Thumbnail | SVG / PNG | `evidence-ledger-thumbnail.svg` | `evidence-ledger-thumbnail.png` | 1280 × 720 | 1280 × 720 | **VERIFIED** |
| **Evidence Ledger** | Social | SVG / PNG | `evidence-ledger-social.svg` | `evidence-ledger-social.png` | 1200 × 630 | 1200 × 630 | **VERIFIED** |
| **Bounded Reasoning** | Banner | SVG / PNG | `bounded-reasoning-banner.svg` | `bounded-reasoning-banner.png` | 1600 × 900 | 1600 × 900 | **VERIFIED** |
| **Bounded Reasoning** | Thumbnail | SVG / PNG | `bounded-reasoning-thumbnail.svg` | `bounded-reasoning-thumbnail.png` | 1280 × 720 | 1280 × 720 | **VERIFIED** |
| **Bounded Reasoning** | Social | SVG / PNG | `bounded-reasoning-social.svg` | `bounded-reasoning-social.png` | 1200 × 630 | 1200 × 630 | **VERIFIED** |

* Machine-readable metadata is maintained in `manifest.json`.

---

## 7. Verification & Technical Quality Gates

### Generation Command
```bash
python generate_assets.py
```

### Verification Script
```python
import json, os
from PIL import Image

# 1. Verify JSON validity
with open('manifest.json', 'r', encoding='utf-8') as f:
    manifest = json.load(f)
assert len(manifest['concepts']) == 3

# 2. Verify all 9 PNG assets
expected_dims = {
    'trust-voyage-banner.png': (1600, 900),
    'trust-voyage-thumbnail.png': (1280, 720),
    'trust-voyage-social.png': (1200, 630),
    'evidence-ledger-banner.png': (1600, 900),
    'evidence-ledger-thumbnail.png': (1280, 720),
    'evidence-ledger-social.png': (1200, 630),
    'bounded-reasoning-banner.png': (1600, 900),
    'bounded-reasoning-thumbnail.png': (1280, 720),
    'bounded-reasoning-social.png': (1200, 630),
}

for fname, dims in expected_dims.items():
    with Image.open(fname) as im:
        assert im.size == dims
        assert im.mode == 'RGB'
```

### Inspection Results & Residual Risk
* **Dimension & Mode Parity**: 100% exact match across all 9 host-rendered raster targets (no letterboxing, distortion, or scale shift).
* **Typography & Visual Quality**: Contrast and clipping were visually inspected; no formal WCAG contrast measurement was performed. In `evidence-ledger` thumbnail and social variants, cards were simplified so no rendered font is smaller than 10 px.
* **Claim-Safe Compliance**: Full compliance with product truth and safe-claim policies. All test artifacts removed.
* **Residual Visual Uncertainty**: Platform thumbnail downscaling may reduce secondary card-detail readability; primary headline/status copy remains the selection criterion. User preference between the three variants remains open.

---

## 8. Nautilus Brand Extensions

The extension turns the project name into a repeatable visual story: Captain Nemo and an original Victorian-futurist Nautilus descend into a private document archive while the existing NemoFold fold mark, palette, and exact wordmark remain constant.

### Reusable Brand Anchor

The stable lockup combines the existing three-color fold with a porthole/sonar ring and the exact `NemoFold` wordmark. Transparent SVG and PNG versions are provided for both dark and light surfaces:

- `brand/nemofold-nautilus-lockup-dark-surface.svg`
- `brand/nemofold-nautilus-lockup-dark-surface.png`
- `brand/nemofold-nautilus-lockup-light-surface.svg`
- `brand/nemofold-nautilus-lockup-light-surface.png`

The wordmark is deliberately composited with a fixed layout rather than generated inside the artwork. This preserves spelling, typography, and placement across every future asset; PNG bytes are reproducible on the same pinned Pillow/font stack.

### Platform Assets

| Direction | YouTube 16:9 | Devpost 4:3 | Primary hook |
| :--- | :--- | :--- | :--- |
| **Nautilus Descent** | `nautilus-descent-youtube.png` · 1280 × 720 | `nautilus-descent-devpost.png` · 1200 × 900 | `DIVE INTO YOUR DOCUMENTS` |
| **Captain Nemo Observatory** | `captain-nemo-observatory-youtube.png` · 1280 × 720 | `captain-nemo-observatory-devpost.png` · 1200 × 900 | `YOUR FILES. YOUR RULES.` |
| **Fold Depth** | `fold-depth-youtube.png` · 1280 × 720 | `fold-depth-devpost.png` · 1200 × 900 | `DIVE DEEP. STAY LOCAL.` |

Brand-title variants reverse the hierarchy: the reusable `NemoFold` mark is the large title and the campaign line becomes a compact subtitle hook.

| Direction | YouTube 16:9 | Devpost 4:3 | Subtitle hook |
| :--- | :--- | :--- | :--- |
| **Nautilus Descent** | `nautilus-descent-brand-youtube.png` · 1280 × 720 | `nautilus-descent-brand-devpost.png` · 1200 × 900 | `Dive into your documents.` |
| **Captain Nemo Observatory** | `captain-nemo-observatory-brand-youtube.png` · 1280 × 720 | `captain-nemo-observatory-brand-devpost.png` · 1200 × 900 | `Your files. Your rules.` |
| **Fold Depth** | `fold-depth-brand-youtube.png` · 1280 × 720 | `fold-depth-brand-devpost.png` · 1200 × 900 | `Dive deep. Stay local.` |

Recommended first-use pairing:

- **YouTube:** `nautilus-descent-brand-youtube.png` when brand recognition is primary; `nautilus-descent-youtube.png` remains the strongest action-led alternative.
- **Devpost:** `captain-nemo-observatory-brand-devpost.png` for the clearest Captain Nemo connection with an immediate project-name anchor.

### Production Path

- Master illustrations: OpenAI built-in image generation, stored text-free under `sources/`.
- Normalized production prompts: `nautilus-prompts.md`.
- Exact logo and platform copy: `generate_nautilus_assets.py` using fixed-layout Pillow composition.
- Machine-readable inventory: `nautilus-manifest.json`.
- Safe claims: no customer, deployment, completed cloud-run, or benchmark assertions appear in the artwork.

Rebuild and verify:

```powershell
python generate_nautilus_assets.py
```

The generator checks all twelve platform PNGs for their required dimensions and RGB mode, and verifies the two reusable lockup PNGs as 1600 × 400 RGBA images with transparency.

Font lookup is portable across the supported production stacks: Segoe UI/Georgia on Windows, DejaVu Sans/Serif on Linux, and Arial/Georgia on macOS. Install one complete listed pair before rebuilding. Exact PNG bytes are expected to match only when Pillow, FreeType, fonts, and compression settings are pinned to the same host stack.

### Scene canon additions (2026-08-31)

Five text-free scene masters were added under `sources/` for the routed work areas,
following the user's scene canon (decision D-023): `scene-analysis.png` (brass
porthole with luminescent deep-sea life), `scene-connections.png` (the surfaced
Nautilus on a sunny day), `scene-artifacts.png` (the Nautilus library),
`scene-routines.png` (the echo-sounder station), and `scene-governance.png` (the
command bridge). Generated via the Gemini image pipeline (agy) on 2026-08-31 from
operator-written scene briefs, curated by the operator, resized to 1672x941, and
shipped as optimized JPEGs in `src/nemofold/web/assets/`. No text is rendered inside
the artwork; all figures are fictional crew. The Document Center scene keeps the
existing `trust-voyage-background.png`.
