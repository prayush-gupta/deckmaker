# Model Setup step
### This is the user context code that requests the user to describe the presentation topic

from datetime import datetime
import glob
import json
import os
import time
import html as _html
import threading
import contextvars
import warnings
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "gpt-oss")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

import gradio as gr
from openai import OpenAI

warnings.filterwarnings("ignore")

# Import relevant functions
from prompts import deck_outline_prompt
from llm_helpers import (first_prompt, response_append, slide_outline, convo_backup,
                           summarize_conversation, slides_from_conversation, outline_titles_from_conversation, extract_json, folders_setup,
                           robust_chat_completion, dark_panel_css, unified_theme)
from slide_renderer import (build_slide_updates, on_thumbnail_select, _gallery_items_for, build_slide, _resolve_template, save_user_session,
                               load_user_session, compile_presentation_file, image_path_for,
                               generate_slide, GALLERY_ITEMS,
                               LAYOUT_NAMES, slide_preview_file,
                               SLIDE_STRUCTURED, SLIDE_TEMPLATES, SLIDE_SOURCE_FOOTERS,
                               configure_project_paths)
from layout_catalog import LAYOUT_LABELS, TEMPLATES, get_template
from layout_manager import (build_template_deck, coerce_content, find_background,
                              recommend_layouts, structure_for_layout, flatten_content,
                              write_catalogue_markdown, PREVIEW_DIR, TEMPLATE_DECK)
from image_generation import comfyui_img_generator, deck_design_brief, comfyui_session
from web_research import enrich_slides_with_research


# Model initialize
ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
ollama = OpenAI(api_key="ollama", base_url=ollama_url)

# --- CONFIGURATION & CONSTANTS ---
MAX_SLIDES = 25
SLIDE_PANEL_HEIGHT = 368
# Set LAYOUT_GALLERY_COLUMNS=8 or 9 in the environment to adjust gallery density.
try:
    LAYOUT_GALLERY_COLUMNS = max(3, min(12, int(os.getenv("LAYOUT_GALLERY_COLUMNS", "9"))))
except (TypeError, ValueError):
    LAYOUT_GALLERY_COLUMNS = 9
