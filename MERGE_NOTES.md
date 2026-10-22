# Merge notes: Layout update + Ollama safeguards

This package is based on `ai-presentation-studio-fixed.zip` and preserves session and slide-design improvements while restoring and extending the Ollama resilience safeguards from the previous AI Presentation Studio build.

## Preserved from Claude's version

- Save and resume project sessions, including restoring the project's folder paths, chat/outline state, deck brief, layout recommendations, slide structure, source footers, editable slide fields, and selected layout galleries.
- Session-name sanitization for Windows-safe file/folder names.
- Added layout templates L65–L68: Executive Summary, Venn / Overlap, Line / Trend Chart, and Action Plan / Next Steps.
- Rendering improvements in `slide_layout_engine.py`, including minimum font sizing, background-luminance-aware scrims, PowerPoint title placeholders, speaker notes, and image accessibility metadata.
- The Initialize Slides button becomes Regenerate Slide Design after a deck is initialized or resumed. Regeneration makes a fresh shared design brief, attempts every slide background, and re-renders the slides while retaining current titles, content, and selected layouts.
- Continue attempting later background images when one slide's ComfyUI image generation fails.
- Compile-time recovery for missing UI title/content values.

## Safeguards restored/added in this merge

- Restored `robust_chat_completion()` with request-compatibility fallbacks, retries for empty final content, and `reasoning_effort="none"` where supported.
- Routed slide/title/content generation, single-slide recovery, layout recommendations, layout content structuring, design-brief generation, research-query planning, and conversation summarization through the resilient helper.
- Kept two-pass retries for slide JSON, layout recommendations, and content structuring.
- When a batch slide response contains fewer slides than the approved outline, recover missing slides individually. If a single-slide recovery also fails, preserve the slide slot with explicitly marked editable placeholder bullets rather than silently dropping the slide.
- If both batch slide-generation attempts fail entirely, attempt per-outline-item recovery and preserve all expected slide slots with placeholders when the model still cannot respond.
- Added a non-streaming fallback if outline streaming returns no visible final content.
- Retained diagnostic logs that describe empty final content, finish reason, and token usage where available, without logging separate private reasoning text.

## Validation performed

- All Python files passed `py_compile`.
- Mocked tests passed for empty-final-content retry, outline title/count recovery, layout recommendation retry, malformed-JSON content-structuring retry, and the JSON example reported by the user.
- ZIP integrity was checked after packaging.

A live run against the user's Ollama and ComfyUI installation was not available in this environment. These safeguards improve recovery but cannot prevent actual system memory exhaustion or guarantee factual quality for placeholder content.
