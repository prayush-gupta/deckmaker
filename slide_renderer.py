"""Gradio helpers for the presentation studio: slot updates, session save/load and PPTX compile.

IMPORTANT - component counts per slide (this mismatch was the cause of the scrambled text):
  * UI_STEP    = 6 -> components in `ui_slots` (event OUTPUTS):
                      slide_box, title, content, layout, image, feedback
  * STATE_STEP = 4 -> components in `state_components_to_persist` (save / compile INPUTS):
                      title, content, layout, feedback
If you add or remove a component in app.py, change the matching constant here.

Slides are rendered with the layout template library (layout_catalog / slide_layout_engine /
layout_templates): the LLM recommends a layout, the user can override it, and the content is
re-structured to fit the template before the slide is written out as an editable .pptx plus a
PNG screenshot.
"""
import json
import os
import re
import math
import hashlib
import glob

from dotenv import load_dotenv

APP_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(APP_DIR, ".env"))
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "gpt-oss")

import gradio as gr
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from prompts import slide_gen_prompt
from llm_helpers import response_generator
from layout_catalog import LAYOUT_LABELS, TEMPLATES, get_template, template_label
from layout_manager import (
    build_template_previews, coerce_content, default_layout_for, find_background,
    flatten_content, render_slide,
)

UI_STEP = 6      # slide_box, title, content, layout, image, feedback
STATE_STEP = 4   # title, content, layout, feedback


# The layout selector gallery: one rendered preview per template, drawn on the ComfyUI
# background.  The previews are cached on disk, so this is a one-off cost per machine.
GALLERY_ITEMS = build_template_previews()
LAYOUT_NAMES = list(LAYOUT_LABELS)
TEMPLATE_BY_LABEL = {tpl.label: tpl for tpl in TEMPLATES}

# Structured content produced by the LLM for each slide (index -> layout ready data)
SLIDE_STRUCTURED: dict = {}
SLIDE_TEMPLATES: dict = {}
# Zero-based slide index -> sources returned by the targeted online research step.
SLIDE_SOURCE_FOOTERS: dict = {}


def _source_footer(index):
    sources = SLIDE_SOURCE_FOOTERS.get(index, []) or []
    labels = []
    seen = set()
    from urllib.parse import urlparse
    for source in sources:
        url = str(source.get("url", "")).strip()
        if not url:
            continue
        domain = urlparse(url).netloc.removeprefix("www.")
        title = " ".join(str(source.get("title") or domain).split())[:30]
        label = f"{title} ({domain})" if domain else title
        if label not in seen:
            seen.add(label)
            labels.append(label)
    if not labels:
        return ""
    shown = labels[:4]
    if len(labels) > 4:
        shown.append(f"+{len(labels) - 4} more")
    return "Sources: " + "; ".join(shown)


def _attach_source_footer(data, index):
    if not isinstance(data, dict):
        return data
    footer = _source_footer(index)
    if footer:
        data["source_footer"] = footer
    else:
        data.pop("source_footer", None)
    return data

# Active project paths are configured by app.slides_setup().
CURRENT_PPT_DIR_FOLDER = ""
CURRENT_SLIDE_PREVIEW_DIR = ""


def configure_project_paths(ppt_dir_folder="", slide_preview_dir=""):
    global CURRENT_PPT_DIR_FOLDER, CURRENT_SLIDE_PREVIEW_DIR
    CURRENT_PPT_DIR_FOLDER = ppt_dir_folder or ""
    CURRENT_SLIDE_PREVIEW_DIR = slide_preview_dir or ""


# --- IMAGE PATH HELPERS ---

def slide_image_file(i, PPT_DIR_FOLDER=None, SLIDE_PREVIEW_DIR=None):
    """Path where ComfyUI saves the image for slide index i (0-based).

    The workflow's save node appends ``_0.png`` to the requested prefix. Support
    both that real filename and the older ``slide_N.png`` naming convention.
    """
    preview_dir = SLIDE_PREVIEW_DIR or CURRENT_SLIDE_PREVIEW_DIR
    if not preview_dir:
        return None
    # image_generation.generate() downloads the current result to the canonical
    # ``slide_N.png`` path. Prefer it over the legacy ComfyUI-style ``slide_N_0.png``
    # fallback: a stale legacy file must never mask the image generated for this run.
    candidates = [
        os.path.join(preview_dir, f"slide_{i + 1}.png"),
        os.path.join(preview_dir, f"slide_{i + 1}_0.png"),
    ]
    return next((path for path in candidates if os.path.isfile(path)), candidates[0])


def slide_preview_file(i, PPT_DIR_FOLDER=None, SLIDE_PREVIEW_DIR=None):
    """PNG screenshot of the finished slide (written to the main project folder)."""
    project_dir = PPT_DIR_FOLDER or CURRENT_PPT_DIR_FOLDER
    return os.path.join(project_dir, f"slide_{i + 1}.png") if project_dir else None


