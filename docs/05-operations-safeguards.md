# 5. Operations, safeguards, troubleshooting, and maintenance

## 5.1 Configuration reference

Configuration is read from `.env`, created from `.env.example` on first run. Never commit a real `.env` containing keys or machine-specific paths.

| Variable | Purpose | Operational note |
|---|---|---|
| `OLLAMA_BASE_URL` | Local Ollama OpenAI-compatible endpoint | Default is `http://localhost:11434/v1`; the native tags endpoint is derived without `/v1` |
| `OLLAMA_DEFAULT_MODEL` | Default model for text-generation tasks | The app avoids silently substituting an arbitrary model |
| `OLLAMA_MODELS_TO_PULL` | Models setup should download | Keep this list short if disk space is limited |
| `OLLAMA_AUTO_SELECT_MODEL` | Allow setup to choose a smaller default on lower-RAM systems | Review the chosen model; smaller models can reduce quality |
| `OPENAI_API_KEY` | Optional OpenAI research provider | Needed only for that optional online research path |
| `GEMINI_API_KEY` | Optional Gemini research provider | Needed only for that optional online research path |
| `OPENAI_RESEARCH_MODEL` | OpenAI research model selection | Provider availability and pricing may change |
| `GEMINI_RESEARCH_MODEL` / `GEMINI_RESEARCH_MODELS` | Preferred model and fallback chain | Keep names aligned with provider availability |
| `RESEARCH_MAX_QUERIES` | Cap on research questions | The code clamps this to a bounded range |
| `LAYOUT_GALLERY_COLUMNS` | Layout gallery density | App clamps the value to a supported range |
| `COMFYUI_DIR` | ComfyUI checkout | Usually populated by setup |
| `COMFYUI_PYTHON` | Python executable for ComfyUI | Separate from the app's virtual environment |
| `COMFYUI_ARGS` | Local ComfyUI launch arguments | Defaults to loopback host and port 8188 |
| `COMFYUI_TORCH_INDEX_URL` | Optional PyTorch package index override | Only change with hardware-specific install guidance |
| `COMFYUI_ZIMAGE_DIFFUSION_MODEL` | Image diffusion model filename | Must exist in the expected ComfyUI model directory |
| `COMFYUI_ZIMAGE_TEXT_ENCODER` | Text encoder filename | Must match installed model assets |

## 5.2 Existing safeguards documented in the repository

`MERGE_NOTES.md` records the following intended safeguards. They should be treated as regression expectations and verified against the current branch whenever the implementation changes:

- request-compatibility fallbacks and retries for empty final content in `robust_chat_completion()`;
- routing key generation steps through the shared resilient helper;
- two-pass retries for slide JSON, layout recommendations, and content structuring;
- recovery of missing slides individually when a batch response is short;
- explicitly marked editable placeholder bullets when per-slide recovery still fails;
- per-outline-item recovery if an entire batch fails;
- non-streaming fallback when outline streaming yields no visible final content;
- diagnostic logs for empty content, finish reason, and token usage where available, without logging separate private reasoning;
- continuing later background-generation attempts when one slide's image fails;
- compile-time recovery for missing UI title/content values;
- save/resume metadata restoration;
- fresh shared design brief and background regeneration while retaining current content and selected layouts.

These are resilience measures, not guarantees. A placeholder keeps a slot visible but may still need human correction. A retry can improve robustness but can also consume time and compute. Hardware failures and out-of-memory errors can remain unrecoverable.

## 5.3 Common failure modes

| Symptom | Likely boundary | Checks and response |
|---|---|---|
| App cannot find local models | Ollama endpoint/service | Confirm Ollama is running; check `OLLAMA_BASE_URL`; query `/api/tags`; verify the configured model has been pulled |
| Model response is empty or malformed | Model compatibility / output parsing | Review logs; confirm selected model; use shared completion helper; preserve retry and schema validation |
| Deck has fewer slides than outline | Batch generation / parsing | Check slide-count validation and per-slide recovery; ensure placeholders are visible and clearly labelled |
| Artwork never appears | ComfyUI process, model files, workflow node IDs, GPU memory | Confirm port 8188 is reachable locally; inspect ComfyUI logs; verify workflow and weights; test one image |
| One background fails and later slides are skipped | Batch control flow | Confirm per-slide failures are caught and loop continues; add regression test |
| Layout preview differs from PowerPoint | Pillow vs PowerPoint rendering | Open exported `.pptx` in PowerPoint/LibreOffice; check font substitution, transparency, text overflow and margins |
| Saved project does not resume faithfully | Session JSON or omitted runtime metadata | Compare saved fields with active state; verify paths, deck brief, outline, structured content, template selections and source footers |
| Compile drops or misorders slide fields | UI slot/state index mismatch | Check `UI_STEP`, `STATE_STEP`, and the ordering in `app.py` event outputs |
| Setup fails after an interrupted download | Bootstrap/download state | Rerun setup; inspect disk space and permissions; verify partial files are handled safely |
| Online research is unavailable | Missing key, network/provider failure, quota | Confirm optional key and provider configuration; continue without research when appropriate; report unavailable evidence clearly |

