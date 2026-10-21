"""generate_code_flow_diagram.py - draws the code flow of the deck builder.

Renders `code_flow.png` - a stage by stage map of which function is called when, and
what it does.  Run it after changing the pipeline:

    python generate_code_flow_diagram.py
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------------------
# Palette (same visual language as the slides)
# --------------------------------------------------------------------------------------
BG = (11, 15, 25)
PANEL = (19, 27, 45)
PANEL_EDGE = (44, 56, 84)
INK = (248, 250, 252)
BODY = (203, 213, 225)
MUTED = (147, 161, 184)
ACCENT = (96, 165, 250)
ACCENT2 = (34, 211, 238)
GREEN = (52, 211, 153)
AMBER = (251, 191, 36)
RED = (248, 113, 113)
VIOLET = (167, 139, 250)

KIND_STYLE = {
    "ui":    (ACCENT, "UI trigger"),
    "llm":   (VIOLET, "LLM call"),
    "plan":  (ACCENT2, "Planning"),
    "render": (GREEN, "Rendering"),
    "io":    (AMBER, "File I/O"),
    "state": (RED, "State"),
    "user":  (MUTED, "User action"),
}

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONTS = {
    "h1": os.path.join(FONT_DIR, "segoeuib.ttf"),
    "h2": os.path.join(FONT_DIR, "segoeuib.ttf"),
    "b": os.path.join(FONT_DIR, "segoeuib.ttf"),
    "r": os.path.join(FONT_DIR, "segoeui.ttf"),
    "i": os.path.join(FONT_DIR, "segoeuii.ttf"),
}
SIZES = {"h1": 40, "h2": 22, "b": 15, "r": 13, "i": 12}

W = 2480
MARGIN = 56
NODE_W = 296
NODE_H = 104
GAP = 58
STAGE_PAD = 26


def font(name: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS[name], SIZES[name])


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> List[str]:
    out: List[str] = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            out.append("")
            continue
        cur = words[0]
        for word in words[1:]:
            trial = cur + " " + word
            if draw.textlength(trial, font=fnt) <= max_w:
                cur = trial
            else:
                out.append(cur)
                cur = word
        out.append(cur)
    return out


class Diagram:
    def __init__(self):
        self.img = Image.new("RGB", (W, 3000), BG)
        self.d = ImageDraw.Draw(self.img)
        self.y = MARGIN
        self._last: Optional[Tuple] = None      # last node of the previous row
        self._chain = True                      # draw the continuation connector

    def ensure(self, needed: int):
        """Grow the canvas if the content needs more room."""
        if needed <= self.img.height:
            return
        new_h = max(needed + 800, int(self.img.height * 1.5))
        bigger = Image.new("RGB", (W, new_h), BG)
        bigger.paste(self.img, (0, 0))
        self.img = bigger
        self.d = ImageDraw.Draw(self.img)

    # -- primitives -------------------------------------------------------------
    def text(self, x, y, s, name="r", fill=BODY, anchor="la"):
        self.d.text((x, y), s, font=font(name), fill=fill, anchor=anchor)
        return self.d.textlength(s, font=font(name))

    def node(self, x, y, title, detail, kind, module=""):
        color = KIND_STYLE[kind][0]
        r = 14
        self.d.rounded_rectangle([x, y, x + NODE_W, y + NODE_H], radius=r,
                                 fill=PANEL, outline=color, width=2)
        # kind stripe
        self.d.rounded_rectangle([x, y, x + 7, y + NODE_H], radius=3, fill=color)
        ty = y + 14
        if module:
            self.text(x + 20, ty, module, "i", color)
            ty += 18
        for line in wrap(self.d, title, font("b"), NODE_W - 38)[:2]:
            self.text(x + 20, ty, line, "b", INK)
            ty += 19
        ty += 2
        for line in wrap(self.d, detail, font("r"), NODE_W - 38)[:3]:
            self.text(x + 20, ty, line, "r", BODY)
            ty += 16
        return (x, y, x + NODE_W, y + NODE_H)

    def arrow(self, a, b, color=MUTED, label=None):
        """Straight / elbow arrow between two node boxes."""
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        if abs((ay0 + ay1) / 2 - (by0 + by1) / 2) < 6:
            y = (ay0 + ay1) / 2
            self.d.line([ax1 + 4, y, bx0 - 10, y], fill=color, width=3)
            self.d.polygon([(bx0 - 2, y), (bx0 - 14, y - 7), (bx0 - 14, y + 7)], fill=color)
        else:
            mid = max(ax1, bx1) + 22
            self.d.line([ax1 + 4, (ay0 + ay1) / 2, mid, (ay0 + ay1) / 2], fill=color, width=3)
            self.d.line([mid, (ay0 + ay1) / 2, mid, (by0 + by1) / 2], fill=color, width=3)
            self.d.line([mid, (by0 + by1) / 2, bx1 + 14, (by0 + by1) / 2], fill=color, width=3)
            self.d.polygon([(bx1 + 2, (by0 + by1) / 2), (bx1 + 16, (by0 + by1) / 2 - 7),
                            (bx1 + 16, (by0 + by1) / 2 + 7)], fill=color)
        if label:
            self.text((ax1 + bx0) / 2, (ay0 + ay1) / 2 - 20, label, "i", color, anchor="mm")

    def chain(self, prev, nxt, color=MUTED):
        """Continuation connector: down from the previous row into the next one."""
        px = (prev[0] + prev[2]) / 2
        nx = (nxt[0] + nxt[2]) / 2
        mid = (prev[3] + nxt[1]) / 2
        self.d.line([px, prev[3] + 4, px, mid], fill=color, width=3)
        self.d.line([px, mid, nx, mid], fill=color, width=3)
        self.d.line([nx, mid, nx, nxt[1] - 10], fill=color, width=3)
        self.d.polygon([(nx, nxt[1] - 1), (nx - 7, nxt[1] - 13), (nx + 7, nxt[1] - 13)], fill=color)

    def stage(self, number, title, subtitle):
        y0 = self.y
        self.ensure(y0 + 140)
        self.text(MARGIN, y0, f"STAGE {number}", "h2", ACCENT2)
        self.text(MARGIN + 132, y0, title, "h2", INK)
        self.text(MARGIN + 132, y0 + 30, subtitle, "r", MUTED)
        self.d.line([MARGIN, y0 + 58, W - MARGIN, y0 + 58], fill=PANEL_EDGE, width=2)
        self.y = y0 + 78
        self._last = None
        return y0

    def end_stage(self, y0):
        self.y += 26
        self.d.line([MARGIN, self.y, W - MARGIN, self.y], fill=(30, 38, 58), width=1)
        self.y += 34
        self._last = None

    def row(self, nodes: List[Tuple[str, str, str, str]], chain: bool = True):
        """nodes = [(title, detail, kind, module), ...] laid out left to right."""
        self.ensure(self.y + NODE_H + 80)
        boxes = []
        x = MARGIN
        for title, detail, kind, module in nodes:
            b = self.node(x, self.y, title, detail, kind, module)
            boxes.append(b)
            x += NODE_W + GAP
        for a, b in zip(boxes, boxes[1:]):
            self.arrow(a, b)
        if chain and self._last is not None:
            self.chain(self._last, boxes[0])
        self._last = boxes[-1]
        self.y += NODE_H + 40
        return boxes

    def solo(self, title, detail, kind, module):
        """A single node that continues into the next row."""
        self.ensure(self.y + NODE_H + 80)
        b = self.node(MARGIN, self.y, title, detail, kind, module)
        if self._last is not None:
            self.chain(self._last, b)
        self._last = b
        self.y += NODE_H + 40
        return b

    def branch(self, label):
        """Small label that starts a new (unconnected) row."""
        self._last = None
        self.ensure(self.y + 40)
        self.text(MARGIN, self.y, label, "i", MUTED)
        self.y += 24

    def save(self, path):
        self.ensure(self.y + MARGIN)
        out = self.img.crop((0, 0, W, self.y + MARGIN))
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        out.save(path, quality=95)
        return path


# --------------------------------------------------------------------------------------
# The diagram content
# --------------------------------------------------------------------------------------

def build() -> Diagram:
    g = Diagram()
    g.text(MARGIN, g.y, "AI Presentation Studio — code flow", "h1", INK)
    g.y += 56
    g.text(MARGIN, g.y, "Which function runs when, and what it does. "
                        "Every stage starts from a click in the Gradio UI and ends in files on disk.",
            "r", MUTED)
    g.y += 44

    # ---------------- stage 0 ----------------
    g.stage(0, "App start (module import)",
            "user_context.py is imported -> the whole UI is built and the template library is drawn")
    g.row([
        ("import user_context", "entry point of the Gradio app", "ui", "user_context.py"),
        ("import gemini_code_fixed", "constants, path helpers, UI updaters", "ui", "gemini_code_fixed.py"),
    ])
    g.solo("build_template_previews()",
           "renders all 64 templates to PNG once (cached on disk)", "render", "layout_templates.py")
    g.row([
        ("render_to_png()  x64", "one preview per template", "render", "layout_engine.py"),
        ("PilCanvas", "raster backend for the preview", "render", "layout_engine.py"),
        ("layout_templates/previews/*.png", "full size previews", "io", "on disk"),
        ("previews/thumbs/*.jpg", "small thumbnails for the galleries", "io", "on disk"),
    ])
    g.branch("...then the UI itself is built:")
    g.row([
        ("gr.Blocks(...)", "25 slide panels, each with its own gallery,\n"
                            "dropdown, image box and buttons", "ui", "user_context.py"),
    ], chain=False)
    g.end_stage(0)

    # ---------------- stage 1 ----------------
    g.stage(1, "Topic -> outline",
            "the user types a topic and presses Submit")
    g.row([
        ("submit_btn.click  /  message_input.submit", "UI trigger", "user", "user_context.py"),
        ("submit_lock()", "disables the buttons while it runs", "ui", "user_context.py"),
        ("response_streamer_outline()", "streams the reply into the chat box", "plan", "user_context.py"),
    ])
    g.row([
        ("first_prompt()", "builds the system + user message list", "plan", "imp_functions.py"),
        ("ollama.chat.completions.create()", "streaming call with the outline tool", "llm", "local Ollama"),
        ("slide_outline()", "the tool call that writes the outline", "plan", "imp_functions.py"),
        ("_parse_outline()", "outline text -> {number: title} dict", "state", "user_context.py"),
    ])
    g.row([
        ("convo_backup()", "saves the transcript to slide_outline_summary.txt", "io", "imp_functions.py"),
        ("summarize_conversation()", "one LLM call that keeps the objective", "llm", "imp_functions.py"),
        ("submit_unlock()", "re-enables the buttons", "ui", "user_context.py"),
    ])
    g.end_stage(1)

    # ---------------- stage 2 ----------------
    g.stage(2, "Initialize Slides  (the big one)",
            "one button -> slide text, ComfyUI backdrops and a layout recommendation per slide")
    g.row([
        ("generate_btn.click", "UI trigger", "user", "user_context.py"),
        ("initialize_lock()", "disables the buttons while it runs", "ui", "user_context.py"),
        ("slides_setup(model)", "orchestrates everything below", "plan", "user_context.py"),
    ])
    g.row([
        ("slides_from_conversation()", "one LLM call -> [{title, content}, ...]", "llm", "imp_functions.py"),
        ("clear_slide_previews()", "wipes the screenshots of the last deck", "state", "gemini_code_fixed.py"),
        ("SLIDE_STRUCTURED.clear()", "wipes the structured content of the last deck", "state", "gemini_code_fixed.py"),
    ])
    g.row([
        ("deck_design_brief()", "ONE palette + shape brief for the whole deck", "llm", "comfyui.py"),
        ("design_brief()", "asks the LLM for colours, shapes, mood", "llm", "comfyui.py"),
        ("_parse_brief()", "keeps only the valid fields", "state", "comfyui.py"),
    ])
    g.row([
        ("comfyui_session(model)", "context manager: starts ComfyUI, stops it after", "render", "comfyui.py"),
        ("comfyui_img_generator()", "one text-free 16:9 backdrop per slide", "render", "comfyui.py"),
        ("comfyui_prompts()", "turns the brief into an image prompt", "plan", "def_prompts.py"),
        ("generate()", "queue -> wait -> download", "render", "comfyui.py"),
    ])
    g.row([
        ("pptN/slide_M_0.png", "the ComfyUI backdrop of every slide", "io", "on disk"),
        ("recommend_layouts()", "one LLM call picks a layout per slide", "llm", "layout_templates.py"),
        ("layout_recommend_prompt()", "the catalogue + the deck, as a prompt", "plan", "def_prompts.py"),
        ("default_layout_for()", "heuristic fallback if the model fails", "plan", "layout_templates.py"),
    ])
    g.branch("...then every slide panel is filled in:")
    g.row([
        ("build_slide_updates()", "fills every slide panel: title, content,\nlayout dropdown, image box, feedback", "ui", "gemini_code_fixed.py"),
        ("initialize_unlock()", "re-enables the buttons", "ui", "user_context.py"),
    ], chain=False)
    g.end_stage(2)

    # ---------------- stage 3 ----------------
    g.stage(3, "Choosing the layout  (user action, no LLM)",
            "every slide has its OWN gallery - clicking a template only affects that slide")
    g.row([
        ("layout_gallery.select", "click a thumbnail in slide N's gallery", "user", "user_context.py"),
        ("on_thumbnail_select(evt)", "index -> layout label", "plan", "gemini_code_fixed.py"),
        ("slide_layout (dropdown)", "now shows the chosen template", "ui", "user_context.py"),
    ])
    g.row([
        ("slide_layout.change", "fires whenever the dropdown changes", "ui", "user_context.py"),
        ("make_layout_note_handler(i)", "binds the note to slide i", "ui", "user_context.py"),
        ("_layout_note(i, label)", "shows the LLM recommendation + what the\ntemplate is for", "ui", "user_context.py"),
    ])
    g.end_stage(3)

    # ---------------- stage 4 ----------------
    g.stage(4, "Generate a slide  (the core loop)",
            "one click -> the content is rewritten for the template, then drawn twice")
    g.row([
        ("generate_slide_btn.click", "UI trigger", "user", "user_context.py"),
        ("make_generate_slide_handler(i)", "binds the button to slide i", "ui", "user_context.py"),
        ("generate_slide()", "orchestrates the steps below", "plan", "gemini_code_fixed.py"),
        ("_resolve_template()", "label / id / name -> Template object", "plan", "gemini_code_fixed.py"),
    ])
    g.row([
        ("structure_for_layout()", "asks the LLM to reshape the content", "llm", "layout_templates.py"),
        ("layout_content_prompt()", "the template + its field list, as a prompt", "plan", "def_prompts.py"),
        ("_coerce_from_llm()", "validates the JSON against the field list", "state", "layout_templates.py"),
        ("_repair_item()", "fills fields the model named differently", "state", "layout_templates.py"),
    ])
    g.row([
        ("coerce_content()", "no-LLM fallback: fits the raw text to the template", "state", "layout_templates.py"),
        ("SLIDE_STRUCTURED[i] = data", "the finished content is remembered", "state", "gemini_code_fixed.py"),
        ("build_slide()", "renders the slide and writes both files", "render", "gemini_code_fixed.py"),
        ("render_slide()", "calls both backends with the same data", "render", "layout_templates.py"),
    ])
    g.row([
        ("render_to_pptx()", "editable native PowerPoint shapes", "render", "layout_engine.py"),
        ("PptxCanvas", "PowerPoint backend", "render", "layout_engine.py"),
        ("render_to_png()", "the screenshot of the same slide", "render", "layout_engine.py"),
        ("PilCanvas", "raster backend - same drawing code", "render", "layout_engine.py"),
    ])
    g.row([
        ("render_template()", "chrome (header, rule) + the kind renderer", "render", "layout_engine.py"),
        ("KIND_RENDERERS[kind]", "the drawing routine for this template", "render", "layout_engine.py"),
    ])
    g.branch("...and the two files land on disk:")
    g.row([
        ("pptN/slides/slide_M.pptx", "the single slide, editable in PowerPoint", "io", "on disk"),
        ("slide_previews/slide_M_preview.png", "the screenshot shown in the UI", "io", "on disk"),
    ], chain=False)
    g.end_stage(4)

    # ---------------- stage 4b ----------------
    g.stage("4b", "The two side buttons of a slide",
            "refine the wording, or redraw the backdrop and re-render the slide")
    g.row([
        ("render_btn.click", "Update slide content", "user", "user_context.py"),
        ("make_refresh_handler(i)", "binds the button to slide i", "ui", "user_context.py"),
        ("regenerate_single_slide()", "LLM rewrites title + bullets from the feedback", "llm", "user_context.py"),
    ])
    g.branch("the other button of the same slide:")
    g.row([
        ("image_btn.click", "Generate image for slide", "user", "user_context.py"),
        ("make_image_handler(i)", "binds the button to slide i", "ui", "user_context.py"),
        ("comfyui_img_generator()", "makes a new backdrop for that slide", "render", "comfyui.py"),
        ("build_slide()", "re-renders the slide on the new backdrop", "render", "gemini_code_fixed.py"),
    ], chain=False)
    g.end_stage("4b")

    # ---------------- stage 5 ----------------
    g.stage(5, "Compile the deck",
            "one button builds the whole .pptx from the state of every slide")
    g.row([
        ("generate_all_btn.click", "re-structures every slide, then compiles", "user", "user_context.py"),
        ("_generate_all_slides()", "loops over the slides and calls stage 4", "plan", "user_context.py"),
    ])
    g.row([
        ("compile_btn.click", "fast path: no LLM, uses what is already there", "user", "user_context.py"),
        ("compile_presentation_file()", "reads title/content/layout/feedback per slide", "plan", "gemini_code_fixed.py"),
        ("build_deck_pptx()", "one Presentation, one slide per entry", "render", "layout_engine.py"),
    ])
    g.branch("...and the deck is ready to download:")
    g.row([
        ("name_compiled.pptx", "the finished deck", "io", "generated_presentations/"),
        ("download_file_widget", "the download button in the UI", "ui", "user_context.py"),
    ], chain=False)
    g.end_stage(5)

    # ---------------- stage 6 ----------------
    g.stage(6, "Sessions",
            "save the state of the workspace, and come back to it later")
    g.row([
        ("save_state_btn.click", "UI trigger", "user", "user_context.py"),
        ("save_user_session()", "packs the 4 state fields of every slide", "state", "gemini_code_fixed.py"),
        ("<name>.json", "the saved session", "io", "presentation_sessions/"),
    ])
    g.row([
        ("load_state_btn.click", "UI trigger", "user", "user_context.py"),
        ("load_user_session()", "rebuilds every panel, normalises the layout", "state", "gemini_code_fixed.py"),
    ])
    g.end_stage(6)

    # ---------------- legend ----------------
    g.y += 10
    g.text(MARGIN, g.y, "Legend", "h2", INK)
    g.y += 40
    lx = MARGIN
    for kind, (color, label) in KIND_STYLE.items():
        g.d.rounded_rectangle([lx, g.y, lx + 22, g.y + 22], radius=5, fill=color)
        g.text(lx + 32, g.y + 3, label, "r", BODY)
        lx += 40 + g.d.textlength(label, font=font("r"))
    g.y += 60
    g.text(MARGIN, g.y, "Files:  user_context.py | gemini_code_fixed.py | layout_catalogue.py | "
                        "layout_engine.py | layout_templates.py | layout_templates/*.py | "
                        "imp_functions.py | def_prompts.py | comfyui.py", "i", MUTED)
    g.y += 40
    return g


if __name__ == "__main__":
    out = build().save("code_flow.png")
    print("Created", os.path.abspath(out))
