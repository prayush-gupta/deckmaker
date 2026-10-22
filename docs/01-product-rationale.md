# 1. Product rationale: why build a local presentation maker?

## 1.1 The problem

A presentation is not just a block of text. It combines a narrative, evidence, visual hierarchy, slide-by-slide pacing, artwork, layout, and an editable deliverable. Creating one manually is repetitive; delegating everything to a hosted AI service can be fast, but may introduce recurring service costs, data-sharing concerns, limited control over the generation pipeline, or output that is difficult to edit.

AI Presentation Studio is designed to make this workflow repeatable on a user's own computer. It combines local language-model inference, local image generation, a layout catalogue, and a PowerPoint renderer. Optional web research remains available for information that needs current or sourced evidence.

## 1.2 Why local-first matters

### Data control

Presentation topics may contain confidential strategy, customer details, internal financials, unpublished product plans, or personal information. Keeping the primary text-generation and artwork-generation steps on the user's machine reduces the need to send all working material to a hosted slide-generation platform.

**Important nuance:** local-first does not mean that every byte always stays offline. Optional research can call OpenAI or Gemini APIs when keys are configured, and first-run setup downloads code and model weights. Users should review their configuration and data policy before handling sensitive content.

### Control over the workflow

The application exposes distinct stages rather than treating the final deck as an opaque AI result:

- propose and confirm an outline;
- create slide content;
- recommend a visual layout;
- allow the user to select a different layout;
- generate slide background artwork;
- render native PowerPoint objects;
- preview, edit, save, resume, and compile the deck.

Separating these stages makes it easier to correct one slide without throwing away the entire presentation.

### Editable deliverables

The output is a `.pptx` with native PowerPoint text and shapes for the supported layout structures, rather than a deck made entirely of flattened screenshots. The renderer also creates PNG previews. This means a user can continue adjusting the deck in PowerPoint-compatible software after export.

Some visual elements, such as charts implemented as drawn shapes, are not necessarily editable as native chart data. See `DESIGN_REVIEW.md` for the documented limitation.

### Repeatability and recoverability

Project folders, slide previews, individual slide PowerPoints, and JSON session checkpoints provide local artifacts that can be inspected and reused. Save/resume is especially valuable for longer generation sessions, where a process can be interrupted or the user may want to return to the deck later.

### Customization and ownership

Because the application is a local codebase, a maintainer can add layouts, change prompts, replace model choices, tune the renderer, or add safeguards without waiting for a hosted vendor's product roadmap. The layout catalogue is data-driven: a layout is described by an ID, name, family, content kind, and usage guidance; the rendering engine draws the relevant kind.

## 1.3 Why combine separate AI components?

A language model and an image model solve different problems.

| Component | Main job | Why it is separate |
|---|---|---|
| Ollama + local LLM | Understand the brief, plan the outline, draft and restructure slide content, recommend layouts | Text and structured reasoning are different from pixel synthesis |
| ComfyUI + image workflow | Generate visual background artwork | Image generation has a separate runtime, model weights, memory profile, and lifecycle |
| Layout catalogue + manager | Map slide purpose to a suitable layout and coerce content into the expected structure | Keeps design patterns consistent and testable |
| PowerPoint renderer | Convert structured content into editable slide objects and preview images | Produces a predictable, portable deliverable rather than relying on an image of a slide |

## 1.4 Why not use only a cloud service?

A cloud service may be preferable when the user has no capable local hardware, wants zero installation, or needs collaboration and hosted asset management. A local application is compelling when the user values control, wants to avoid a per-deck service dependency, needs editable outputs, or wants to modify the generation logic.

The local approach has real costs:

- the first installation downloads large models and dependencies;
- image generation benefits from a capable GPU and significant disk/RAM;
- the user is responsible for updates, troubleshooting, backups, and key management;
- optional online research still depends on external services and network availability;
- local generation is not automatically faster or more accurate than hosted alternatives.

## 1.5 Intended value proposition

The product's core value is **a controllable local production line for editable presentations**: AI assists with narrative, content, and artwork, while explicit layout rules and a deterministic renderer turn the result into a slide deck the user can inspect and continue editing.

## 1.6 Success criteria

A successful experience should:

1. preserve the approved outline and expected slide count;
2. keep slide text and layout fields editable;
3. let the user override AI layout recommendations;
4. avoid losing an entire deck when one model request or image fails;
5. save enough state to resume the work;
6. clearly distinguish research-backed content from unsourced generation;
7. make hardware, network, and model limitations visible;
8. provide actionable error messages and reproducible diagnostics.