def fetch_ollama_models():
    """Fetch locally available Ollama models from /api/tags at startup."""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    # The OpenAI-compatible base URL may end in /v1; the native Ollama API does not.
    base = base[:-3] if base.endswith("/v1") else base
    try:
        req = urllib.request.Request(f"{base}/api/tags", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names = sorted({str(item.get("name") or item.get("model")) for item in payload.get("models", [])
                        if item.get("name") or item.get("model")})
        return names
    except Exception as exc:
        print(f"[ollama] Could not fetch installed model list: {exc}")
        return []


installed_model_list = fetch_ollama_models()
# Keep the configured default as the initial selection. The setup script normally
# installs it; including it here avoids silently replacing it with an arbitrary
# model if Ollama is reachable but the default has not been pulled yet.
model_list = list(installed_model_list)
if DEFAULT_OLLAMA_MODEL not in model_list:
    model_list.insert(0, DEFAULT_OLLAMA_MODEL)
if not model_list:
    model_list = [DEFAULT_OLLAMA_MODEL]
PPT_DIR_FOLDER = ""
ARCHIVE_DIR = ""
SESSIONS_DIR = ""
SLIDE_PREVIEW_DIR = ""
SLIDE_LAYOUTS = ""

# Define our system prompt for the first step of defining the outline of the presentation
system_prompt, user_prompt_prefix, outline_summarizer = deck_outline_prompt()

# --- GLOBAL STATE ---
p_cnt = 0
global_prompt = []
deck_outline = {}
summary_stages = []
slide_titles = [""] * MAX_SLIDES
slide_contents = [""] * MAX_SLIDES
deck_brief = None   # ONE colour/shape/style brief shared by every slide of the current deck
layout_recommendations = {}   # slide number (1-based) -> {"layout_id": ..., "reason": ...}
design_ready = False   # True once slides exist -> the main button becomes "Regenerate Slide Design"
INITIALIZE_LABEL = "✨ Initialize Slides"
REGENERATE_LABEL = "🎨 Regenerate Slide Design"


def _outline_text():
    """Readable outline text handed to the layout planner."""
    if isinstance(deck_outline, dict):
        return "\n".join(f"{n}. {t}" for n, t in sorted(deck_outline.items()))
    return str(deck_outline or "")


def _parse_outline(outline):
    parsed = {}
    for line in outline.split("\n"):
        if line.startswith("#") or ". " not in line:
            continue
        number, text = line.split(". ", 1)
        if number.strip().isdigit():
            parsed[int(number)] = text
    return parsed


def _safe_session_filename(name):
    import re
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", (name or "").strip()).strip(" ._") or "Presentation"


def _session_file_path(session_name, sessions_dir=None):
    safe = _safe_session_filename(session_name)
    if sessions_dir:
        candidate = os.path.join(sessions_dir, f"{safe}.json")
        if os.path.isfile(candidate):
            return candidate
    import glob
    roots = {os.path.abspath("generated_presentations"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_presentations")}
    matches = []
    for root in roots:
        matches.extend(glob.glob(os.path.join(root, "**", "presentation_sessions", f"{safe}.json"), recursive=True))
    matches = sorted(set(matches), key=os.path.getmtime)
    return matches[-1] if matches else (os.path.join(sessions_dir, f"{safe}.json") if sessions_dir else None)


def _list_saved_sessions():
    """Every saved project on disk, newest first, as (label, path) pairs for the Resume dropdown."""
    import glob
    roots = {os.path.abspath("generated_presentations"),
             os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_presentations")}
    found = {}
    for root in roots:
        for path in glob.glob(os.path.join(root, "*", "presentation_sessions", "*.json")):
            found[os.path.abspath(path)] = os.path.getmtime(path)
    items = []
    for path, mtime in sorted(found.items(), key=lambda kv: kv[1], reverse=True):
        project = os.path.basename(os.path.dirname(os.path.dirname(path)))
        name = os.path.splitext(os.path.basename(path))[0]
        stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        items.append((f"{name}  ·  {project}  ·  saved {stamp}", path))
    return items


def _refresh_saved_sessions():
    return gr.update(choices=_list_saved_sessions())


def _add_checkpoint_metadata(session_name, sessions_dir=None):
    """Attach project/runtime state to the human-readable slide checkpoint."""
    path = _session_file_path(session_name, sessions_dir or SESSIONS_DIR)
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        from slide_renderer import SLIDE_STRUCTURED, SLIDE_TEMPLATES, SLIDE_SOURCE_FOOTERS
        payload.update({
            "generated": True,
            "PPT_DIR_FOLDER": os.path.abspath(PPT_DIR_FOLDER) if PPT_DIR_FOLDER else "",
            "ARCHIVE_DIR": os.path.abspath(ARCHIVE_DIR) if ARCHIVE_DIR else "",
            "SESSIONS_DIR": os.path.abspath(SESSIONS_DIR) if SESSIONS_DIR else "",
            "SLIDE_PREVIEW_DIR": os.path.abspath(SLIDE_PREVIEW_DIR) if SLIDE_PREVIEW_DIR else "",
            "SLIDE_LAYOUTS": os.path.abspath(SLIDE_LAYOUTS) if SLIDE_LAYOUTS else "",
            "deck_brief": deck_brief,
            "deck_outline": deck_outline,
            "global_prompt": global_prompt,
            "summary_stages": summary_stages,
            "layout_recommendations": layout_recommendations,
            "slide_source_footers": SLIDE_SOURCE_FOOTERS,
            "slide_structured": SLIDE_STRUCTURED,
            "slide_templates": SLIDE_TEMPLATES,
        })
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
        return path
    except Exception as exc:
        print(f"[checkpoint] Could not attach project metadata: {exc}")
        return ""


def _save_current_session(sessions_dir, max_slides, session_name, count, outline, *slide_states):
    """Save the current editable state; refuse to create a project before generation."""
    if not design_ready or not PPT_DIR_FOLDER or not os.path.isdir(PPT_DIR_FOLDER):
        return "⚠️ Generate slides first. A blank chat cannot be saved as a project."
    result = save_user_session(sessions_dir, max_slides, session_name, count, outline, *slide_states)
    if result.startswith("💾"):
        _add_checkpoint_metadata(session_name, sessions_dir)
    return result


def _restore_session(sessions_dir, max_slides, ppt_dir_folder, slide_preview_dir, session_name):
    """Restore UI and module globals so the project can be edited after an app restart."""
    global PPT_DIR_FOLDER, ARCHIVE_DIR, SESSIONS_DIR, SLIDE_PREVIEW_DIR, SLIDE_LAYOUTS
    global global_prompt, deck_outline, summary_stages, deck_brief, layout_recommendations
    global slide_titles, slide_contents, p_cnt, design_ready
    from slide_renderer import SLIDE_STRUCTURED, SLIDE_TEMPLATES, SLIDE_SOURCE_FOOTERS, _gallery_items_for

    updates = load_user_session(sessions_dir, max_slides, ppt_dir_folder, slide_preview_dir, session_name)
    path = _session_file_path(session_name, sessions_dir)
    if not path or not os.path.isfile(path):
        return [updates[0], updates[1], updates[2], updates[3], gr.update(), gr.update(), gr.update(), gr.update(), gr.update(interactive=False)] + updates[4:] + [gr.update() for _ in range(MAX_SLIDES * 2)] + [gr.update()]

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    # The checkpoint sits in <project>/presentation_sessions/, so the project folder is always
    # derivable from where the file really is. That keeps resume working if the project folder
    # was moved/renamed or the stored absolute paths belong to another machine/location.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    if os.path.basename(os.path.dirname(os.path.abspath(path))) != "presentation_sessions":
        project_root = payload.get("PPT_DIR_FOLDER") or ppt_dir_folder or project_root
    PPT_DIR_FOLDER = project_root
    ARCHIVE_DIR = os.path.join(PPT_DIR_FOLDER, "archive")
    SESSIONS_DIR = os.path.join(PPT_DIR_FOLDER, "presentation_sessions")
    SLIDE_PREVIEW_DIR = os.path.join(PPT_DIR_FOLDER, "slide_previews")
    SLIDE_LAYOUTS = os.path.join(PPT_DIR_FOLDER, "slide_layouts")
    for _d in (ARCHIVE_DIR, SESSIONS_DIR, SLIDE_PREVIEW_DIR, SLIDE_LAYOUTS):
        os.makedirs(_d, exist_ok=True)
    configure_project_paths(PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)
    # the slide UI values/images were built by load_user_session from the stored paths -> rebuild
    # them against the real project folder
    updates = load_user_session(SESSIONS_DIR, max_slides, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR,
                                os.path.splitext(os.path.basename(path))[0])

    global_prompt = payload.get("global_prompt", []) or []
    raw_outline = payload.get("deck_outline", {}) or {}
    deck_outline = ({int(k): v for k, v in raw_outline.items()} if isinstance(raw_outline, dict) else raw_outline)
    design_ready = True
    summary_stages = payload.get("summary_stages", []) or []
    deck_brief = payload.get("deck_brief")
    layout_recommendations = {int(k): v for k, v in (payload.get("layout_recommendations", {}) or {}).items()}
    p_cnt = 1 if global_prompt else 0
    slides = payload.get("slides", [])
    slide_titles = [(slides[i].get("title", "") if i < len(slides) else "") for i in range(max_slides)]
    slide_contents = [(slides[i].get("content", "") if i < len(slides) else "") for i in range(max_slides)]

    SLIDE_STRUCTURED.clear()
    SLIDE_STRUCTURED.update({int(k): v for k, v in (payload.get("slide_structured", {}) or {}).items()})
    SLIDE_TEMPLATES.clear()
    SLIDE_TEMPLATES.update({int(k): v for k, v in (payload.get("slide_templates", {}) or {}).items()})
    SLIDE_SOURCE_FOOTERS.clear()
    SLIDE_SOURCE_FOOTERS.update({int(k): v for k, v in (payload.get("slide_source_footers", {}) or {}).items()})

    status = updates[0]
    # show the last assistant message (the approved outline) so the chat panel isn't blank
    last_reply = next((m.get("content") for m in reversed(global_prompt)
                       if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content")), "")
    chat_update = gr.update(value=last_reply or "")
    note_updates = []
    gallery_updates = []
    for i in range(max_slides):
        slide = slides[i] if i < len(slides) else {}
        layout_label = slide.get("layout", "") or LAYOUT_LABELS[1]
        note_updates.append(gr.update(value=_layout_note(i, layout_label)))
        gallery_updates.append(gr.update(value=_gallery_items_for(layout_label)))
    return [status, updates[1], updates[2], updates[3],
            gr.update(value=SESSIONS_DIR), gr.update(value=PPT_DIR_FOLDER),
            gr.update(value=SLIDE_PREVIEW_DIR), gr.update(value=_safe_session_filename(session_name)),
            gr.update(interactive=True)] + updates[4:] + note_updates + gallery_updates + [chat_update]


def _resume_clicked(picked_path, sessions_dir, max_slides, ppt_dir_folder, slide_preview_dir, typed_name):
    """Resume the project picked in the dropdown, or fall back to the typed session name."""
    if picked_path and os.path.isfile(picked_path):
        sessions_dir = os.path.dirname(picked_path)
        typed_name = os.path.splitext(os.path.basename(picked_path))[0]
    return _restore_session(sessions_dir, max_slides, ppt_dir_folder, slide_preview_dir, typed_name)


def response_streamer_outline(model, user_input_message, slide_count):
    yield "⏳ Processing..."
    global p_cnt, global_prompt, deck_outline, summary_stages
    if p_cnt == 0:
        prompt = first_prompt(system_prompt, user_prompt_prefix, user_input_message, slide_count)
        p_cnt = 1
    else:
        prompt = response_append(global_prompt, user_input_message, "user")

    stream = ollama.chat.completions.create(
        model=model,
        messages=prompt,
        stream=True,
    )

    result = ""
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            result += delta.content
            yield result

    # Streaming endpoints can return reasoning without visible final content. If that happens,
    # retry through the resilient non-streaming path with reasoning disabled where supported.
    if not result.strip():
        try:
            fallback = robust_chat_completion(
                ollama, model, prompt, temperature=0, max_tokens=4096,
            )
            result = (getattr(fallback.choices[0].message, "content", None) or "").strip()
            if result:
                yield result
        except Exception as exc:
            print(f"[ollama] outline streaming was empty; non-streaming fallback failed: {exc}")

    # store the assistant turn, including any tool calls
    assistant_msg = {"role": "assistant", "content": result or None}

    global_prompt = list(prompt) + [assistant_msg]



def regenerate_single_slide(ollama, slide_index, current_title, current_content, user_feedback, model_selection):
    """Refine one slide from user feedback. Returns exactly two updates: (title, content)."""
    if not (user_feedback or "").strip():
        gr.Warning("Please provide feedback before re-generating.")
        return gr.update(), gr.update()

    refine_prompt = [
        {"role": "system", "content": (
            "You are a professional deck layout editor. Modify the provided slide title and content "
            "based strictly on the user feedback. Return ONLY valid JSON with keys 'title' (string) and "
            "'content' (array of 3-6 short bullet strings, no bullet characters).")},
        {"role": "user", "content": f"Current Title: {current_title}\nCurrent Content: {current_content}\nUser Feedback: {user_feedback}"},
    ]

    try:
        target_model = DEFAULT_OLLAMA_MODEL if model_selection == "Default" else model_selection
        response = robust_chat_completion(
            ollama, target_model, refine_prompt,
            response_format={"type": "json_object"}, temperature=0, max_tokens=2048,
        )
        data = extract_json(response.choices[0].message.content)
        new_title = str(data.get("title", current_title)).strip() or current_title
        new_content = data.get("content", current_content)
        if isinstance(new_content, list):
            new_content = "\n".join(f"• {str(c).strip().lstrip('•-* ').strip()}" for c in new_content if str(c).strip())

        if 0 <= slide_index < len(slide_titles):
            slide_titles[slide_index] = new_title
            slide_contents[slide_index] = new_content

        gr.Info(f"Slide {slide_index + 1} updated using {target_model}")
        return gr.update(value=new_title), gr.update(value=new_content)

    except Exception as e:
        gr.Warning(f"Re-generation error: {e}")
        return gr.update(), gr.update()


# --- LIVE PROGRESS PANEL --------------------------------------------------------------------
# Long jobs run in a worker thread while a generator streams a checkpoint list + spinner to the page.
_PROGRESS = {"steps": [], "t0": 0.0}
_progress_lock = threading.Lock()

PROGRESS_CSS = """
.pg-card { border: 1px solid #2c3854; border-radius: 12px; padding: 14px 18px; background: #101725; color: #e2e8f0; }
.pg-head { display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 1.05rem; }
.pg-time { margin-left: auto; font-variant-numeric: tabular-nums; color: #93a1b8; font-weight: 400; }
.pg-spin { width: 20px; height: 20px; border: 3px solid #2c3854; border-top-color: #60a5fa; border-radius: 50%;
           animation: pg-rot 0.9s linear infinite; flex: none; }
@keyframes pg-rot { to { transform: rotate(360deg); } }
.pg-steps { list-style: none; margin: 10px 0 0 0; padding: 0; font-size: 0.93rem; }
.pg-steps li { padding: 2px 0; color: #93a1b8; }
.pg-steps li.done::before { content: "\\2713  "; color: #34d399; }
.pg-steps li.now { color: #f8fafc; }
.pg-steps li.now::before { content: "\\25B6  "; color: #60a5fa; }
.pg-steps li .t { float: right; font-variant-numeric: tabular-nums; }
"""


def progress_reset():
    with _progress_lock:
        _PROGRESS["steps"] = []
        _PROGRESS["t0"] = time.time()


def progress(msg):
    """Record a checkpoint (shown live in the page and printed to the console)."""
    with _progress_lock:
        _PROGRESS["steps"].append((time.time(), str(msg)))
    print(f"[progress] {msg}")


def _fmt_secs(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


def progress_html(done=False, error=None):
    with _progress_lock:
        steps = list(_PROGRESS["steps"])
        t0 = _PROGRESS["t0"] or time.time()
    now = time.time()
    if error:
        head = f'<span>&#10060;</span><span>Stopped: {_html.escape(str(error))[:300]}</span>'
    elif done:
        head = '<span>&#9989;</span><span>Finished</span>'
    else:
        current = _html.escape(steps[-1][1]) if steps else "Starting"
        head = f'<div class="pg-spin"></div><span>{current}&hellip;</span>'
    items = []
    for i, (ts, msg) in enumerate(steps):
        end = steps[i + 1][0] if i + 1 < len(steps) else now
        is_now = (i == len(steps) - 1) and not done and not error
        items.append(f'<li class="{"now" if is_now else "done"}">{_html.escape(msg)}'
                     f'<span class="t">{_fmt_secs(end - ts)}</span></li>')
    return (f'<div class="pg-card"><div class="pg-head">{head}'
            f'<span class="pg-time">{_fmt_secs(now - t0)}</span></div>'
            f'<ul class="pg-steps">{"".join(items)}</ul></div>')


def run_with_progress(fn, n_outputs, *args):
    """Run fn(*args) in a worker thread; yield [no-change x n_outputs] + [progress html] every second,
    then the real outputs + a final progress panel."""
    progress_reset()
    box = {}
    ctx = contextvars.copy_context()      # keeps gr.Info / gr.Warning working inside the thread

    def worker():
        try:
            box["result"] = ctx.run(fn, *args)
        except BaseException as e:        # re-raised below so Gradio shows it
            box["error"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    while t.is_alive():
        yield [gr.update() for _ in range(n_outputs)] + [progress_html()]
        t.join(timeout=1.0)
    if "error" in box:
        err = box["error"]
        yield [gr.update() for _ in range(n_outputs)] + [progress_html(error=getattr(err, "message", None) or err)]
        raise err
    yield list(box["result"]) + [progress_html(done=True)]


def slides_setup(model, slide_count=0):
    """Build the requested number of slides from the agreed conversation, render images, and fill UI slots."""
    global slide_titles, slide_contents, deck_brief, layout_recommendations, design_ready, deck_outline
    global PPT_DIR_FOLDER, ARCHIVE_DIR, SESSIONS_DIR, SLIDE_PREVIEW_DIR, SLIDE_LAYOUTS

    if not global_prompt:
        raise gr.Error("Please submit a topic and confirm the outline first.")

    # Read the current Gradio Number value at click time. A zero value means
    # automatic/maximum mode; otherwise constrain extraction to the requested N.
    try:
        requested_count = int(float(slide_count or 0))
    except (TypeError, ValueError):
        requested_count = 0
    requested_count = requested_count if requested_count > 0 else MAX_SLIDES
    requested_count = max(1, min(requested_count, MAX_SLIDES))

    # The approved outline in the chat is the source of truth for the slide count.
    outline_titles = outline_titles_from_conversation(global_prompt)
    print(f"[slides] outline items found: {len(outline_titles)}; target count field: {requested_count}")

    progress("Reading the approved outline")
    progress(f"Drafting slide content with {model}")
    try:
        slides = slides_from_conversation(ollama, global_prompt, model, requested_count,
                                          expected_titles=outline_titles)
        PPT_DIR_FOLDER, ARCHIVE_DIR, SESSIONS_DIR, SLIDE_PREVIEW_DIR, SLIDE_LAYOUTS = folders_setup(ollama, global_prompt[-1]['content'], model=model)
        configure_project_paths(PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)
    except Exception as e:
        raise gr.Error(str(e))

    slide_titles = [t for t, _ in slides]
    slide_contents = [c for _, c in slides]
    # keep the approved outline: layout planning and slide structuring use it for story context,
    # and it is saved with the checkpoint so a resumed project keeps it
    deck_outline = {i + 1: t for i, t in enumerate(outline_titles or slide_titles)}
    from slide_renderer import SLIDE_STRUCTURED, SLIDE_TEMPLATES
    SLIDE_STRUCTURED.clear()
    SLIDE_TEMPLATES.clear()

    # During content generation, let the local LLM select a few high-value evidence
    # questions. Only those questions are sent to configured online research APIs.
    SLIDE_SOURCE_FOOTERS.clear()
    progress("Researching evidence for the slides")
    try:
        enriched, research_sources, research_status = enrich_slides_with_research(
            ollama, model, _outline_text(),
            [{"title": title, "content": content} for title, content in slides],
        )
        slide_contents = [entry.get("content", slide_contents[i]) for i, entry in enumerate(enriched)]
        for slide_idx, source_info in research_sources.items():
            SLIDE_SOURCE_FOOTERS[int(slide_idx)] = source_info.get("sources", [])
        if research_status.startswith("Research skipped"):
            gr.Warning(research_status)
        else:
            gr.Info(research_status)
    except Exception as e:
        research_status = f"Research enrichment skipped after an error: {e}"
        print(f"[research] {research_status}")

    slides = list(zip(slide_titles, slide_contents))

    # one design brief for the whole deck -> every slide gets the same palette, shapes and style
    progress("Designing the deck's visual style")
    deck_brief = deck_design_brief(slide_titles, model) or None
    print(deck_brief)

    # ComfyUI is started ONCE for the whole deck and shut down afterwards, which frees its VRAM
    # One failed image must not stop the rest of the deck: try every slide, retry each once, and
    # print the real error to the console (a toast alone is easy to miss).
    failed_images = []
    progress("Starting the image generator (ComfyUI) - the first start can take a minute")
    try:
        with comfyui_session(model):
            for i, (title, content) in enumerate(slides):
                prefix = os.path.join(SLIDE_PREVIEW_DIR, f"slide_{i + 1}")
                progress(f"Generating background image {i + 1}/{len(slides)}")
                for attempt in (1, 2):
                    try:
                        comfyui_img_generator(title, content, prefix, brief=deck_brief)
                        print(f"[comfyui] slide {i + 1}: background generated")
                        break
                    except Exception as e:
                        print(f"[comfyui] slide {i + 1} background attempt {attempt}/2 failed: {e}")
                        if attempt == 2:
                            failed_images.append(f"slide {i + 1}: {str(e)[:200]}")
                        else:
                            time.sleep(3)
    except Exception as e:
        print(f"[comfyui] could not run the image batch: {e}")
        gr.Warning(f"Could not start ComfyUI: {e}")
    if failed_images:
        gr.Warning("Background generation failed for " + "; ".join(failed_images))

    progress("Choosing a layout for each slide")
    # the LLM recommends a layout per slide - the user can still change any of them
    try:
        picks = recommend_layouts(
            ollama, model, _outline_text(),
            [{"title": t, "content": c} for t, c in slides],
        )
    except Exception as e:
        gr.Warning(f"Layout recommendation failed ({e}); a heuristic layout was used instead.")
        picks = []

    layout_recommendations = {int(p.get("number", i + 1)): p for i, p in enumerate(picks)}
    layout_ids = [p.get("layout_id") for p in picks]

    # Initialization now creates complete editable slides immediately, using the LLM's
    # recommended layout. The user can inspect the real slide and change its layout later.
    from slide_renderer import SLIDE_STRUCTURED, SLIDE_TEMPLATES
    for i, (title, raw_content) in enumerate(slides):
        progress(f"Structuring and rendering slide {i + 1}/{len(slides)}: {title[:50]}")
        rec = layout_recommendations.get(i + 1, {})
        selected_layout = rec.get("layout_id") or (layout_ids[i] if i < len(layout_ids) else "")
        template = _resolve_template(selected_layout, title, raw_content)
        try:
            data = structure_for_layout(ollama, model, template, title, raw_content, _outline_text())
        except Exception as e:
            print(f"[initialize] Slide {i + 1} LLM structuring failed; using fallback: {e}")
            data = coerce_content(template, title, raw_content)
        from slide_renderer import _attach_source_footer
        _attach_source_footer(data, i)
        SLIDE_STRUCTURED[i] = data
        SLIDE_TEMPLATES[i] = template.id
        slide_contents[i] = flatten_content(data) or raw_content
        try:
            build_slide(template, data, i)
        except Exception as e:
            gr.Warning(f"Slide {i + 1} content was prepared, but rendering failed: {e}")

    updates = build_slide_updates(MAX_SLIDES, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR, slide_titles, slide_contents, layout_ids)
    # Keep Gradio State components synchronized with the newly created project paths.
    note_updates = []
    for i in range(MAX_SLIDES):
        selected = LAYOUT_LABELS[1]
        if i < len(slide_titles):
            selected = next((label for label in LAYOUT_LABELS
                             if layout_recommendations.get(i + 1, {}).get("layout_id", "") in label),
                            LAYOUT_LABELS[1])
        note_updates.append(gr.update(value=_layout_note(i, selected)))
    # First checkpoint is created only after the slide generation/initial rendering pass.
    progress("Saving the first checkpoint")
    default_session_name = os.path.basename(os.path.normpath(PPT_DIR_FOLDER))
    initial_states = []
    for i in range(MAX_SLIDES):
        title = slide_titles[i] if i < len(slide_titles) else ""
        content = slide_contents[i] if i < len(slide_contents) else ""
        rec = layout_recommendations.get(i + 1, {})
        layout_id = rec.get("layout_id", "")
        selected_template = get_template(layout_id) if layout_id else _resolve_template("", title, content)
        layout_label = selected_template.label if selected_template else LAYOUT_LABELS[1]
        initial_states.extend([title, content, layout_label, ""])
    checkpoint_result = save_user_session(SESSIONS_DIR, MAX_SLIDES, default_session_name,
                                           len(slide_titles), _outline_text(), *initial_states)
    if checkpoint_result.startswith("💾"):
        _add_checkpoint_metadata(default_session_name, SESSIONS_DIR)
    else:
        print(f"[checkpoint] Initial save skipped: {checkpoint_result}")

    design_ready = True
    return [gr.update(value=SESSIONS_DIR), gr.update(value=PPT_DIR_FOLDER), gr.update(value=SLIDE_PREVIEW_DIR),
            gr.update(value=default_session_name), gr.update(interactive=True)] + updates + note_updates


message_input = gr.Textbox(label="Presentation Topic", info="Hi, please share a brief overview of the presentation topic: ", lines=7)
model_selector = gr.Dropdown(model_list, label="Select Model", value=DEFAULT_OLLAMA_MODEL)
message_output = gr.Markdown(label="Response:")

title_textboxes = []
content_textboxes = []
slide_image_components = []
layout_note_components = []


def reset_chat():
    global p_cnt, global_prompt, deck_outline, summary_stages, slide_titles, slide_contents, deck_brief, design_ready
    global PPT_DIR_FOLDER, ARCHIVE_DIR, SESSIONS_DIR, SLIDE_PREVIEW_DIR, SLIDE_LAYOUTS
    deck_brief = None
    design_ready = False
    PPT_DIR_FOLDER = ARCHIVE_DIR = SESSIONS_DIR = SLIDE_PREVIEW_DIR = SLIDE_LAYOUTS = ""
    configure_project_paths("", "")
    p_cnt = 0
    global_prompt = []
    deck_outline = {}
    summary_stages = []
    slide_titles = [""] * MAX_SLIDES
    slide_contents = [""] * MAX_SLIDES
    # Returns: message_input, message_output, workspace_section, generate_btn, save_state_btn
    return "", "", gr.update(visible=False), gr.update(value=INITIALIZE_LABEL), gr.update(interactive=False)


def submit_lock():
    return gr.update(interactive=False, value="Generating..."), gr.update(interactive=False), gr.update(interactive=False)

def submit_unlock():
    return gr.update(interactive=True, value="Submit"), gr.update(interactive=True), gr.update(interactive=True)

def initialize_lock():
    return gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False, value="Generating Slides...")

def initialize_unlock():
    return gr.update(interactive=True), gr.update(interactive=True), gr.update(interactive=True, value=REGENERATE_LABEL if design_ready else INITIALIZE_LABEL)


def make_refresh_handler(slide_idx):
    def handler(current_t, current_c, feedback, model):
        return regenerate_single_slide(ollama, slide_idx, current_t, current_c, feedback, model)
    return handler


def title_values():
    return list(slide_titles)


def make_image_handler(slide_idx):
    def handler(current_t, current_c):
        global deck_brief
        if not (current_t or "").strip():
            raise gr.Error("This slide has no title yet.")
        prefix = os.path.join(SLIDE_PREVIEW_DIR, f"slide_{slide_idx + 1}")
        try:
            if deck_brief is None:   # e.g. after loading a saved session: create one and keep it for the rest of the deck
                deck_brief = deck_design_brief([t for t in title_values() if t] or [current_t]) or None
            comfyui_img_generator(current_t, current_c, prefix, brief=deck_brief)
        except Exception as e:
            raise gr.Error(f"Image generation failed (is ComfyUI running?): {e}")

        # a new backdrop means the slide has to be re-rendered on top of it
        data = SLIDE_STRUCTURED.get(slide_idx)
        if data:
            from slide_renderer import _resolve_template, build_slide
            template = _resolve_template(
                get_template(SLIDE_TEMPLATES.get(slide_idx, "")), current_t, current_c)
            try:
                build_slide(template, data, slide_idx)
            except Exception as e:
                gr.Warning(f"Could not re-render the slide: {e}")
        return image_path_for(slide_idx, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)
    return handler


# --------------------------------------------------------------------------------------
# LAYOUT TEMPLATE LIBRARY HELPERS
# --------------------------------------------------------------------------------------

def _template_info(layout_label):
    """Markdown describing a template (used by the library panel)."""
    tpl = get_template(layout_label)
    if tpl is None:
        return "Pick a template in the gallery to see what it is for."
    return (
        f"### {tpl.id} · {tpl.name}\n"
        f"**Family:** {tpl.family}\n\n"
        f"**Use it when:** {tpl.best_for}\n\n"
        f"**Content pattern:** {tpl.content_pattern}\n\n"
        f"**Look:** {tpl.implementation}\n\n"
        f"**Density:** {tpl.density}"
    )


def _layout_info_for(layout_label):
    """Template information only (used when the user changes the dropdown)."""
    tpl = get_template(layout_label)
    if tpl is None:
        return "⚠️ Unknown layout - pick one from the list."
    return (f"**{tpl.id} · {tpl.name}** ({tpl.family})\n\n"
            f"{tpl.best_for}\n\n"
            f"*Content pattern:* {tpl.content_pattern}")


def _layout_note(slide_index, layout_label):
    """Per slide note: what the LLM recommended and what is currently selected."""
    rec = layout_recommendations.get(slide_index + 1, {})
    lines = []
    if rec:
        lines.append(f"🤖 **LLM recommendation:** `{rec.get('layout_id', '')}` — {rec.get('reason', '')}")
    lines.append(_layout_info_for(layout_label))
    return "\n\n".join(lines)


def make_layout_note_handler(slide_idx):
    """Rebuild the per-slide layout note whenever the dropdown changes."""
    def handler(layout_label):
        return _layout_note(slide_idx, layout_label)
    return handler


def _apply_pick(picked_label):
    """Apply a template that was picked in a gallery to a slide."""
    if not picked_label:
        raise gr.Error("Select a template in the gallery first.")
    return gr.update(value=picked_label)


def make_generate_slide_handler(slide_idx):
    """Generate/re-generate the artwork and the editable slide as one operation."""
    def handler(title, content, layout, model_selection):
        global deck_brief
        target_model = DEFAULT_OLLAMA_MODEL if model_selection in ("Default", None, "") else model_selection
        image_status = ""
        if not (title or "").strip():
            return (gr.update(), gr.update(), gr.update(), gr.update(),
                    "⚠️ Add a title before generating this slide.")
        try:
            if deck_brief is None:
                deck_brief = deck_design_brief([t for t in title_values() if t] or [title], target_model) or None
            prefix = os.path.join(SLIDE_PREVIEW_DIR, f"slide_{slide_idx + 1}")
            comfyui_img_generator(title, content, prefix, brief=deck_brief, llm_model=target_model)
            image_status = "🖼️ New background generated. "
        except Exception as exc:
            image_status = f"⚠️ Background generation failed; using the existing background if available ({exc}). "
        result = generate_slide(ollama, target_model, slide_idx, title, content, layout, _outline_text())
        if len(result) == 5 and isinstance(result[4], str):
            result = result[:4] + (image_status + result[4],)
        return result
    return handler


def _generate_all_slides(session_name, model, *slide_states):
    """Regenerate artwork and render every titled slide; compilation is a separate action."""
    global deck_brief
    from slide_renderer import _resolve_template, build_slide
    from layout_manager import structure_for_layout, flatten_content

    outline = _outline_text()
    content_updates = []
    image_updates = []
    built = 0
    errors = []

    # Generate artwork as one ComfyUI batch, then let Ollama structure the slides
    # after ComfyUI has released its VRAM. This keeps the image + slide workflow unified
    # without restarting ComfyUI for every slide.
    titled = []
    for i in range(MAX_SLIDES):
        title = (slide_states[i * 4] or "").strip()
        content = slide_states[i * 4 + 1] or ""
        if title:
            titled.append((i, title, content))
    if titled:
        try:
            if deck_brief is None:
                deck_brief = deck_design_brief([title for _, title, _ in titled], model) or None
            progress("Designing the deck's visual style")
            progress("Starting the image generator (ComfyUI) - the first start can take a minute")
            with comfyui_session(model):
                for i, title, content in titled:
                    progress(f"Generating background image {i + 1}/{len(titled)}: {title[:50]}")
                    try:
                        comfyui_img_generator(title, content,
                                              os.path.join(SLIDE_PREVIEW_DIR, f"slide_{i + 1}"),
                                              brief=deck_brief, llm_model=model)
                    except Exception as e:
                        print(f"[comfyui] slide {i + 1} background failed: {e}")
                        errors.append(f"slide {i + 1} background: {e}")
        except Exception as e:
            errors.append(f"ComfyUI batch: {e}")

    for i in range(MAX_SLIDES):
        idx = i * 4
        title = (slide_states[idx] or "").strip()
        content = slide_states[idx + 1] or ""
        layout = slide_states[idx + 2] or ""
        if not title:
            content_updates.append(gr.update(value=content))
            image_updates.append(gr.update(value=image_path_for(i, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)))
            continue
        progress(f"Structuring and rendering slide {i + 1}: {title[:50]}")
        template = _resolve_template(layout, title, content)
        try:
            data = structure_for_layout(ollama, model, template, title, content, outline)
        except Exception as e:
            errors.append(f"slide {i + 1}: {e}")
            data = coerce_content(template, title, content)
        from slide_renderer import _attach_source_footer
        _attach_source_footer(data, i)
        SLIDE_STRUCTURED[i] = data
        SLIDE_TEMPLATES[i] = template.id
        try:
            _, png = build_slide(template, data, i)
            image_updates.append(gr.update(value=png))
            content_updates.append(gr.update(value=flatten_content(data) or content))
            built += 1
        except Exception as e:
            errors.append(f"slide {i + 1} render: {e}")
            image_updates.append(gr.update(value=image_path_for(i, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)))
            content_updates.append(gr.update(value=content))

    requested = len(titled)
    if errors:
        status = (f"🎬 Regenerated {built}/{requested} titled slide(s). Compilation has not run; use Compile when ready.\n\n⚠️ "
                  + "; ".join(errors[:8]))
    else:
        status = (f"🎬 Regenerated all {built} titled slide(s). Each slide has its own numbered output path. "
                  "Review the previews, then use Compile to create the final PowerPoint.")
    # Clear any old download so it cannot be mistaken for the newly generated slides.
    return [None, status] + content_updates + image_updates


def initialize_or_regenerate(model, slide_count, session_name, *slide_states):
    """One button, two jobs.

    First click: build the deck from the approved outline (slides_setup).
    Afterwards ("Regenerate Slide Design"): keep the current titles, content and layouts, but
    write a NEW deck design brief, regenerate EVERY background image, and re-render all slides.
    """
    if not design_ready:
        return list(slides_setup(model, slide_count)) + [gr.update(), gr.update()]

    global deck_brief
    deck_brief = None   # forces a fresh design brief (new colours/shapes/style) for the whole deck
    # Use the model picked in the main selector; "Default" only exists on per-slide selectors.
    target_model = DEFAULT_OLLAMA_MODEL if model in ("Default", None, "") else model
    result = _generate_all_slides(session_name, target_model, *slide_states)
    download_update, status = result[0], result[1]
    content_updates = result[2:2 + MAX_SLIDES]
    image_updates = result[2 + MAX_SLIDES:2 + 2 * MAX_SLIDES]

    # same shape as slides_setup's outputs: 6 leading items, 6 per slide (box, title, content,
    # layout, image, feedback), then one layout note per slide -> leave everything untouched
    # except each slide's content and image.
    n_slots = 6 + MAX_SLIDES * 6 + MAX_SLIDES
    out = [gr.update() for _ in range(n_slots)]
    for i in range(MAX_SLIDES):
        out[6 + i * 6 + 2] = content_updates[i]
        out[6 + i * 6 + 4] = image_updates[i]
    status = status.replace("🎬 Regenerated", "🎨 New design: regenerated", 1)
    return out + [download_update, status]


def _sync_generate_button(*titles):
    """Set the button label from whether slides exist (used after loading a saved session)."""
    global design_ready
    design_ready = any((t or "").strip() for t in titles)
    return gr.update(value=REGENERATE_LABEL if design_ready else INITIALIZE_LABEL)


def compile_current_presentation(ppt_dir_folder, max_slides, session_name, *slide_states):
    """Compile from current UI state, repairing missing title/content values from initialized state.

    Gradio's compile inputs are four values per slide: title, content, layout, feedback.
    If the UI payload unexpectedly contains only one titled slide while the initialized
    in-process deck contains more, preserve the initialized titles/content rather than
    silently writing a one-slide PowerPoint. Layout/feedback values from the UI are kept.
    """
    from slide_renderer import STATE_STEP
    try:
        limit = max(1, min(int(max_slides), MAX_SLIDES))
    except (TypeError, ValueError):
        limit = MAX_SLIDES

    states = list(slide_states)
    expected = limit * STATE_STEP
    if len(states) < expected:
        states.extend([""] * (expected - len(states)))
    elif len(states) > expected:
        states = states[:expected]

    ui_titled = [i for i in range(limit) if str(states[i * STATE_STEP] or "").strip()]
    initialized_titled = [i for i in range(min(limit, len(slide_titles)))
                          if str(slide_titles[i] or "").strip()]

    # Defensive recovery for the exact failure mode reported: the UI sends only slide 1,
    # but the initialized deck still has multiple titles in memory.
    if len(ui_titled) <= 1 and len(initialized_titled) > 1:
        print(f"[compile] UI supplied {len(ui_titled)} titled slide(s), but initialized deck has "
              f"{len(initialized_titled)}. Restoring missing title/content fields from initialized state.")
        for i in initialized_titled:
            idx = i * STATE_STEP
            if not str(states[idx] or "").strip():
                states[idx] = slide_titles[i]
            if not str(states[idx + 1] or "").strip() and i < len(slide_contents):
                states[idx + 1] = slide_contents[i]
            if not str(states[idx + 2] or "").strip():
                rec = layout_recommendations.get(i + 1, {})
                layout_id = rec.get("layout_id", "")
                template = get_template(layout_id) if layout_id else None
                states[idx + 2] = template.label if template else _resolve_template("", slide_titles[i], slide_contents[i]).label

    return compile_presentation_file(ppt_dir_folder, limit, session_name, *states)


# The page background is always dark, but Gradio picks its text colours from the viewer's device
# setting - on a light-mode phone/laptop that gave dark text on a dark page. Force dark mode and
# white text everywhere so the page reads the same on every device.
FORCE_DARK_JS = """
() => {
    document.documentElement.style.colorScheme = 'dark';
    document.body.classList.add('dark');
    const url = new URL(window.location.href);
    if (url.searchParams.get('__theme') !== 'dark') {
        url.searchParams.set('__theme', 'dark');
        window.location.replace(url.toString());
    }
}
"""
WHITE_TEXT_CSS = """
.gradio-container, .dark .gradio-container, .gradio-container * {
    --body-text-color: #f8fafc !important;
    --body-text-color-subdued: #e2e8f0 !important;
    --block-title-text-color: #f8fafc !important;
    --block-label-text-color: #f8fafc !important;
    --block-info-text-color: #cbd5e1 !important;
    --input-placeholder-color: #94a3b8 !important;
    --link-text-color: #93c5fd !important;
    --neutral-950: #f8fafc;
}
.gradio-container, .gradio-container label, .gradio-container span, .gradio-container p,
.gradio-container h1, .gradio-container h2, .gradio-container h3, .gradio-container li,
.gradio-container .prose, .gradio-container .prose *, .gradio-container .md, .gradio-container .md *,
.gradio-container button.secondary, .gradio-container [data-testid="block-info"] {
    color: #f8fafc;
}
.gradio-container [data-testid="block-info"] { color: #cbd5e1; }
.gradio-container button.primary, .gradio-container button.primary * { color: #ffffff; }
"""

with gr.Blocks(theme=unified_theme, title="Local Deck Compiler", css=dark_panel_css + PROGRESS_CSS + WHITE_TEXT_CSS, js=FORCE_DARK_JS) as demo:
    sessions_dir_state = gr.State(SESSIONS_DIR)
    max_slides_var = gr.State(MAX_SLIDES)
    ppt_dir_folder_var = gr.State(PPT_DIR_FOLDER)
    slide_preview_var = gr.State(SLIDE_PREVIEW_DIR)
    gr.Markdown("# 🎬 AI Presentation Studio & Design Engine Workspace", elem_id="app-header")

    # --- PROFILES & TRACKING ENGINE CONTROLS ---
    with gr.Group():
        gr.Markdown("---")
        with gr.Accordion(label="📁 Project Session Management Console", open=False):
            gr.Markdown("## Session Management")
            gr.Markdown("---")
            gr.HTML("<div style='height: 1px;'></div>")
            with gr.Row():
                session_input = gr.Textbox(
                    label="📁 Local Project Session Identifier Name",
                    placeholder="Enter workspace profiles target title name (e.g., Marketing-Q4-Deck)...",
                    scale=2
                )
                save_state_btn = gr.Button("💾 Save Current Session", interactive=False)
                load_state_btn = gr.Button("📂 Resume Old Session")
            with gr.Row():
                saved_sessions_dropdown = gr.Dropdown(
                    choices=_list_saved_sessions(), value=None, interactive=True, scale=4,
                    label="Saved projects (pick one to resume - or type a session name above)",
                )
                refresh_sessions_btn = gr.Button("🔄 Refresh list", scale=1)
        status_marquee = gr.Markdown("---")

        gr.Markdown("---")
        gr.HTML("<div style='height: 25px;'></div>")
        gr.Markdown("## 🧑‍🏫 Describe the Presentation Topic")
        gr.Markdown("---")
        gr.HTML("<div style='height: 1px;'></div>")

        with gr.Row():
            with gr.Column(scale=1):
                model_selector.render()
                message_input.render()
                count_input = gr.Number(
                    label="Slide Target Count", value=0, precision=0, minimum=0, maximum=MAX_SLIDES,
                    interactive=True, info="upto 25 slides; 0 for auto"
                )
                with gr.Row():
                    reset_btn = gr.Button("Reset Chat")
                    submit_btn = gr.Button("Submit", variant="primary")
            with gr.Column(scale=2):
                message_output.render()
        inputs = [model_selector, message_input, count_input]

        with gr.Row():
            gr.HTML("<div style='width: 1px;'></div>")
            with gr.Column(scale=5):
                gr.HTML("<div style='height: 25px;'></div>")
                generate_btn = gr.Button("✨ Initialize Slides", variant="primary")
                progress_box = gr.HTML(value="")
            gr.HTML("<div style='width: 1px;'></div>")

        # --- DYNAMIC GRID INTERACTIVE COMPONENT WORKSPACE ---
        generation_events = []
        render_events = []
        # ui_slots  : UI_STEP (6) per slide  -> slide_box, title, content, layout, image, feedback
        # state_components_to_persist : STATE_STEP (4) per slide -> title, content, layout, feedback
        # Keep these in sync with UI_STEP / STATE_STEP in slide_renderer.py!
        state_components_to_persist = []
        ui_slots = []
        layout_gallery_components = []

        with gr.Column(visible=False, elem_id="workspace-section") as workspace_section:

            gr.HTML("<div style='height: 25px;'></div>")
            gr.Markdown("## 🛠️ Slides Content and Layout")
            gr.Markdown("---")
            gr.HTML("<div style='height: 1px;'></div>")

            for i in range(MAX_SLIDES):
                with gr.Accordion(label=f'Slide {i+1}: ', open=True) as slide_box:
                    gr.Markdown(f"## 🖼️ Slide {i+1}")

                    with gr.Row(equal_height=True):
                        # SLIDE CONTENTS
                        with gr.Column(scale=3):
                            title_textbox = gr.Textbox(value="", label=f"Slide {i+1} Title")
                            content_textbox = gr.TextArea(value="", label=f"Slide {i+1} Contents", lines=10)
                            title_textboxes.append(title_textbox)
                            content_textboxes.append(content_textbox)

                        # SLIDE IMAGE - stays EMPTY until this slide has been generated
                        with gr.Column(scale=3):
                            slide_image_component = gr.Image(
                                value=image_path_for(i, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR),
                                label=f"Slide {i+1} preview",
                                show_label=False,
                                type="filepath",
                                interactive=False,
                                height=SLIDE_PANEL_HEIGHT,
                                elem_classes=["slide-image"],
                            )
                            slide_image_components.append(slide_image_component)

                    with gr.Row():
                        with gr.Column(scale=2):
                            model_selector_slide = gr.Dropdown(["Default"] + model_list, label="Select model", value="Default", interactive=True)
                        with gr.Column(scale=8):
                            user_feedback_box = gr.Textbox(
                                label="User Feedback",
                                placeholder="Please share your feedback here..."
                            )

                    # --- LAYOUT SELECTOR - one per slide ---
                    with gr.Accordion(label=f'🎨 Layout for Slide {i+1}', open=False):
                        with gr.Row():
                            with gr.Column(scale=2):
                                slide_layout = gr.Dropdown(
                                    LAYOUT_LABELS,
                                    label="Selected Layout (LLM recommended - change it any time)",
                                    value=LAYOUT_LABELS[1],
                                    interactive=True,
                                )
                            with gr.Column(scale=3):
                                layout_note = gr.Markdown(_layout_note(i, LAYOUT_LABELS[1]))
                                layout_note_components.append(layout_note)

                        gr.Markdown("**Template gallery** — click a layout to use it for this slide:")
                        layout_gallery = gr.Gallery(
                            value=_gallery_items_for(LAYOUT_LABELS[1]),
                            columns=LAYOUT_GALLERY_COLUMNS,
                            height=420,
                            allow_preview=False,
                            show_label=True,
                            object_fit="contain",
                            elem_classes=["template-gallery"],
                            label=f"Choose a layout for slide {i+1} (selected layout is marked ✓)",
                        )
                        layout_gallery_components.append(layout_gallery)
                        slide_status = gr.Markdown("")

                    with gr.Row():
                        render_btn = gr.Button(f"🎨 Update slide {i+1} content", variant="secondary")
                        generate_slide_btn = gr.Button(f"🎬 Generate slide {i+1}", variant="primary")

                    gr.HTML("<div style='height: 25px;'></div>")

                    # clicking a template in THIS slide's gallery selects it for THIS slide
                    layout_gallery.select(
                        fn=on_thumbnail_select,
                        inputs=[slide_layout],
                        outputs=[slide_layout, layout_gallery],
                    )

                    def _layout_change_with_gallery(layout_label, slide_idx=i):
                        return _layout_note(slide_idx, layout_label), _gallery_items_for(layout_label)

                    slide_layout.change(
                        fn=_layout_change_with_gallery,
                        inputs=[slide_layout],
                        outputs=[layout_note, layout_gallery],
                    )

                    generated_slide_event = generate_slide_btn.click(
                        fn=make_generate_slide_handler(i),
                        inputs=[title_textbox, content_textbox, slide_layout, model_selector_slide],
                        outputs=[title_textbox, content_textbox, slide_layout,
                                 slide_image_component, slide_status],
                    )
                    generation_events.append(generated_slide_event)

                    render_event = render_btn.click(
                        fn=make_refresh_handler(i),
                        inputs=[title_textbox, content_textbox, user_feedback_box, model_selector_slide],
                        outputs=[title_textbox, content_textbox]
                    )
                    render_events.append(render_event)

                    state_components_to_persist.extend([
                        title_textbox, content_textbox, slide_layout, user_feedback_box
                    ])
                    ui_slots.extend([
                        slide_box, title_textbox, content_textbox, slide_layout,
                        slide_image_component, user_feedback_box
                    ])

            # Save the complete current state after any slide generation/render action.
            # These handlers are attached only after all slide state components exist.
            checkpoint_inputs = [sessions_dir_state, max_slides_var, session_input, count_input, message_input] + state_components_to_persist
            for event in generation_events + render_events:
                event.then(fn=_save_current_session, inputs=checkpoint_inputs, outputs=status_marquee)
            # Persist text, layout and feedback edits on blur/change once the project exists.
            # Text boxes save when the user leaves the box (not on every keystroke, and not while
            # the app itself is filling them in); dropdown layout choices save when they change.
            for component in state_components_to_persist:
                trigger = component.change if isinstance(component, gr.Dropdown) else component.blur
                trigger(fn=_save_current_session, inputs=checkpoint_inputs, outputs=status_marquee)

            # --- COMPILATION CONTROL TERMINAL PANEL LAYER ---
            gr.Markdown("---")

            progress_box_all = gr.HTML(value="")
            with gr.Row(elem_id="compile-action-bar"):
                with gr.Column(scale=5):
                    with gr.Row():
                        generate_all_btn = gr.Button("🎬 Generate all slides", variant="primary")
                        compile_btn = gr.Button("📦 Compile", variant="primary")

            with gr.Accordion(label='File Outputs', open=False):
                with gr.Column(scale=2):
                    compilation_output_box = gr.Markdown()
                with gr.Column(scale=1):
                    download_file_widget = gr.File(label="Download PowerPoint (.pptx)")

        # --- EVENT ROUTERS ---
        step1_outputs = [sessions_dir_state, ppt_dir_folder_var, slide_preview_var, session_input, save_state_btn, workspace_section] + ui_slots + layout_note_components
        n_init_outputs = len(step1_outputs) + 2

        def _initialize_with_progress(*args):
            yield from run_with_progress(initialize_or_regenerate, n_init_outputs, *args)

        generate_btn.click(initialize_lock, None, [submit_btn, reset_btn, generate_btn]).then(
            fn=_initialize_with_progress,
            inputs=[model_selector, count_input, session_input] + state_components_to_persist,
            outputs=step1_outputs + [download_file_widget, compilation_output_box, progress_box]
        ).then(
            fn=_save_current_session,
            inputs=[sessions_dir_state, max_slides_var, session_input, count_input, message_input] + state_components_to_persist,
            outputs=status_marquee,
        ).then(_refresh_saved_sessions, None, saved_sessions_dropdown).then(initialize_unlock, None, [submit_btn, reset_btn, generate_btn])

        save_state_btn.click(
            fn=_save_current_session,
            inputs=[sessions_dir_state, max_slides_var, session_input, count_input, message_input] + state_components_to_persist,
            outputs=status_marquee
        )

        load_state_btn.click(
            fn=_resume_clicked,
            inputs=[saved_sessions_dropdown, sessions_dir_state, max_slides_var, ppt_dir_folder_var, slide_preview_var, session_input],
            outputs=[status_marquee, count_input, message_input, workspace_section,
                     sessions_dir_state, ppt_dir_folder_var, slide_preview_var, session_input, save_state_btn] + ui_slots + layout_note_components + layout_gallery_components + [message_output]
        ).then(fn=_sync_generate_button, inputs=title_textboxes, outputs=generate_btn)

        n_all_outputs = 2 + len(content_textboxes) + len(slide_image_components)

        def _generate_all_with_progress(*args):
            yield from run_with_progress(_generate_all_slides, n_all_outputs, *args)

        generate_all_event = generate_all_btn.click(
            fn=_generate_all_with_progress,
            inputs=[session_input, model_selector] + state_components_to_persist,
            outputs=[download_file_widget, compilation_output_box] + content_textboxes + [c for c in slide_image_components] + [progress_box_all],
        )
        generate_all_event.then(
            fn=_save_current_session,
            inputs=[sessions_dir_state, max_slides_var, session_input, count_input, message_input] + state_components_to_persist,
            outputs=status_marquee,
        )

        compile_event = compile_btn.click(
            fn=compile_current_presentation,
            inputs=[ppt_dir_folder_var, max_slides_var, session_input] + state_components_to_persist,
            outputs=[download_file_widget, compilation_output_box]
        )
        compile_event.then(
            fn=_save_current_session,
            inputs=[sessions_dir_state, max_slides_var, session_input, count_input, message_input] + state_components_to_persist,
            outputs=status_marquee,
        )

        submit_btn.click(submit_lock, None, [submit_btn, reset_btn, generate_btn]).then(
            response_streamer_outline, inputs, message_output, show_progress="full"
        ).then(submit_unlock, None, [submit_btn, reset_btn, generate_btn])

        message_input.submit(
            response_streamer_outline, inputs, message_output, show_progress="full"
        )

        refresh_sessions_btn.click(_refresh_saved_sessions, None, saved_sessions_dropdown)
        demo.load(_refresh_saved_sessions, None, saved_sessions_dropdown)

        reset_btn.click(reset_chat, None, [message_input, message_output, workspace_section, generate_btn, save_state_btn])


if __name__ == "__main__":
    # Optional public link (set in .env): GRADIO_SHARE=1 creates a temporary *.gradio.live URL that
    # tunnels to THIS machine. Always protect it with GRADIO_USER / GRADIO_PASSWORD.
    _share = os.getenv("GRADIO_SHARE", "").strip().lower() in ("1", "true", "yes")
    _user, _pass = os.getenv("GRADIO_USER", "").strip(), os.getenv("GRADIO_PASSWORD", "").strip()
    if _share and not (_user and _pass):
        raise SystemExit("GRADIO_SHARE is on but GRADIO_USER / GRADIO_PASSWORD are not set in .env. "
                         "Refusing to publish an open link to your GPU; set both and restart.")
    demo.launch(
        inbrowser=not _share,
        share=_share,
        auth=(_user, _pass) if (_user and _pass) else None,
        allowed_paths=[os.path.abspath("generated_presentations"), os.path.abspath("layout_templates")],
    )
