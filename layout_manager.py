"""layout_manager.py - the bridge between the LLM planner and the layout renderer.

Responsibilities
-----------------
1. Build the layout template preview images (PNG) that the user sees in the layout
   selector, rendered on top of the ComfyUI background that was generated for the deck.
2. Build the template specimen deck (.pptx) with one editable slide per template.
3. Ask the LLM which layout fits each slide (recommendation), while leaving the final
   choice with the user.
4. Ask the LLM to restructure the slide content so that it fits the chosen template.
5. Render the finished slide to .pptx (native, editable shapes) and to a PNG screenshot
   that is written back to the project folder.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from layout_catalog import (
    ADDED_LAYOUTS, LAYOUT_LABELS, ORIGINAL_LAYOUTS, TEMPLATES, Template,
    catalogue_for_llm, get_template, kind_spec, sample_content,
)
from slide_layout_engine import (
    DARK_THEME, LIGHT_THEME, build_deck_pptx, render_to_png, render_to_pptx,
)

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

TEMPLATE_ROOT = "layout_templates"
PREVIEW_DIR = os.path.join(TEMPLATE_ROOT, "previews")
THUMB_DIR = os.path.join(PREVIEW_DIR, "thumbs")
CATALOG_FILE = os.path.join(TEMPLATE_ROOT, "layout_template_catalogue.md")
TEMPLATE_DECK = os.path.join(TEMPLATE_ROOT, "presentation_layout_templates.pptx")
TEMPLATE_SAMPLE_PPTX = os.path.join(TEMPLATE_ROOT, "presentation_layout_templates.pptx")

os.makedirs(PREVIEW_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)


# --------------------------------------------------------------------------------------
# Backgrounds
# --------------------------------------------------------------------------------------

def find_background(extra: Optional[str] = None) -> Optional[str]:
    """Locate the ComfyUI background to render the templates on top of."""
    if extra and os.path.exists(extra):
        return extra
    patterns = [
        os.path.join("generated_presentations", "ppt*", "slide_1_0.png"),
        os.path.join("generated_presentations", "ppt*", "Archive", "slide_1_0.png"),
        os.path.join("archive", "slide_0.png"),
        "slide_trial_z_img_no_text_0.png",
    ]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if hits:
            return hits[0]
    return None


# --------------------------------------------------------------------------------------
# Template previews + specimen deck
# --------------------------------------------------------------------------------------

def preview_path_for(template: Template) -> str:
    """Where the full size preview PNG of a template lives."""
    safe = template.name.replace(" ", "_").replace("/", "-")
    return os.path.join(PREVIEW_DIR, f"{template.id}_{safe}_v2.png")


def thumb_path_for(template: Template) -> str:
    """Where the small gallery thumbnail of a template lives.

    The gallery sits on every slide, so the thumbnails are kept small - the browser
    only has to fetch each template once and can then reuse it for every slide.
    """
    safe = template.name.replace(" ", "_").replace("/", "-")
    return os.path.join(THUMB_DIR, f"{template.id}_{safe}_v2.jpg")


def _make_thumb(source: str, dest: str, width: int = 420) -> Optional[str]:
    try:
        from PIL import Image
        with Image.open(source) as im:
            im = im.convert("RGB")
            ratio = width / im.width
            im = im.resize((width, max(1, int(im.height * ratio))), Image.LANCZOS)
            im.save(dest, quality=82)
        return dest
    except Exception:
        return None


def build_template_previews(background: Optional[str] = None, force: bool = False,
                             dpi: int = 110) -> List[Tuple[str, str]]:
    """Render one preview PNG per template. Returns [(thumbnail_path, caption), ...]."""
    bg = find_background(background)
    items: List[Tuple[str, str]] = []
    for tpl in TEMPLATES:
        path = preview_path_for(tpl)
        thumb = thumb_path_for(tpl)
        if force or not os.path.exists(path):
            render_to_png(tpl, sample_content(tpl.kind), path, background=bg, number=None, dpi=dpi)
        if force or not os.path.exists(thumb):
            _make_thumb(path, thumb)
        items.append((thumb if os.path.exists(thumb) else path, tpl.label))
    return items


def build_template_deck(background: Optional[str] = None, out_path: str = TEMPLATE_DECK) -> str:
    """Build the .pptx specimen deck: one editable slide per template, on the background."""
    bg = find_background(background)
    slides = [(tpl, sample_content(tpl.kind)) for tpl in TEMPLATES]
    backgrounds = [bg] * len(slides)
    return build_deck_pptx(slides, out_path, backgrounds=backgrounds)


def write_catalogue_markdown(out_path: str = CATALOG_FILE) -> str:
    from layout_catalog import catalogue_markdown
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(catalogue_markdown())
    return out_path


def gallery_items(background: Optional[str] = None, force: bool = False) -> List[Tuple[str, str]]:
    """The gallery payload used by the layout selector in the UI."""
    return build_template_previews(background=background, force=force)


# --------------------------------------------------------------------------------------
# Content helpers
# --------------------------------------------------------------------------------------

def clean_lines(content: str) -> List[str]:
    lines = []
    for raw in (content or "").splitlines():
        line = raw.strip().lstrip("•-*–— ").strip()
        if line:
            lines.append(line)
    return lines


def _split_heading_body(line: str) -> Tuple[str, str]:
    words = line.split()
    if len(words) <= 5:
        return line, ""
    head = " ".join(words[:3])
    body = " ".join(words[3:])
    return head, body


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return clean_lines(value)
    return [value]


def _notes_from_content(content: str) -> str:
    """Speaker notes: the full source text, which the slide itself has to shorten to fit."""
    lines = [ln.strip().lstrip("\u2022-*\u2013 ").strip() for ln in str(content or "").splitlines()]
    return "\n".join(ln for ln in lines if ln)[:3000]


def coerce_content(template: Template, title: str, content: str) -> Dict[str, Any]:
    """Fit raw text into the template shape (no LLM) and keep the full text as speaker notes."""
    data = _coerce_content_core(template, title, content)
    notes = _notes_from_content(content)
    if notes:
        data["notes"] = notes
    return data


def _coerce_content_core(template: Template, title: str, content: str) -> Dict[str, Any]:
    """Fallback structuring: fit the raw text into the template shape without an LLM.

    Used when the model call fails, or when a slide was never run through the generator.
    """
    kind = template.kind
    spec = kind_spec(kind)
    lines = clean_lines(content)
    data: Dict[str, Any] = {}
    sample = spec["sample"]
    item_key = spec.get("item_key")

    # scalars straight from the sample, overridden by the real title where it makes sense
    for key in spec["required"]:
        if key == item_key:
            continue
        if key == "title":
            data["title"] = title or sample.get("title", template.name)
        elif key in sample and not isinstance(sample[key], (list, dict)):
            data[key] = sample[key]
        elif key in sample:
            data[key] = copy.deepcopy(sample[key])
        else:
            data[key] = ""
    if "title" in spec["fields"] and "title" not in data:
        data["title"] = title or template.name
    for key in spec["fields"]:
        data.setdefault(key, copy.deepcopy(sample.get(key, "")))

    if not item_key:
        return data

    min_i = spec.get("min_items") or 1
    max_i = spec.get("max_items") or max(min_i, len(lines))
    items = [ln for ln in lines[:max_i] if isinstance(ln, str)]

    proto = sample[item_key][0] if sample.get(item_key) else {}
    if isinstance(proto, str):
        data[item_key] = list(items)
        while len(data[item_key]) < min_i and sample.get(item_key):
            data[item_key].append(copy.deepcopy(sample[item_key][len(data[item_key]) % len(sample[item_key])]))
        return data

    built = []
    for i, line in enumerate(items):
        if isinstance(proto, dict):
            entry = {}
            for key, default in proto.items():
                if key == "number":
                    entry[key] = str(i + 1).zfill(2)
                elif key == "heading":
                    entry[key] = _split_heading_body(line)[0]
                elif key == "body":
                    entry[key] = _split_heading_body(line)[1] or line
                elif key == "label":
                    entry[key] = _split_heading_body(line)[0]
                elif key == "value":
                    entry[key] = _split_heading_body(line)[0]
                elif key in ("bullets", "features", "actions", "items", "traits", "text"):
                    entry[key] = [line]
                elif key == "action":
                    entry[key] = line
                elif key == "detail":
                    entry[key] = _split_heading_body(line)[1] or line
                else:
                    entry[key] = default
            built.append(entry)
        else:
            built.append(line)

    # top up with sample entries so the template never renders an empty slot
    while len(built) < min_i and sample.get(item_key):
        built.append(copy.deepcopy(sample[item_key][len(built) % len(sample[item_key])]))
    data[item_key] = built
    return data


def _repair_item(entry: Dict[str, Any], proto: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    """Make a model supplied item match the shape the template expects.

    Models frequently return the right information with slightly different key names
    (or a single string where a heading/body pair is expected).  Rather than rendering an
    empty slot, the missing fields are filled from whatever the model did return.
    """
    out = dict(entry)
    strings = [v.strip() for k, v in entry.items() if isinstance(v, str) and v.strip()]
    numbers = [v for k, v in entry.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]

    for key, default in proto.items():
        if key in out and out[key] not in ("", None, [], {}):
            continue
        if key == "number":
            out[key] = str(index + 1).zfill(2)
        elif key in ("value", "price", "total"):
            out[key] = str(default) if not strings else (str(numbers[0]) if numbers else strings[0])
        elif key in ("heading", "label", "name", "period", "role", "code", "category", "action"):
            out[key] = strings[0] if strings else str(default)
        elif key == "body":
            out[key] = (strings[1] if len(strings) > 1 else (strings[0] if strings else str(default)))
        elif key in ("bullets", "features", "actions", "traits", "text", "items", "values"):
            out[key] = [strings[0]] if strings else list(default) if isinstance(default, list) else []
        elif key in ("note", "caption", "detail", "sub"):
            out[key] = strings[-1] if strings else str(default)
        else:
            out[key] = default
    return out


# Short fields (headings, labels, figures) get a tight cap so one over-long reply cannot burst
# out of its card; running text keeps the generous default.
_SHORT_FIELDS = {"heading", "label", "kicker", "eyebrow", "owner", "due", "status", "number", "value",
                 "name", "role", "period", "x_label", "y_label", "unit", "overlap", "stage", "tag"}


def _field_limit(key: str) -> int:
    if key in _SHORT_FIELDS:
        return 48
    if key == "title":
        return 80
    if key in ("headline", "statement", "insight", "recommendation", "action"):
        return 160
    return 220


def _coerce_from_llm(template: Template, raw: Dict[str, Any], title: str, content: str) -> Dict[str, Any]:
    """Validate / repair the model's JSON against the template's field list."""
    spec = kind_spec(template.kind)
    fallback = coerce_content(template, title, content)
    data = copy.deepcopy(fallback)

    def clean_str(value: Any, limit: int = 220) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return (cut if len(cut) >= limit // 2 else text[:limit - 1]) + "\u2026"

    for key in spec["fields"]:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(spec["fields"][key], str) and "array" in spec["fields"][key]:
            if not isinstance(value, list):
                value = _as_list(value)
            item_key = spec.get("item_key")
            proto = fallback.get(item_key, [])
            proto = proto[0] if proto and isinstance(proto[0], dict) else {}
            items = []
            for i, entry in enumerate(value):
                if isinstance(entry, dict):
                    if proto:
                        entry = _repair_item(entry, proto, i)
                    out = {}
                    for k, v in entry.items():
                        if isinstance(v, list):
                            out[k] = [clean_str(x) for x in v][:6]
                        elif isinstance(v, (int, float)):
                            out[k] = v
                        else:
                            out[k] = clean_str(v, _field_limit(k))
                    items.append(out)
                else:
                    items.append(clean_str(entry))
            lo = spec.get("min_items") or 1
            hi = spec.get("max_items") or max(lo, len(items))
            if len(items) > hi:
                items = items[:hi]
            while len(items) < lo and proto:
                items.append(copy.deepcopy(proto))
            data[key] = items
        elif isinstance(value, list):
            if value:
                data[key] = [clean_str(v) for v in value][:12]
        elif isinstance(value, dict):
            if value:
                data[key] = {k: (clean_str(v) if not isinstance(v, (int, float)) else v)
                             for k, v in value.items()}
        elif isinstance(value, (int, float)):
            data[key] = value
        else:
            text = clean_str(value, _field_limit(key))
            # an empty reply never overwrites a usable fallback
            if text:
                data[key] = text

    # the title always wins over whatever the model produced
    if "title" in spec["fields"] and title:
        data["title"] = title
    return data


def flatten_content(data: Dict[str, Any]) -> str:
    """Turn the structured content back into readable bullet lines for the text box."""
    out: List[str] = []
    for key, value in data.items():
        if key in ("title", "source_footer", "sources", "source_urls", "notes"):
            continue
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
        elif isinstance(value, dict):
            for v in value.values():
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    out.append(entry.strip())
                elif isinstance(entry, dict):
                    bits = [str(v) for v in entry.values() if isinstance(v, str) and v.strip()]
                    out.append(" — ".join(bits))
    return "\n".join(f"• {line}" for line in out if line)


# --------------------------------------------------------------------------------------
# LLM: layout recommendation
# --------------------------------------------------------------------------------------

def _catalogue_text() -> str:
    lines = []
    for entry in catalogue_for_llm():
        lines.append(
            f"{entry['id']} | {entry['name']} | {entry['family']} | "
            f"use for: {entry['best_for']} | content: {entry['content_pattern']}"
        )
    return "\n".join(lines)


def recommend_layouts(ollama, model: str, deck_outline: str, slides: Sequence[Dict[str, Any]],
                      ) -> List[Dict[str, Any]]:
    """Ask the LLM which layout fits each slide; retry bad responses then use heuristics."""
    from prompts import layout_recommend_prompt
    from llm_helpers import extract_json, robust_chat_completion

    payload = [
        {"number": i + 1, "title": s.get("title", ""), "content": s.get("content", "")}
        for i, s in enumerate(slides)
    ]
    system_prompt, user_prompt = layout_recommend_prompt(_catalogue_text(), deck_outline, payload)
    last_error = None
    for attempt in range(2):
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt if attempt == 0 else (
                        user_prompt + "\n\nReturn ONLY valid JSON with a top-level 'slides' array. "
                        "Include one entry for every supplied slide, in order. No markdown or commentary.") }]
        try:
            response = robust_chat_completion(
                ollama, model, messages, response_format={"type": "json_object"},
                temperature=0, max_tokens=4096,
            )
            data = extract_json(response.choices[0].message.content)
            raw = data.get("slides", data) if isinstance(data, dict) else data
            picks = []
            if isinstance(raw, dict):
                raw = [raw]
            for i, entry in enumerate(raw if isinstance(raw, list) else []):
                if i >= len(payload) or not isinstance(entry, dict):
                    continue
                lid = str(entry.get("layout_id", "")).strip().upper()
                if get_template(lid) is None:
                    lid = ""
                picks.append({
                    "number": i + 1,
                    "layout_id": lid or default_layout_for(payload[i].get("title", ""), payload[i].get("content", "")),
                    "reason": str(entry.get("reason", ""))[:160],
                })
            if len(picks) == len(payload):
                return picks
            last_error = ValueError(f"Expected {len(payload)} layout choices, received {len(picks)}")
        except Exception as exc:
            last_error = exc
        print(f"[layouts] layout recommendation attempt {attempt + 1}/2 failed: {last_error}")

    print(f"[layouts] layout recommendation failed, using heuristics: {last_error}")
    return [{"number": i + 1,
             "layout_id": default_layout_for(s.get("title", ""), s.get("content", "")),
             "reason": "Heuristic match on the slide title"}
            for i, s in enumerate(payload)]


def default_layout_for(title: str, content: str) -> str:
    """Heuristic layout choice, used when the model is unavailable."""
    text = f"{title} {content}".lower()
    t = (title or "").lower()

    def has(*words):
        return any(w in text for w in words)

    if has("agenda", "contents", "roadmap of the talk", "what we will cover"):
        return "L15"
    if has("executive summary", "exec summary", "at a glance", "tl;dr", "in one slide"):
        return "L65"
    if has("action plan", "next steps", "action items", "owners and dates", "who does what"):
        return "L68"
    if has("thank", "questions", "contact"):
        return "L14"
    if has("venn", "overlap", "intersection", "sweet spot"):
        return "L66"
    if has("agenda item") or t in ("introduction", "overview", "welcome"):
        return "L01"
    if has("timeline", "milestone", "roadmap", "history of", "phases"):
        return "L06"
    if has("compare", "versus", " vs ", "pros and cons", "before and after", "trade-off"):
        return "L08"
    if has("swot", "strengths", "weaknesses", "opportunities", "threats"):
        return "L30"
    if has("quote", "testimonial", "customer said", "said"):
        return "L09"
    if has("trend", "over time", "year over year", "yoy", "growth rate", "forecast"):
        return "L67"
    if has("kpi", "metric", "scorecard", "how many", "number of users"):
        return "L31"
    if has("process", "workflow", "steps", "how to", "pipeline"):
        return "L10"
    if has("architecture", "technical", "components", "integration"):
        return "L29"
    if has("table", "breakdown by", "detail per"):
        return "L07"
    if has("three", "pillars", "3 ", "features", "benefits"):
        return "L03"
    if has("takeaway", "key points", "summary", "in summary"):
        return "L62"
    if has("section", "part "):
        return "L45"
    return "L02"


# --------------------------------------------------------------------------------------
# LLM: content structuring for a template
# --------------------------------------------------------------------------------------

def structure_for_layout(ollama, model: str, template: Template, title: str, content: str,
                         deck_outline: str = "") -> Dict[str, Any]:
    """Restructure content for a template with retries; deterministic coercion is the final fallback."""
    from prompts import layout_content_prompt
    from llm_helpers import extract_json, robust_chat_completion

    spec = kind_spec(template.kind)
    record = (f"{template.id} {template.name} ({template.family}) - {template.best_for} "
              f"Content pattern: {template.content_pattern}. "
              f"Implementation: {template.implementation}")
    system_prompt, user_prompt = layout_content_prompt(record, spec, title, content, deck_outline)
    last_error = None
    for attempt in range(2):
        repair_instruction = ("\n\nIMPORTANT: Return exactly one complete JSON object, no markdown fences or commentary. "
                              "Ensure all strings are double-quoted and every bracket is closed. Preserve all key facts.")
        messages = [
            {"role": "system", "content": system_prompt + repair_instruction},
            {"role": "user", "content": user_prompt if attempt == 0 else (
                user_prompt + "\n\nYour previous response could not be parsed as complete JSON. Regenerate the full object from scratch.")},
        ]
        try:
            response = robust_chat_completion(
                ollama, model, messages, response_format={"type": "json_object"},
                temperature=0, max_tokens=4096,
            )
            data = extract_json(response.choices[0].message.content)
            if isinstance(data, dict) and isinstance(data.get(template.kind), dict):
                data = data[template.kind]
            if not isinstance(data, dict):
                raise ValueError("model did not return a JSON object")
            return _coerce_from_llm(template, data, title, content)
        except Exception as exc:
            last_error = exc
            print(f"[layouts] content structuring attempt {attempt + 1}/2 failed for {template.id}: {exc}")

    print(f"[layouts] content structuring failed for {template.id}; using deterministic fallback: {last_error}")
    return coerce_content(template, title, content)


# --------------------------------------------------------------------------------------
# Rendering a finished slide
# --------------------------------------------------------------------------------------


def render_slide(template: Template, data: Dict[str, Any], pptx_path: str, png_path: str,
                 background: Optional[str] = None, number: Optional[int] = None,
                 dpi: int = 110) -> Tuple[str, str]:
    """Write the slide as an editable .pptx and as a PNG screenshot."""
    render_to_pptx(template, data, pptx_path, background=background, number=number)
    render_to_png(template, data, png_path, background=background, number=number, dpi=dpi)
    return pptx_path, png_path
