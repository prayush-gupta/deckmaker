# 3. End-to-end workflows

## 3.1 First-run installation

```mermaid
flowchart TD
    Start[User launches app] --> OS{Operating system}
    OS -->|Windows| BAT[start_windows.bat]
    BAT --> PS[scripts/start_windows.ps1]
    OS -->|macOS/Linux| SH[start.sh]
    SH --> Setup[setup_environment.py]
    PS --> Setup
    Setup --> Python{Python 3.11–3.13 available?}
    Python -->|No| Stop[Explain requirement / attempt supported install]
    Python -->|Yes| Venv[Create or reuse app .venv]
    Venv --> Requirements[Install requirements.txt]
    Requirements --> Env[Create .env from .env.example if missing]
    Env --> Ollama[Install/start Ollama and pull configured model]
    Ollama --> Comfy[Clone/configure ComfyUI and separate environment]
    Comfy --> Weights[Download required image model files]
    Weights --> Launch[Launch app.py]
    Launch --> Browser[Open Gradio UI in browser]
```

The first run is intentionally heavyweight. The README estimates at least 35 GB of free disk space and recommends 32 GB system RAM and an NVIDIA GPU with 16 GB+ VRAM for a good experience with the default lower-memory image model. These are recommendations from the repository, not universal minimums; actual performance depends on model choices, drivers, and hardware.

Subsequent runs reuse local environments, ComfyUI checkout, and model files. The setup script is intended to be rerunnable after interrupted installation/downloads.

## 3.2 Presentation planning and content generation

```mermaid
flowchart TD
    Topic[Topic / assignment from user] --> Prompt[deck_outline_prompt]
    Prompt --> Chat[Conversation with local LLM]
    Chat --> Outline[Objective + proposed slide outline]
    Outline --> Review{User approves outline?}
    Review -->|No| Refine[User clarifies / revise outline]
    Refine --> Chat
    Review -->|Yes| Summary[Summarize agreed objective and structure]
    Summary --> Draft[Generate slide titles and content]
    Draft --> Count{All outline slides represented?}
    Count -->|Yes| Continue[Continue to design]
    Count -->|No| Recover[Retry or recover missing slides individually]
    Recover --> Placeholder[If recovery fails, preserve slide slot with marked placeholder]
    Placeholder --> Continue
```

The outline approval step matters because it establishes the narrative before investing in artwork and layout. The approved outline is a constraint for later stages; the system should preserve the intended slide count and order even when a model response is incomplete.

## 3.3 Layout recommendation and user override

```mermaid
flowchart LR
    Content[Slide title + content] --> Heuristic[Heuristic fallback]
    Content --> Model[LLM layout recommendation]
    Catalogue[layout_catalog.py] --> Model
    Model --> Recommend[Recommended layout ID + reason]
    Heuristic -. fallback .-> Recommend
    Recommend --> Gallery[Layout gallery and selector]
    Gallery --> Choice{User accepts recommendation?}
    Choice -->|Yes| Selected[Selected template]
    Choice -->|No| Override[User selects another template]
    Override --> Structure[Structure content for selected layout kind]
    Selected --> Structure
    Structure --> Render[Render slide]
```

Layout selection is deliberately separate from rendering. This makes it possible to change the visual pattern while preserving the underlying subject and editable content. A new layout normally requires coordinated metadata and drawing support: adding only a catalogue record is insufficient if the renderer does not implement its content kind.

## 3.4 Background image generation

```mermaid
sequenceDiagram
    participant App as app.py
    participant Brief as Local LLM
    participant Client as image_generation.py
    participant Workflow as Workflow JSON
    participant Comfy as ComfyUI
    participant FS as Filesystem

    App->>Brief: Request shared deck design brief / slide image prompts
    Brief-->>App: Visual direction and prompts
    App->>Client: Generate background for slide
    Client->>Workflow: Load workflow and set prompt, seed, size
    Client->>Comfy: Queue workflow
    Comfy-->>Client: Prompt/job identifier
    loop Poll until complete or failure
        Client->>Comfy: Check queue/history
        Comfy-->>Client: Status/result
    end
    Client->>Comfy: Fetch generated image output
    Client->>FS: Save canonical slide_N.png
    Client-->>App: Image path or failure information
```