## 5.4 Security and privacy posture

### Local service binding

The example ComfyUI arguments bind to `127.0.0.1`, limiting access to the local machine by default. Avoid exposing model APIs to a public network without a deliberate authentication and network-security design.

### Secrets

- Keep API keys in `.env`.
- Keep `.env` ignored by Git.
- Use `.env.example` with empty values only.
- Do not log secrets or include them in bug reports.
- Rotate a key if it is accidentally committed or shared.

### Research and external downloads

The first run fetches external repositories and model files. Optional research sends selected queries to configured providers. Users should understand these external network boundaries before using sensitive material.

### Generated content

Local inference improves control over data flow but does not guarantee factual accuracy, copyright clearance, accessibility, or appropriate handling of confidential source material. Review the deck and its artwork before distribution.

## 5.5 Testing strategy

The repository's merge notes report `py_compile` and mocked resilience tests for several LLM paths, while explicitly noting that a live run against the user's Ollama and ComfyUI installation was not available in that validation environment. Treat syntax/mocked tests and live end-to-end tests as different levels of evidence.

Recommended test layers:

1. **Unit tests**
   - parse valid, fenced, malformed and truncated JSON;
   - normalize model responses with empty final content;
   - coerce partial structured content into each layout kind;
   - sanitize session names and resolve session paths;
   - verify output filenames and path precedence.

2. **Workflow tests with mocks**
   - first batch generation returns fewer slides than the outline;
   - batch generation fails completely;
   - individual slide recovery succeeds/fails;
   - one ComfyUI image fails but later images are still attempted;
   - optional research has no API keys or returns provider errors;
   - save/resume restores every rendering-relevant field.

3. **Renderer tests**
   - render every layout using sample content;
   - increase text lengths and item counts;
   - verify safe margins and minimum font sizes;
   - compare PNG preview with exported PowerPoint;
   - inspect title placeholders, speaker notes, source metadata, alt text, and transparency.

4. **Integration tests**
   - test against a real Ollama instance;
   - generate one image through real ComfyUI;
   - create, save, close, resume, edit, and compile a deck;
   - test low-memory and unavailable-service behavior.

5. **Platform tests**
   - fresh install and rerun after interruption on Windows, macOS and Linux;
   - test supported Python versions and accelerator paths;
   - test paths containing spaces and non-ASCII characters.

## 5.6 Suggested invariants

These are useful assertions to encode in tests:

- The number of slide slots equals the approved outline count, within the application's documented maximum.
- Every expected slide remains represented after a failed generation attempt.
- A failed image for slide N does not prevent attempting slide N+1.
- Regenerating visual design does not overwrite the user's current title/content/layout selection unless explicitly requested.
- Every saved session can be loaded without silently discarding its project path or layout metadata.
- Every selected layout ID exists in the catalogue and its content kind is supported by the engine.
- A rendered slide has a valid output path and a clear error state if rendering fails.
- UI component ordering matches the state serialization and compilation mapping.
- Secrets are never written into repository-tracked files.
- Research source metadata is not presented as proof unless the source actually supports the claim.

## 5.7 Layout QA

`DESIGN_REVIEW.md` describes a useful stress-test method: render each layout with sample content, lengthen text, test maximum item counts, combine long text with maximum items, check overflow/collisions/margins, and inspect the exported PowerPoint. Keep that method as a release gate when adding or changing templates.

Known limitations recorded by the project include hard-coded Segoe UI font selection, differences between Pillow and PowerPoint text wrapping, some layouts relying partly on color to communicate state, charts rendered as shapes rather than native PowerPoint chart objects, and layouts that can leave excess empty space with short content. These should be tracked as explicit issues rather than hidden behind a general claim of “editable slides.”

## 5.8 Maintenance checklist for new features

Before merging a feature:

- [ ] Update architecture and workflow diagrams if data flow changes.
- [ ] Add new configuration keys to `.env.example` and this reference.
- [ ] Decide whether new state must be saved/restored.
- [ ] Route model requests through resilient helpers where possible.
- [ ] Validate structured model output before rendering.
- [ ] Define timeout, retry, cancellation and partial-failure behavior.
- [ ] Add tests for both success and failure paths.
- [ ] Check that UI output order matches save/compile state order.
- [ ] Regenerate layout gallery/specimen deck if template behavior changes.
- [ ] Open exported PowerPoint in a real renderer.
- [ ] Keep secrets and local user artifacts out of version control.
- [ ] Update `README.md` quick-start/configuration instructions.
