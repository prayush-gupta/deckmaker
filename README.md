# AI Presentation Studio

A local-first Gradio app that uses Ollama for presentation planning and content, ComfyUI + Z-Image Turbo for slide artwork, and a Python PowerPoint renderer for the final editable `.pptx` deck. It includes a visual layout selector, research enrichment (optional API keys), and save/resume checkpoints.

The repository is designed to bootstrap its own local runtime on Windows, macOS, and Linux. The first run installs Python dependencies, installs/starts Ollama when possible, pulls an Ollama model, clones ComfyUI, installs its Python dependencies, downloads the required image-model weights, and then launches the app in your browser.

> **Important hardware note:** “automatic setup” cannot remove local AI hardware requirements. Image generation needs substantial disk space and a capable GPU for a good experience. The installer selects a lower-memory Z-Image variant on most systems, but CPU-only or low-memory machines may be extremely slow or unable to generate images. Read [Hardware and downloads](#hardware-and-downloads) before the first run.

## Quick start

### Windows 10/11

1. Download and extract this repository (or clone it with Git).
2. Double-click **`start_windows.bat`**.
3. Follow any installer prompts. On the first run it will create `.venv`, install the app dependencies, install Ollama if missing, download the selected local LLM, install ComfyUI, and download the image weights.
4. Keep the terminal window open. When setup is complete, the Gradio app opens in your default browser.

The launcher attempts to install Python 3.12 and Git using `winget` if they are missing. If your Windows edition does not have `winget`, install Python 3.12 and Git manually, then rerun the launcher.

### macOS

1. Install Python 3.12 and Git if needed. With Homebrew:
   ```bash
   brew install python@3.12 git
   ```
2. Install Ollama from [ollama.com/download](https://ollama.com/download), or install its CLI with Homebrew:
   ```bash
   brew install ollama
   ```
3. In Terminal, navigate to the extracted repository and run:
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

### Linux

Install Python 3.12 (including `venv`), Git, and the appropriate graphics drivers using your distribution's package manager. Install `curl` if it is not already available. Then run:

```bash
chmod +x start.sh
./start.sh
```

The launcher attempts the official Ollama install script on Linux. If the installer requires elevated privileges, follow its prompt. NVIDIA GPU users need a compatible NVIDIA driver. AMD ROCm setups vary by distribution and GPU; see [GPU notes](#gpu-notes).

## Project structure

The source files use descriptive names so contributors can find the right part of the application quickly:

| File | Responsibility |
|---|---|
| `app.py` | Main Gradio application and user interface |
| `setup_environment.py` | First-run environment, Ollama, and ComfyUI setup |
| `slide_renderer.py` | Slide state, rendering orchestration, preview and PowerPoint compilation |
| `llm_helpers.py` | Ollama chat helpers, conversation handling, and JSON parsing |
| `prompts.py` | Prompts for slide content, layouts, and image generation |
| `image_generation.py` | ComfyUI API client and image-generation lifecycle |
| `web_research.py` | Optional online research enrichment and source collection |
| `layout_catalog.py` | Definitions and metadata for available slide layouts |
| `layout_manager.py` | Layout selection, structured slide content, and template previews |
| `slide_layout_engine.py` | Low-level slide layout rendering to PowerPoint and PNG |
| `build_layout_gallery.py` | Utility to build or refresh the layout gallery |
| `z_image_turbo_workflow.json` | ComfyUI API workflow used for slide background generation |
| `layout_templates/` | Generated layout preview images and template catalogue assets |

## What the first run does

1. **Python app environment:** creates a project-local `.venv` and installs `requirements.txt`.
2. **Git:** installs Git using a platform package manager when available, because ComfyUI is cloned from its official repository.
3. **Ollama:** installs it if missing, starts its local API if it is not already running, and downloads the configured model(s).
4. **Model discovery:** the app queries Ollama's local `/api/tags` endpoint at startup and fills the model dropdown from the models actually installed on that machine. It does not hard-code a stale list of model names.
5. **ComfyUI:** clones the official `Comfy-Org/ComfyUI` repository to `runtime/ComfyUI`, creates a separate Python environment, installs PyTorch for the detected platform where possible, and installs ComfyUI's requirements.
6. **Image weights:** downloads Z-Image Turbo, its text encoder, and VAE into ComfyUI's model folders. Downloads are resumable where the hosting server supports HTTP range requests.
7. **Launch:** starts `app.py`; Gradio opens in the default browser. ComfyUI is started on demand when slide artwork is generated and is shut down afterward by the app to release VRAM.

Subsequent runs reuse the environments, ComfyUI checkout, and model files. Setup can be rerun safely if a download or installation was interrupted.

## Hardware and downloads

### Recommended

- 64-bit Windows 10/11, a recent macOS release, or a modern Linux distribution.
- Python **3.11–3.13** (the launchers prefer 3.12).
- Git and a stable internet connection for first-run downloads.
- **At least 35 GB free disk space** for the selected Ollama model, ComfyUI, Python environments, and image-model files. More space is recommended for presentations and additional Ollama models.
- **32 GB system RAM recommended** for the default `gpt-oss` LLM and local image generation.
- An NVIDIA GPU with **16 GB+ VRAM recommended** for the default lower-memory Z-Image variant. More VRAM improves reliability and speed.

The setup chooses the BF16 image model only when an NVIDIA GPU with approximately 24 GB or more VRAM is detected. Otherwise it uses the official INT8 ConvRot diffusion model and FP8 text encoder, which reduce disk and memory use. The INT8 ConvRot model requires a recent ComfyUI version; the installer clones the current official ComfyUI branch.

All local Ollama text-generation tasks use the configured `OLLAMA_DEFAULT_MODEL` by default (normally `gpt-oss`), including slide creation, slide edits, design briefs, and conversation summaries. The app does not silently replace that default with another installed model. During setup, machines with less than 24 GB RAM may default to `llama3.2:3b` when `OLLAMA_AUTO_SELECT_MODEL=true`; this choice is written to `.env` and is then used consistently throughout the app. Users can select another installed model in the UI.

### Low-memory machines

If the machine has less than 24 GB of RAM and `OLLAMA_AUTO_SELECT_MODEL=true`, the installer switches the default from `gpt-oss` to the smaller `llama3.2:3b` model. You can choose a different installed model in the app. To disable this automatic choice, set `OLLAMA_AUTO_SELECT_MODEL=false` in `.env`.

CPU-only image generation is not recommended. Apple Silicon may use PyTorch's MPS backend, but model and operator compatibility depends on the hardware and software versions. If image generation does not work on your hardware, the text/layout/PPT portions can still be run with `--skip-comfyui` if you already have an alternative image workflow, or you can configure an existing ComfyUI installation in `.env`.

### GPU notes

- **NVIDIA:** the installer detects GPU compute capability and selects the official PyTorch CUDA 13.0 wheels for newer GPUs or CUDA 12.6 for older GPUs. Keep NVIDIA drivers up to date.
- **Apple Silicon:** installs standard PyTorch, which can use MPS where supported.
- **AMD Linux:** if `rocminfo` is present, setup attempts the official PyTorch ROCm 7.2 index. AMD GPU support is hardware/distribution-specific.
- **Other hardware or custom drivers:** set `COMFYUI_TORCH_INDEX_URL` in `.env` to the appropriate PyTorch index and rerun setup. Check the current [ComfyUI installation guide](https://github.com/Comfy-Org/ComfyUI#installing) and [PyTorch installation selector](https://pytorch.org/get-started/locally/) first.

## Configuration

On first run, `.env` is created from `.env.example`. Edit it to change settings, then rerun the launcher. Do not commit `.env` or API keys.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Local Ollama OpenAI-compatible API endpoint |
| `OLLAMA_DEFAULT_MODEL` | `gpt-oss` | Model used for default actions |
| `OLLAMA_MODELS_TO_PULL` | `gpt-oss` | Comma-separated list of Ollama models to download on setup |
| `OLLAMA_AUTO_SELECT_MODEL` | `true` | Select a smaller default model on lower-RAM machines |
| `COMFYUI_DIR` | auto-populated | ComfyUI checkout path |
| `COMFYUI_PYTHON` | auto-populated | Python executable for the separate ComfyUI environment |
| `COMFYUI_ARGS` | auto-populated | Local ComfyUI server arguments |
| `COMFYUI_TORCH_INDEX_URL` | blank | Optional override for the PyTorch package index |
| `LAYOUT_GALLERY_COLUMNS` | `9` | Layout gallery density (3–12) |
| `RESEARCH_MAX_QUERIES` | `3` | Number of targeted online research queries (0–6) |
| `OPENAI_API_KEY` | blank | Optional OpenAI research API key |
| `GEMINI_API_KEY` | blank | Optional Gemini research API key (also accepts `GOOGLE_API_KEY`) |
| `GEMINI_RESEARCH_MODEL` | `gemini-3.1-flash-lite` | Preferred Gemini research model |
| `GEMINI_RESEARCH_MODELS` | `gemini-3.1-flash-lite,gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.8-flash` | Ordered fallback chain tried until a grounded answer succeeds |

Online research is optional. Without `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY`, the local app can still build decks; online source-grounded research is skipped. For Gemini, the app tries `GEMINI_RESEARCH_MODEL` first, then the comma-separated fallback chain in `GEMINI_RESEARCH_MODELS`. Each fallback must be enabled for your Google AI Studio project and have quota available; model names and free-tier availability can change. If Gemini is available in your browser, that does not automatically configure API access: create/use an API key in Google AI Studio and put it in the project `.env`, then restart the app. Keep API keys private.

### Change the Ollama models that are downloaded

Set the model names before running setup, for example:

```dotenv
OLLAMA_DEFAULT_MODEL=llama3.2:3b
OLLAMA_MODELS_TO_PULL=llama3.2:3b,qwen3.5:4b
```

Only models named in `OLLAMA_MODELS_TO_PULL` are pulled automatically. The dropdown is populated from models actually installed in Ollama, not every model available in the online registry. Model names and requirements change over time; see [Ollama's model library](https://ollama.com/library).

## Setup options

Run `python setup_environment.py --help` from a terminal to see the available flags. Common examples:

```bash
# Install app/Ollama/ComfyUI and launch the app (normal first-run behavior)
python setup_environment.py

# Use an already-installed Ollama and skip its installation/pull stage
python setup_environment.py --skip-ollama

# Set up ComfyUI but defer the large image-model downloads
python setup_environment.py --skip-model-download

# Set up dependencies without launching Gradio
python setup_environment.py --no-launch
```

`--skip-comfyui` skips ComfyUI setup completely. Use it only if you do not need image generation or have configured another supported workflow. If you skip Ollama model downloads, make sure the configured default model already exists locally.

## Generated files and save/resume

- Decks and project checkpoints are stored under `generated_presentations/`.
- Session checkpoints are written after generation and after user edits; use **Project Session Management Console** to save or resume a saved session.
- The saved session restores slide content, selected layouts, preview paths, design brief, outline, and structured slide data.
- The layout library includes executive summary (L65), Venn/overlap (L66), line/trend chart (L67), and action plan (L68) designs.
- The first **Initialize Slides** action creates the deck. Afterward, the button becomes **Regenerate Slide Design**, which creates a fresh shared design brief, regenerates all slide backgrounds, and re-renders slides while retaining the current titles, content, and selected layouts.
- If one background image fails, generation continues for the remaining slides; failed images are reported and the deck can still be reviewed.
- Keep a project's folder intact if you want to resume it later; checkpoints refer to its images and previews.
- Local runtimes, weights, secrets, logs, and generated presentations are ignored by Git and are not uploaded to your public repository.

## Troubleshooting

- **Browser did not open:** keep the terminal open and copy the final Gradio URL (usually `http://127.0.0.1:7860`) into your browser.
- **Ollama API not available:** start Ollama, verify `ollama list` works, and rerun the launcher. Check `ollama_server.log` if the launcher started the service itself.
- **Model pull failed:** rerun the launcher; then verify the model name in `OLLAMA_MODELS_TO_PULL` against the Ollama model library.
- **Ollama returns empty content or invalid JSON:** requests retry compatible configurations (including disabling separate reasoning output where supported); slide generation can recover missing slides individually, layout/content structuring retries malformed JSON, and deterministic fallbacks keep the deck editable when the model still fails. Check the console's `[ollama]`, `[slides]`, and `[layouts]` diagnostics. These safeguards do not prevent genuine RAM/VRAM exhaustion, and fallback slide text may need manual completion.
- **ComfyUI startup failed:** inspect `comfyui_server.log`. Confirm the GPU driver and PyTorch installation. The model files are under `runtime/ComfyUI/models/`.
- **Missing model error:** check `COMFYUI_ZIMAGE_DIFFUSION_MODEL` and `COMFYUI_ZIMAGE_TEXT_ENCODER` in `.env` and ensure the corresponding files exist in the ComfyUI model folders.
- **Disk space / interrupted model download:** free disk space and rerun the launcher. Partial model files use the `.part` suffix and may resume.
- **Use an existing ComfyUI install:** set `COMFYUI_DIR` to the directory containing `main.py`; rerun `python setup_environment.py --skip-ollama` as appropriate. The installer still creates/uses a `.venv` inside that ComfyUI directory unless one is already present.

## Publish this project to GitHub

1. Create an empty repository on GitHub.
2. Extract this project so `README.md`, `app.py`, `setup_environment.py`, `start_windows.bat`, and `start.sh` are at the repository root.
3. In the project folder, run:

   ```bash
   git init
   git add .
   git commit -m "Prepare AI Presentation Studio for first-run setup"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
   git push -u origin main
   ```

4. Confirm `.env`, `.venv`, `runtime/`, model weights, and generated presentations are not tracked. The included `.gitignore` excludes them.

## Upstream components and model licenses

- [Ollama](https://ollama.com/download) — install and model runtime.
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI) — image generation server.
- [Comfy-Org Z-Image Turbo files](https://huggingface.co/Comfy-Org/z_image_turbo) — downloaded on first run; upstream model repository identifies the files as Apache-2.0. Review the upstream license and terms before redistribution.
- [PyTorch](https://pytorch.org/) — tensor runtime.

This repository does **not** bundle Ollama, ComfyUI, or large model weights. The setup script downloads them from their respective upstream sources onto each user's machine.
