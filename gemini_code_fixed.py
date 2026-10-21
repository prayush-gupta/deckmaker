"""Gradio helpers for the presentation studio: slot updates, session save/load and PPTX compile.

IMPORTANT - component counts per slide (this mismatch was the cause of the scrambled text):
  * UI_STEP    = 6 -> components in `ui_slots` (event OUTPUTS):
                      slide_box, title, content, layout, image, feedback
  * STATE_STEP = 4 -> components in `state_components_to_persist` (save / compile INPUTS):
                      title, content, layout, feedback
If you add or remove a component in user_context.py, change the matching constant here.

Slides are rendered with the layout template library (layout_catalogue / layout_engine /
layout_templates): the LLM recommends a layout, the user can override it, and the content is
re-structured to fit the template before the slide is written out as an editable .pptx plus a
PNG screenshot.
"""
import json
import os
import math

import gradio as gr
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from def_prompts import slide_gen_prompt
from imp_functions import response_generator
from layout_catalogue import LAYOUT_LABELS, TEMPLATES, get_template, template_label
from layout_templates import (
    build_template_previews, coerce_content, default_layout_for, find_background,
    flatten_content, render_slide,
)

# --- CONFIGURATION & CONSTANTS ---
MAX_SLIDES = 25
SESSIONS_DIR = "presentation_sessions"
OUTPUT_DIR = "generated_presentations"
PPT_DIR_FOLDER = "generated_presentations"   # single source of truth for slide images
ARCHIVE_DIR = "archive"
SLIDE_PREVIEW_DIR = "slide_previews"        # screenshots of the finished slides (main folder)

UI_STEP = 6      # slide_box, title, content, layout, image, feedback
STATE_STEP = 4   # title, content, layout, feedback

folder_counter = len(os.listdir(PPT_DIR_FOLDER))+1
PPT_DIR = f"{PPT_DIR_FOLDER}/ppt{folder_counter}"

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(f"{PPT_DIR_FOLDER}/ppt{folder_counter}", exist_ok=True)
os.makedirs(SLIDE_PREVIEW_DIR, exist_ok=True)
os.makedirs(os.path.join(PPT_DIR, "slides"), exist_ok=True)

# The layout selector gallery: one rendered preview per template, drawn on the ComfyUI
# background.  The previews are cached on disk, so this is a one-off cost per machine.
GALLERY_ITEMS = build_template_previews()
LAYOUT_NAMES = list(LAYOUT_LABELS)
TEMPLATE_BY_LABEL = {tpl.label: tpl for tpl in TEMPLATES}

# Structured content produced by the LLM for each slide (index -> layout ready data)
SLIDE_STRUCTURED: dict = {}
SLIDE_TEMPLATES: dict = {}


# --- IMAGE PATH HELPERS ---

def slide_image_file(i):
    """Path where ComfyUI saves the image for slide index i (0-based)."""
    return f"{PPT_DIR}/slide_{i + 1}_0.png"


def slide_preview_file(i):
    """PNG screenshot of the finished slide (written to the main project folder)."""
    return os.path.join(SLIDE_PREVIEW_DIR, f"slide_{i + 1}_preview.png")


def slide_pptx_file(i):
    """Single-slide .pptx produced by the per-slide generator."""
    return os.path.join(PPT_DIR, "slides", f"slide_{i + 1}.pptx")


def image_path_for(i):
    """The rendered slide for slide i - or None when the slide has not been generated yet.

    The ComfyUI backdrop is a BACKGROUND, not a slide, so it is never shown in the image
    box.  The box stays empty until the slide has actually been generated.
    """
    preview = slide_preview_file(i)
    return preview if os.path.exists(preview) else None


def clear_slide_previews():
    """Remove the screenshots of a previous deck so a new deck starts clean."""
    import glob
    removed = 0
    for old in glob.glob(os.path.join(SLIDE_PREVIEW_DIR, "slide_*_preview.png")):
        try:
            os.remove(old)
            removed += 1
        except OSError:
            pass
    return removed


# --- CORE PLATFORM EVENT HANDLERS ---

def suggest_layout(title, content=""):
    """Heuristic layout suggestion (the LLM recommendation overrides this)."""
    return default_layout_for(title or "", content or "")


