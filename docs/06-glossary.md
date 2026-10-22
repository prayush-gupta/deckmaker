# 6. Glossary

- **Local-first:** Core generation and rendering are designed to run on the user's computer, although setup downloads and optional online research may use external services.
- **Ollama:** Local model runtime exposing an API used by the app for text generation.
- **ComfyUI:** Node-graph runtime used for image generation.
- **Workflow JSON:** Exported graph describing the image-generation nodes and connections.
- **Design brief:** Shared visual direction intended to keep the deck's backgrounds and styling coherent.
- **Layout catalogue:** Metadata describing available slide archetypes, their intended uses, and their required content structure.
- **Layout kind:** A schema-like description of the fields a template renderer expects.
- **Structured content:** Slide data mapped into named fields that a layout can draw.
- **PptxCanvas:** Rendering backend that creates native editable PowerPoint objects.
- **PilCanvas:** Rendering backend that produces PNG previews using Pillow.
- **Session checkpoint:** JSON record used to persist a presentation's editable state and related metadata for resume.
- **Source footer:** Compact source labels derived from optional research metadata and shown on a slide where supported.
- **VRAM:** GPU memory used by image and language models; image generation may be limited by its capacity.
- **Fallback:** A secondary method used when the preferred method fails, such as a smaller compatible model request or per-slide generation after a batch failure.
- **Placeholder content:** Clearly marked editable content retained when the model cannot produce a slide, preventing silent loss of a required slide slot.