The current default workflow targets 16:9 artwork. The image-generation module can start a managed ComfyUI process when configured to do so, reuse it for a batch, and stop it afterward to release VRAM. If ComfyUI is externally managed, the app can instead use that existing server.

The image generator and workflow must remain in sync: the Python module references workflow node IDs for prompt, seed, size, and model settings. A changed workflow export may change those IDs.

## 3.5 Slide rendering and final compilation

```mermaid
flowchart TD
    Inputs[Title + content + selected layout + artwork + source metadata] --> Coerce[Coerce/structure content for layout kind]
    Coerce --> Draw[Shared layout drawing instructions]
    Draw --> Pptx[PptxCanvas: editable native shapes/text]
    Draw --> Preview[PilCanvas: PNG preview]
    Pptx --> PerSlide[Per-slide PPTX artifact]
    Preview --> PreviewFile[Slide preview PNG]
    PerSlide --> Compile[Compile slides in order]
    PreviewFile --> Workspace[Show preview in Gradio workspace]
    Compile --> Final[Final editable presentation .pptx]
```

The preview is a convenience, not the authoritative output. The project documents historical cases where PowerPoint transparency differed from the PNG preview; shared drawing instructions and explicit PowerPoint output fixes reduce, but cannot eliminate, differences between Pillow's font rendering and PowerPoint's own text layout.

## 3.6 Save and resume

```mermaid
flowchart TD
    SaveClick[User chooses Save] --> Ready{Slides initialized and project directory valid?}
    Ready -->|No| Warn[Ask user to generate slides first]
    Ready -->|Yes| Serialize[Save editable slide fields to session JSON]
    Serialize --> Metadata[Attach project paths, outline, prompts, design brief, layout metadata, source metadata]
    Metadata --> Disk[Write checkpoint under project session directory]
    Disk --> List[Refresh saved-session list]
    List --> Resume[User selects a saved session]
    Resume --> Load[Read JSON and restore values/metadata]
    Load --> Paths[Restore project paths and rendering context]
    Paths --> UI[Rebuild workspace and selected layout gallery]
    UI --> Continue[Continue editing / regenerate / compile]
```

A checkpoint is more than a transcript. It needs enough metadata to restore the active project folder, slide state, deck outline, design brief, layout recommendations, structured content, selected templates, and research-source footers. Any new runtime state that influences rendering or editing should be reviewed for serialization.

## 3.7 Regenerating slide design

The repository's merge notes describe a “Regenerate Slide Design” action after slides are initialized or resumed. The intended behavior is to create a fresh shared design brief, attempt background generation for every slide, and rerender slides while preserving current titles, content, and selected layouts. If one image fails, later slides should still be attempted rather than aborting the entire batch.

This is an important separation of concerns: **regenerate visual design** should not silently rewrite the user's approved narrative. If implementation changes this behavior, update this section and add a regression test.

## 3.8 Optional research enrichment

```mermaid
flowchart TD
    Slides[Draft slides] --> Decide{Research configured?}
    Decide -->|No| Plain[Continue without online enrichment]
    Decide -->|Yes| Questions[Local LLM proposes focused research questions]
    Questions --> Provider[OpenAI and/or Gemini search API]
    Provider --> Evidence[Candidate results and source metadata]
    Evidence --> Enrich[Attach useful evidence to slide content]
    Enrich --> Footer[Record source footer metadata]
    Footer --> Render[Render visible slide and notes/metadata as supported]
```

Research is not equivalent to fact verification. The application can collect sources and show provenance, but users should still check that a cited page supports the claim, is current enough, and is authoritative for the subject.