def build_slide_updates(titles, contents, layout_ids=None):
    """Return [workspace_section] + UI_STEP updates for each of MAX_SLIDES slots.

    Order per slide MUST match `ui_slots` in user_context.py:
    slide_box, title, content, layout, image, feedback
    """
    count = min(len(titles), MAX_SLIDES)
    updates = [gr.update(visible=True)]  # workspace_section

    for i in range(MAX_SLIDES):
        if i < count:
            title = titles[i]
            content = contents[i] if i < len(contents) else ""
            if layout_ids and i < len(layout_ids) and layout_ids[i]:
                layout = template_label(layout_ids[i])
            else:
                layout = template_label(suggest_layout(title, content))
            updates.extend([
                gr.update(visible=True, label=f"Slide {i + 1}: {title}"),
                gr.update(value=title),
                gr.update(value=content),
                gr.update(value=layout),
                gr.update(value=image_path_for(i)),
                gr.update(value=""),
            ])
        else:  # hide and clear unused slots so stale text never reaches compile/save
            updates.extend([
                gr.update(visible=False, label=f"Slide {i + 1}: "),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=LAYOUT_LABELS[1]),
                gr.update(value=None),
                gr.update(value=""),
            ])
    return updates


def on_thumbnail_select(evt: gr.SelectData):
    """Gallery click -> layout label (uses the index, which is stable across Gradio versions)."""
    try:
        return LAYOUT_NAMES[int(evt.index)]
    except Exception:
        value = getattr(evt, "value", None)
        if isinstance(value, dict):
            return value.get("caption") or ""
        return value or ""


def first_slide_gen(topic, slide_num, deck_outline, title, content):
    system_prompt, user_prompt = slide_gen_prompt(topic, slide_num, deck_outline, title, content)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def slide_content_generator(slide_topic, deck_outline, slide_num, title, content, feedback,
                            ollama, model="llama3.1", conv_hist=None):
    if conv_hist:
        conv_hist = conv_hist + [{"role": "user", "content": feedback}]
    else:
        conv_hist = first_slide_gen(slide_topic, slide_num, deck_outline, title, content)
    response = response_generator(ollama, model, conv_hist)
    return response, conv_hist


# --- SESSION MANAGEMENT & LOCAL PERSISTENCE ---

def save_user_session(session_name, count, outline, *slide_states):
    """Packs slide parameters (STATE_STEP components per slide) into JSON."""
    if not session_name or not session_name.strip():
        return "❌ Please specify a valid Session Identifier Name first!"

    slides_data = []
    for i in range(MAX_SLIDES):
        idx = i * STATE_STEP
        slides_data.append({
            "title": slide_states[idx],
            "content": slide_states[idx + 1],
            "layout": slide_states[idx + 2],
            "feedback": slide_states[idx + 3],
        })

    session_payload = {
        "session_name": session_name,
        "slide_count": int(count or 0),
        "outline": outline,
        "slides": slides_data,
    }

    file_path = os.path.join(SESSIONS_DIR, f"{session_name.strip()}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(session_payload, f, indent=2)

    return f"💾 Session state saved safely to local storage: {file_path}"

def load_user_session(session_name):
    """Rehydrates the UI. Output order: status, count, outline, workspace, then UI_STEP per slide."""
    file_path = os.path.join(SESSIONS_DIR, f"{(session_name or '').strip()}.json")
    if not os.path.exists(file_path):
        return ["❌ Session target name not found!"] + [gr.update() for _ in range(3 + MAX_SLIDES * UI_STEP)]

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    slides = data.get("slides", [])
    # Show every slide that actually has a title (not the stored count) so nothing gets hidden
    active = [i for i in range(min(len(slides), MAX_SLIDES)) if (slides[i].get("title") or "").strip()]
    shown = (max(active) + 1) if active else 0

    updates = [
        f"📂 Successfully loaded session state profile: '{session_name}'",
        gr.update(value=data.get("slide_count", shown)),
        gr.update(value=data.get("outline", "")),
        gr.update(visible=True),
    ]

    for i in range(MAX_SLIDES):
        if i < shown:
            s = slides[i]
            title = s.get("title", "")
            # a stored layout may be an old name / id -> always fall back to a valid label
            tpl = get_template(s.get("layout", ""))
            layout = tpl.label if tpl else LAYOUT_LABELS[1]
            updates.extend([
                gr.update(visible=True, label=f"Slide {i + 1}: {title}"),
                gr.update(value=title),
                gr.update(value=s.get("content", "")),
                gr.update(value=layout),
                gr.update(value=image_path_for(i)),
                gr.update(value=s.get("feedback", "")),
            ])
        else:
            updates.extend([
                gr.update(visible=False, label=f"Slide {i + 1}: "),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=""),
                gr.update(value=None),
                gr.update(value=""),
            ])
    return updates


