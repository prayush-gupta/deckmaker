# 4. Codebase reference

This reference focuses on the files that define runtime behavior. Generated files, model weights, Python bytecode, and local output directories are not source modules and should be documented separately if a deployment needs an artifact inventory.

## 4.1 Core application files

| File | Responsibility | Main relationships |
|---|---|---|
| `app.py` | Main Gradio interface, state and event orchestration, model discovery, outline/content/design workflow, save/resume actions | Imports helpers, prompts, renderer, layout modules, image generation, research |
| `llm_helpers.py` | Ollama chat-completion helper, response parsing, conversation helpers, summaries and utility functions | Uses `prompts.py`; called from app and layout code |
| `prompts.py` | Prompt templates for outline, slide content, folder names, design/image tasks | Used by app, LLM helpers, renderer, image generation |
| `slide_renderer.py` | Slide UI update helpers, artifact paths, per-slide generation, session save/load, final compile orchestration | Uses python-pptx, layout modules, helpers; imported by app |
| `image_generation.py` | ComfyUI API client, workflow parameterization, queue polling, output retrieval, server lifecycle, design brief | Uses workflow JSON, prompts, local Ollama |
| `web_research.py` | Optional focused web research using configured providers; source/result normalization | Called from app; may use `llm_helpers` JSON parsing |
| `layout_catalog.py` | Template records, stable layout IDs, layout families and content-kind specifications | Used by layout manager, engine, renderer |
| `layout_manager.py` | Template previews/specimen deck, layout recommendations, content coercion/structuring, render orchestration | Bridges catalogue, LLM, engine, generated assets |
| `slide_layout_engine.py` | Drawing logic and backends for editable PowerPoint and PNG preview | Uses `python-pptx` and Pillow; reads layout metadata |
| `setup_environment.py` | Cross-platform first-run setup, virtual environments, dependency/model setup, local runtime configuration | Invoked by launcher scripts |
| `build_layout_gallery.py` | Rebuilds template previews, specimen PowerPoint, catalogue Markdown and contact sheet | Uses catalogue, manager, engine |
| `z_image_turbo_workflow.json` | ComfyUI node graph used to create background images | Node IDs must agree with `image_generation.py` |
| `.env.example` | Documented configuration defaults and optional research settings | Copied to local `.env` on first run |
| `requirements.txt` | Python dependency constraints | Installed into app virtual environment |
| `start.sh` | macOS/Linux launcher; selects a compatible Python and ensures Git is available before setup | Calls `setup_environment.py` |
| `start_windows.bat` | Windows entry point | Calls `scripts/start_windows.ps1` |
| `scripts/start_windows.ps1` | Windows-specific bootstrap/launch logic | Calls the Python setup process |
| `DESIGN_REVIEW.md` | Recorded layout QA method, fixes and known visual limitations | Use when changing layouts/renderer |
| `MERGE_NOTES.md` | Records merge-era features and LLM resilience safeguards | Useful regression checklist; verify against current code |

## 4.2 The main app: `app.py`

The application entry point:

- resolves the app directory and loads `.env`;
- configures the default Ollama model and endpoint;
- creates an OpenAI-compatible client pointing at Ollama;
- queries `/api/tags` to discover installed models;
- initializes prompt templates and shared runtime state;
- imports the layout, image, research and renderer modules;
- defines handlers for user actions and builds the Gradio interface.

State visible near the top of the file includes `deck_outline`, `global_prompt`, `summary_stages`, `slide_titles`, `slide_contents`, `deck_brief`, `layout_recommendations`, and `design_ready`. When extending the workflow, be explicit about whether state is per-run, per-slide, persisted to disk, or recomputed after resume.

The app also limits the slide count using `MAX_SLIDES = 25`. UI event output ordering is significant: slide slot components are grouped in a defined order. The renderer documents `UI_STEP = 6` for UI outputs and `STATE_STEP = 4` for persistent slide fields; changing the number/order of components requires updating the matching mapping logic.

## 4.3 `llm_helpers.py`: resilient model boundary

The model wrapper attempts request variants because compatible APIs can differ in support for parameters such as `response_format`, `reasoning_effort`, or `max_tokens`. It retries when final content is empty and removes `<think>` content from visible output. It also provides JSON extraction and conversation-oriented helper functions.