def slide_pptx_file(i, PPT_DIR_FOLDER=None, SLIDE_PREVIEW_DIR=None):
    """Single-slide .pptx produced by the per-slide generator."""
    project_dir = PPT_DIR_FOLDER or CURRENT_PPT_DIR_FOLDER
    return os.path.join(project_dir, "slides", f"slide_{i + 1}.pptx") if project_dir else None


def image_path_for(i, PPT_DIR_FOLDER=None, SLIDE_PREVIEW_DIR=None):
    """Return the rendered slide preview, or the raw ComfyUI backdrop before rendering."""
    preview = slide_preview_file(i, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)
    if preview and os.path.isfile(preview):
        return preview
    # Before the editable slide is rendered, show the generated ComfyUI backdrop.
    backdrop = slide_image_file(i, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)
    return backdrop if backdrop and os.path.isfile(backdrop) else None



# --- CORE PLATFORM EVENT HANDLERS ---

def suggest_layout(title, content=""):
    """Heuristic layout suggestion (the LLM recommendation overrides this)."""
    return default_layout_for(title or "", content or "")


def build_slide_updates(MAX_SLIDES, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR, titles, contents, layout_ids=None):
    """Return [workspace_section] + UI_STEP updates for each of MAX_SLIDES slots.

    Order per slide MUST match `ui_slots` in app.py:
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
                gr.update(value=image_path_for(i, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)),
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


def _gallery_items_for(selected_label=None):
    """Return larger gallery cards, with a visible check/border on the selected layout."""
    result = []
    for path, caption in GALLERY_ITEMS:
        if caption != selected_label or not path or not os.path.isfile(path):
            result.append((path, caption))
            continue
        try:
            from PIL import Image, ImageDraw, ImageFont
            digest = hashlib.md5(caption.encode("utf-8")).hexdigest()[:10]
            marked = os.path.join(os.path.dirname(path), f"selected_{digest}_{os.path.basename(path)}.png")
            if not os.path.isfile(marked) or os.path.getmtime(marked) < os.path.getmtime(path):
                with Image.open(path) as source:
                    im = source.convert("RGB")
                draw = ImageDraw.Draw(im)
                width = max(5, im.width // 65)
                draw.rectangle((width // 2, width // 2, im.width - width // 2 - 1,
                                im.height - width // 2 - 1), outline=(34, 197, 94), width=width)
                r = max(18, im.width // 18)
                x, y = im.width - r - width * 2, r + width * 2
                draw.ellipse((x-r, y-r, x+r, y+r), fill=(34, 197, 94), outline=(255,255,255), width=max(2, width//2))
                try:
                    font = ImageFont.truetype("arial.ttf", int(r * 1.3))
                except Exception:
                    font = ImageFont.load_default()
                draw.text((x, y), "✓", fill="white", anchor="mm", font=font, stroke_width=0)
                im.save(marked)
            result.append((marked, f"✓ SELECTED · {caption}"))
        except Exception:
            result.append((path, f"✓ SELECTED · {caption}"))
    return result


def on_thumbnail_select(evt: gr.SelectData, current_layout=None):
    """Gallery click selects a layout; return both dropdown value and highlighted gallery."""
    try:
        selected = LAYOUT_NAMES[int(evt.index)]
    except Exception:
        value = getattr(evt, "value", None)
        if isinstance(value, dict):
            selected = value.get("caption") or ""
        else:
            selected = value or ""
    return selected, _gallery_items_for(selected)


def first_slide_gen(topic, slide_num, deck_outline, title, content):
    system_prompt, user_prompt = slide_gen_prompt(topic, slide_num, deck_outline, title, content)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def slide_content_generator(slide_topic, deck_outline, slide_num, title, content, feedback,
                            ollama, model=DEFAULT_OLLAMA_MODEL, conv_hist=None):
    if conv_hist:
        conv_hist = conv_hist + [{"role": "user", "content": feedback}]
    else:
        conv_hist = first_slide_gen(slide_topic, slide_num, deck_outline, title, content)
    response = response_generator(ollama, model, conv_hist)
    return response, conv_hist


# --- SESSION MANAGEMENT & LOCAL PERSISTENCE ---

def save_user_session(SESSIONS_DIR, MAX_SLIDES, session_name, count, outline, *slide_states):
    """Save a checkpoint only after at least one slide has been generated."""
    if not session_name or not session_name.strip():
        return "❌ Please specify a valid Session Identifier Name first!"
    if not SESSIONS_DIR or not os.path.isdir(SESSIONS_DIR):
        return "⚠️ Initialize and generate slides before saving a project."

    slides_data = []
    for i in range(MAX_SLIDES):
        idx = i * STATE_STEP
        slides_data.append({
            "title": slide_states[idx],
            "content": slide_states[idx + 1],
            "layout": slide_states[idx + 2],
            "feedback": slide_states[idx + 3],
        })

    if not any((item.get("title") or "").strip() for item in slides_data):
        return "⚠️ No generated slide content was found; nothing was saved."

    os.makedirs(SESSIONS_DIR, exist_ok=True)
    safe_session_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", session_name.strip()).strip(" ._") or "Presentation"
    session_payload = {
        "schema_version": 2,
        "session_name": safe_session_name,
        "slide_count": int(count or 0),
        "outline": outline,
        "slides": slides_data,
    }

    file_path = os.path.join(SESSIONS_DIR, f"{safe_session_name}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(session_payload, f, indent=2, ensure_ascii=False)

    return f"💾 Project checkpoint saved: {file_path}"

def load_user_session(SESSIONS_DIR, MAX_SLIDES, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR, session_name):
    """Find a checkpoint even after restart, then rehydrate slide UI values."""
    raw_name = (session_name or "").strip()
    safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw_name).strip(" ._")
    candidates = []
    if SESSIONS_DIR and safe_name:
        candidates.append(os.path.join(SESSIONS_DIR, f"{safe_name}.json"))
    # Project-specific SESSIONS_DIR is empty on app startup; discover saved projects globally.
    if safe_name:
        roots = {os.path.abspath("generated_presentations"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_presentations")}
        for root in roots:
            candidates.extend(sorted(glob.glob(os.path.join(root, "**", "presentation_sessions", f"{safe_name}.json"), recursive=True), reverse=True))
            candidates.extend(sorted(glob.glob(os.path.join(root, "**", f"{safe_name}.json"), recursive=True), reverse=True))
    file_path = next((path for path in candidates if os.path.isfile(path)), None)
    if not file_path:
        return ["❌ Saved project not found. Enter the project/session name shown when it was saved."] + [gr.update() for _ in range(3 + MAX_SLIDES * UI_STEP)]

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Prefer the absolute paths stored with the checkpoint, which remain stable across app restarts.
    PPT_DIR_FOLDER = data.get("PPT_DIR_FOLDER") or PPT_DIR_FOLDER
    SLIDE_PREVIEW_DIR = data.get("SLIDE_PREVIEW_DIR") or SLIDE_PREVIEW_DIR
    configure_project_paths(PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)
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
                gr.update(value=image_path_for(i, PPT_DIR_FOLDER, SLIDE_PREVIEW_DIR)),
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
    return path if path and os.path.exists(path) else None


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
    if not pptx_path or not png_path:
        raise RuntimeError("Project output paths are not configured. Initialize slides first.")
    os.makedirs(os.path.dirname(os.path.abspath(pptx_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    render_slide(template, data, pptx_path, png_path, background=background, number=index + 1)
    return pptx_path, png_path


def generate_slide(ollama, model, index, title, content, layout, deck_outline=""):
    """LLM -> structured content for the template -> .pptx + PNG screenshot.

    Returns (title, content, layout, preview_path, status_message).
    """
    from layout_manager import structure_for_layout

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

    _attach_source_footer(data, index)
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


def compile_presentation_file(PPT_DIR_FOLDER, MAX_SLIDES, session_name, *slide_states):
    """Builds the .pptx. Expects STATE_STEP components per slide: title, content, layout, feedback."""
    from slide_layout_engine import build_deck_pptx
    if PPT_DIR_FOLDER:
        configure_project_paths(PPT_DIR_FOLDER, CURRENT_SLIDE_PREVIEW_DIR)
    if not (PPT_DIR_FOLDER or CURRENT_PPT_DIR_FOLDER):
        return None, "⚠️ Initialize slides first; the project output folder is not set."
    PPT_DIR_FOLDER = PPT_DIR_FOLDER or CURRENT_PPT_DIR_FOLDER

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
        _attach_source_footer(data, i)
        SLIDE_STRUCTURED[i] = data
        SLIDE_TEMPLATES[i] = template.id
        slides.append((template, data))
        backgrounds.append(_slide_background(i))
        previews.append((i, template, data))

    if not slides:
        return None, "⚠️ Compilation stalled: Enter a title for at least one slide before compiling."

    # Name the final deck after the project folder itself, not the editable session label.
    # Example: generated_presentations/Market_Analysis -> Market_Analysis.pptx
    folder_name = os.path.basename(os.path.normpath(PPT_DIR_FOLDER))
    safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", folder_name).strip(" ._") or "Presentation"
    output_path = os.path.join(PPT_DIR_FOLDER, f"{safe_name}.pptx")
    build_deck_pptx(slides, output_path, backgrounds=backgrounds)

    # refresh the slide screenshots in the main folder so the user always sees the latest render
    from slide_layout_engine import render_to_png
    for i, template, data in previews:
        png_path = slide_preview_file(i)
        try:
            render_to_png(template, data, png_path, background=_slide_background(i), number=i + 1)
        except Exception:
            pass

    return output_path, (f"🚀 **Compilation successful!** Built {len(slides)} slides using the "
                         f"layout template library.\n\n📄 `{output_path}`")