# --- POWERPOINT COMPILATION (layout template driven) ---

def _slide_background(index):
    """The ComfyUI backdrop for a slide, if one was generated."""
    path = slide_image_file(index)
    return path if os.path.exists(path) else None


def _resolve_template(layout_value, title="", content=""):
    """Layout value (label, id or name) -> Template. Falls back to a sensible match."""
    tpl = get_template(layout_value)
    if tpl is None:
        tpl = get_template(default_layout_for(title, content))
    if tpl is None:
        tpl = TEMPLATES[1]          # L02 - standard content
    return tpl


def build_slide(template, data, index):
    """Render one slide to .pptx + .png screenshot (both stored locally)."""
    background = _slide_background(index)
    pptx_path = slide_pptx_file(index)
    png_path = slide_preview_file(index)
    os.makedirs(os.path.dirname(os.path.abspath(pptx_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    render_slide(template, data, pptx_path, png_path, background=background, number=index + 1)
    return pptx_path, png_path


def generate_slide(ollama, model, index, title, content, layout, deck_outline=""):
    """LLM -> structured content for the template -> .pptx + PNG screenshot.

    Returns (title, content, layout, preview_path, status_message).
    """
    from layout_templates import structure_for_layout

    if not (title or "").strip():
        return (gr.update(), gr.update(), gr.update(), gr.update(),
                "⚠️ This slide has no title yet - add one before generating.")

    template = _resolve_template(layout, title, content)
    try:
        data = structure_for_layout(ollama, model, template, title, content, deck_outline)
    except Exception as e:
        data = coerce_content(template, title, content)
        return (gr.update(value=title), gr.update(value=content), gr.update(value=template.label),
                gr.update(), f"⚠️ Could not reach the model ({e}); the slide was left as it is.")

    SLIDE_STRUCTURED[index] = data
    SLIDE_TEMPLATES[index] = template.id

    try:
        pptx_path, png_path = build_slide(template, data, index)
    except Exception as e:
        return (gr.update(value=title), gr.update(value=content), gr.update(value=template.label),
                gr.update(), f"⚠️ Slide rendering failed: {e}")

    new_content = flatten_content(data) or content
    return (gr.update(value=title),
            gr.update(value=new_content),
            gr.update(value=template.label),
            gr.update(value=png_path),
            f"🎬 Slide {index + 1} rendered with **{template.id} · {template.name}**\n\n"
            f"📄 PowerPoint: `{pptx_path}`\n"
            f"🖼️ Screenshot: `{png_path}`")


def compile_presentation_file(session_name, *slide_states):
    """Builds the .pptx. Expects STATE_STEP components per slide: title, content, layout, feedback."""
    from layout_engine import build_deck_pptx

    slides = []
    backgrounds = []
    previews = []

    for i in range(MAX_SLIDES):
        idx = i * STATE_STEP
        title = (slide_states[idx] or "").strip()
        content = slide_states[idx + 1] or ""
        layout = slide_states[idx + 2] or ""
        if not title:
            continue
        template = _resolve_template(layout, title, content)
        data = SLIDE_STRUCTURED.get(i)
        # the structured content belongs to the template it was written for - if the user
        # changed the layout, fall back to a fresh fit of the raw content
        if data and SLIDE_TEMPLATES.get(i) != template.id:
            data = None
        if not data:
            data = coerce_content(template, title, content)
            SLIDE_STRUCTURED[i] = data
        SLIDE_TEMPLATES[i] = template.id
        slides.append((template, data))
        backgrounds.append(_slide_background(i))
        previews.append((i, template, data))

    if not slides:
        return None, "⚠️ Compilation stalled: Enter a title for at least one slide before compiling."

    name = (session_name or "").strip() or "Presentation"
    output_path = os.path.join(OUTPUT_DIR, f"{name}_compiled.pptx")
    build_deck_pptx(slides, output_path, backgrounds=backgrounds)

    # refresh the slide screenshots in the main folder so the user always sees the latest render
    from layout_engine import render_to_png
    for i, template, data in previews:
        png_path = slide_preview_file(i)
        try:
            render_to_png(template, data, png_path, background=_slide_background(i), number=i + 1)
        except Exception:
            pass

    return output_path, (f"🚀 **Compilation successful!** Built {len(slides)} slides using the "
                         f"layout template library.\n\n📄 `{output_path}`")
