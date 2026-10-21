# Local Deck Maker

Generates editable `.pptx` presentations with a local LLM (Ollama) and a **library of 64
slide layout templates** rendered on the ComfyUI background.

> **Code flow:** [`CODE_FLOW.md`](CODE_FLOW.md) documents which function runs when and what
> it does — with the rendered diagram [`code_flow.png`](code_flow.png)
> (regenerate with `python generate_code_flow_diagram.py`).

## How it works
1. **Outline**: one LLM call returns a title + slide titles (you can edit them).
2. **Slides**: one LLM call per slide returns structured JSON (title, bullets, notes).
3. **Layouts**: a second LLM call picks the layout template that fits each slide. The
   recommendation is shown to you and can be changed at any time from the slide's dropdown
   or by clicking a template in that slide's own gallery.
4. **Render**: `python-pptx` builds the deck with native, editable shapes, using the chosen
   template and the ComfyUI background. A PNG screenshot of every slide is written back to
   the project folder so you can see the result immediately.

## The slide workspace

Each slide has its own panel, and inside it its own **layout selector**:

```
Slide 1
├── Title / Contents            (left)
├── Slide preview               (right - EMPTY until the slide is generated)
├── User feedback
├── 🎨 Layout for Slide 1
│   ├── Selected Layout  [dropdown, 64 templates]   <- LLM recommendation
│   ├── 🤖 LLM recommendation: L31 - Four key revenue metrics
│   ├── Template gallery - 64 thumbnails on your background (click to use one)
│   └── status line
├── 🎬 Generate slide 1   🎨 Update content   🖼️ Generate image
```

* The **preview box stays empty** until the slide has actually been generated - the ComfyUI
  backdrop is a background, not a slide, so it is never shown there.
* Clicking a template in a slide's gallery selects it for **that** slide only.
* A new deck clears the screenshots and the structured content of the previous one.

## The layout template library

`layout_catalogue.py` holds the catalogue: the original 44 archetypes (`L01`–`L44`) plus
**20 new ones (`L45`–`L64`) that close the gaps in the original list**:

| New | Template | Why it was added |
| --- | --- | --- |
| L45 | Section Divider | The original set only had a first and a last slide - long decks had no way to signal a chapter break |
| L46 | Feature Matrix | L07 is a data table; a capability-vs-option comparison matrix had no archetype |
| L47 | How-To / Numbered Steps | L10 is a horizontal pipeline; a vertical, instructional how-to was missing |
| L48 | Hero Metric + Support | L05 shows equal metrics; one dominant KPI with a supporting strip is the most common exec slide |
| L49 | Pricing Tiers | No archetype for packaging / pricing comparison |
| L50 | Mission / Vision / Values | Strategy statements had no archetype |
| L51 | Customer Personas | L13 introduces real people; personas describe audiences |
| L52 | Business Model Canvas | A widely used strategy frame with no archetype |
| L53 | Progress / Status Bars | L31 is a KPI scorecard; a simple progress readout was missing |
| L54 | Heatmap Matrix | No archetype for intensity over two dimensions |
| L55 | Scatter / Correlation | Bar, waterfall and funnel existed, but no scatter plot |
| L56 | Composition / Stacked Share | No archetype for a "split of the total" visual |
| L57 | Kanban Board | L23 maps initiatives over time; live work-in-flight is different |
| L58 | Retrospective Board | Keep / stop / start slides are common and had no archetype |
| L59 | Key Dates Calendar | L23 is a swimlane and L06 a timeline; a month view was missing |
| L60 | RACI Responsibility Matrix | L37 covers branching decisions, not role accountability |
| L61 | Anatomy / Labelled Callout | No archetype for an explained diagram with labels |
| L62 | Key Takeaways | The catalogue could end a section but had no explicit takeaways slide |
| L63 | Contact / Directory Grid | L13 shows bios; a contact directory is a different job |
| L64 | Icon Benefit Strip | L03 uses cards; a lighter, more visual benefits row was missing |

### How a layout is described
A layout is **never** described by coordinates. It is a stable id + name + family + a
"content kind" (the structured shape the LLM must produce). The renderer knows how to draw
each kind, so the planner returns `id` + content and never free-form geometry.

### One drawing implementation, two outputs
`layout_engine.py` draws every layout through a small canvas abstraction with two backends:

* `PptxCanvas` -> native, editable PowerPoint shapes and text
* `PilCanvas`  -> a PNG preview

The preview and the `.pptx` therefore always show exactly the same slide, and no separate
screenshot renderer has to be kept in sync. The ComfyUI artwork is blurred and darkened once
(cached on disk) so that body copy stays readable on top of it.

## Setup
```bash
pip install -r requirements.txt
python user_context.py            # the Gradio studio
```

ComfyUI is optional but recommended: set `COMFYUI_DIR` (and optionally `COMFYUI_PYTHON` /
`COMFYUI_ARGS`) so the module can start and stop it for you - see the docstring in
`comfyui.py`.

## Rebuilding the template library
```bash
python generate_layout_templates.py                 # newest ComfyUI background
python generate_layout_templates.py --background path/to/slide_1_0.png
python generate_layout_templates.py --force --light # flat light theme
```
Outputs (in `layout_templates/`):
* `previews/` - one PNG per template, rendered on the ComfyUI background
* `previews/thumbs/` - small JPEG thumbnails used by the per-slide galleries
* `presentation_layout_templates.pptx` - specimen deck, one editable slide per template
* `layout_template_catalogue.md` - the catalogue
* `layout_template_gallery.png` - contact sheet of all 64 templates

## Where the output goes
| What | Where |
| --- | --- |
| Single slide (`.pptx`) | `generated_presentations/pptN/slides/slide_M.pptx` |
| Slide screenshot (`.png`) | `slide_previews/slide_M_preview.png` (project folder) |
| Full deck | `generated_presentations/<session>_compiled.pptx` |
| Session state | `presentation_sessions/<session>.json` |

## Files
- `layout_catalogue.py` - the 64 templates, their metadata and the content-kind schemas
- `layout_engine.py`   - canvas abstraction (PPTX + PNG) and the renderer for every kind
- `layout_templates.py` - LLM planner bridge, content structuring, preview/deck builders
- `generate_layout_templates.py` - CLI to rebuild the template library
- `generate_code_flow_diagram.py` - draws `code_flow.png` from the pipeline description
- `CODE_FLOW.md`       - which function runs when, and what it does
- `gemini_code_fixed.py` - Gradio helpers: slot updates, sessions, per-slide generation, compile
- `user_context.py`     - the Gradio studio (outline -> slides -> layouts -> deck)
- `comfyui.py`          - ComfyUI client for the slide backdrops
- `def_prompts.py`      - prompts, including the layout planner and the content structurer
- `test_layout_pipeline.py` - offline end-to-end test of the whole pipeline (mock LLM)
- `test_code_flow_accuracy.py` - checks that every function in CODE_FLOW.md exists

## Tweaking
- More layouts: add a `Template` to `TEMPLATES` in `layout_catalogue.py`, describe the
  content shape in `KINDS`, and add a renderer to `KIND_RENDERERS` in `layout_engine.py`.
- Different colours: the `Theme` dataclass at the top of `layout_engine.py`.
- Scrim / blur of the background: `Theme.scrim` and `softened_background()`.
- Model: pick it in the UI, or change `model_list` in `user_context.py`.