Do not bypass the wrapper casually. If a new model call is added, use the shared helper when compatible, or document why a different path is required. Otherwise the new call may lose the existing compatibility fallbacks and diagnostics.

The helper's resilience is not a guarantee of valid or truthful content. Parsing, schema validation, slide-count checks, and user review are still needed after generation.

## 4.4 `layout_catalog.py`: layout contract

A template record describes a slide pattern using stable IDs (the repository documents L01–L68), names, families, `kind`, best-use guidance, content patterns, implementation notes, density, and image strategy. Content-kind specifications define fields, required values, examples, and repeating item constraints.

To add a layout safely:

1. define the template metadata and content-kind schema;
2. ensure the engine implements that kind;
3. provide representative sample content;
4. build and visually inspect previews and specimen deck;
5. test long text, maximum item counts, and combinations of both;
6. verify PNG/PPTX visual consistency and editability;
7. update the catalogue and design documentation.

## 4.5 `layout_manager.py`: bridge from content to drawing

This module creates previews and a specimen deck, finds a suitable background, asks the model to recommend layouts, coerces model output into the selected layout's shape, and calls the engine for PowerPoint/PNG output. It is the integration boundary between semantic layout metadata and the drawing backend.

A recommendation is not a mandate: the UI lets the user override it. When the selected layout changes, the structured content must be compatible with that template's kind; content restructuring should preserve the meaning, not just force fields to exist.

## 4.6 `slide_layout_engine.py`: drawing backends

The engine uses common drawing instructions with a PowerPoint backend and a Pillow backend. Coordinates use a 13.333 × 7.5 inch canvas. The code defines theme palettes, content-safe margins and a minimum 10 pt font size.

The shared approach reduces duplicated layout geometry, but two rendering systems can still differ in font substitution, text wrapping, alpha/transparency, and PowerPoint's own layout behavior. `DESIGN_REVIEW.md` documents both fixes and remaining limitations. A renderer change should be tested by opening the exported deck in an actual presentation application, not only by looking at PNGs.

## 4.7 `image_generation.py` and workflow JSON

The client targets ComfyUI's local API. Its model configuration identifies workflow path, prompt node, seed node, image-size node, and model-related node values. The default Z-Image workflow is configured for 1536 × 864 output, an exact 16:9 ratio.

Key responsibilities include:

- loading the API-format workflow;
- replacing prompt, seed, image dimensions and model configuration;
- queueing the graph and polling for completion;
- obtaining and saving the generated image;
- optionally starting/stopping a managed ComfyUI subprocess.

If the workflow graph is re-exported, compare node IDs and input names before assuming the Python client remains compatible. Test success, timeout, server-not-running, malformed workflow, and output-download failures.

## 4.8 `web_research.py`: optional network boundary

This module is explicitly optional and uses configured provider keys. It caps the number of research questions, selects provider/model configuration from environment variables, posts requests, parses results, and normalizes evidence. Keep secrets in `.env`; never place API keys in source code, logs, screenshots, or committed example files.

Research results should be treated as candidate evidence. Good documentation and UI affordances should distinguish “source found” from “claim independently verified.”

## 4.9 `setup_environment.py` and launchers

The setup script creates/reuses the application virtual environment, reads and updates `.env`, installs Python dependencies, and prepares local model services and image weights. The app and ComfyUI use separate environments because their dependency and accelerator requirements can differ.

The launchers are part of the product, not incidental convenience scripts. They determine Python version selection, platform-specific setup, and error propagation. Test fresh installation and rerunning after a partial failure on each supported OS.

## 4.10 Generated and runtime directories

The README describes `runtime/ComfyUI` for the ComfyUI checkout and project output under `generated_presentations/`. The exact project tree is configured by the application at runtime. Typical artifact categories include:

- final presentation `.pptx`;
- per-slide PowerPoint files;
- background artwork;
- rendered slide PNGs;
- JSON session checkpoints;
- layout preview PNGs and a specimen layout deck.

Do not commit large model weights, `.venv`, local `.env`, secrets, or user-generated confidential presentations by default. Check `.gitignore` before changing artifact storage rules.
