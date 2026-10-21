"""slide_layout_engine.py - draws layout templates to PowerPoint AND to PNG.

Every layout is drawn through a small canvas abstraction so that the editable
PowerPoint slide and the PNG preview are produced from *one* set of drawing
instructions (no duplicated geometry, no drift between what the user sees and
what ends up in the .pptx).

Two backends:
    PptxCanvas  -> native, editable PowerPoint shapes and text
    PilCanvas   -> a raster preview (used for the template gallery and for the
                   "how does this slide look right now" screenshot)

All coordinates are in inches on a 13.333 x 7.5 in (16:9) canvas.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from layout_catalog import Template, get_template, kind_spec

# --------------------------------------------------------------------------------------
# Canvas geometry
# --------------------------------------------------------------------------------------

SLIDE_W = 13.333
SLIDE_H = 7.5
LEFT = 0.82
RIGHT = 12.51
CONTENT_TOP = 1.92
CONTENT_BOTTOM = 6.72
CONTENT_W = RIGHT - LEFT
CONTENT_H = CONTENT_BOTTOM - CONTENT_TOP

EMU_PER_IN = 914400

# Smallest text size ever drawn. Projected slides are unreadable below ~10 pt, so every
# text call is clamped to this floor (labels, footers and source lines included).
MIN_FONT_PT = 10.0


def hx(value: str) -> RGBColor:
    value = value.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def rgb_tuple(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def num(value: Any, default: float = 0.0) -> float:
    """Best effort numeric read of a value that may carry a currency symbol or unit."""
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUM_RE.search(str(value or ""))
    return float(match.group()) if match else default


# --------------------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------------------

@dataclass
class Theme:
    name: str = "dark"
    bg: str = "#0B0F19"
    scrim: float = 0.55
    surface: str = "#141D33"
    surface_alt: str = "#1B2740"
    border: str = "#2C3854"
    text: str = "#F8FAFC"
    body: str = "#CBD5E1"
    muted: str = "#93A1B8"
    accent: str = "#60A5FA"
    accent_solid: str = "#2563EB"
    accent2: str = "#22D3EE"
    green: str = "#34D399"
    amber: str = "#FBBF24"
    red: str = "#F87171"
    bar: str = "#3B82F6"
    pale_blue: str = "#15233F"
    pale_cyan: str = "#0F2A38"
    pale_green: str = "#102B26"
    pale_amber: str = "#2B2312"
    pale_red: str = "#2E181B"
    font: str = "Segoe UI"
    dark: bool = True

    def accent_cycle(self, n: int) -> List[str]:
        cycle = [self.accent, self.accent2, self.green, self.amber, self.red]
        return [cycle[i % len(cycle)] for i in range(max(1, n))]


DARK_THEME = Theme()
LIGHT_THEME = Theme(
    name="light", bg="#F8FAFC", scrim=0.0, surface="#FFFFFF", surface_alt="#EEF2F7",
    border="#E2E8F0", text="#111827", body="#374151", muted="#6B7280",
    accent="#2563EB", accent_solid="#1D4ED8", accent2="#0891B2", green="#059669",
    amber="#D97706", red="#DC2626", bar="#3B82F6",
    pale_blue="#EAF1FF", pale_cyan="#E6FAFD", pale_green="#E7F8F0",
    pale_amber="#FFF5DF", pale_red="#FEECEC", dark=False,
)


# --------------------------------------------------------------------------------------
# Background softening
# --------------------------------------------------------------------------------------
# The ComfyUI artwork is beautiful but far too busy behind body copy.  The image is
# therefore blurred and darkened once, cached on disk, and used by BOTH backends so
# the PNG preview and the .pptx slide show exactly the same backdrop.

_BG_CACHE: Dict[str, str] = {}


def softened_background(path: Optional[str], blur: int = 14, darken: float = 0.34) -> Optional[str]:
    """Return a cached, softened copy of a background image (or the original)."""
    if not path or not os.path.exists(path):
        return None
    key = os.path.abspath(path)
    if key in _BG_CACHE and os.path.exists(_BG_CACHE[key]):
        return _BG_CACHE[key]
    out = path
    try:
        import tempfile
        from PIL import Image, ImageEnhance, ImageFilter
        with Image.open(path) as im:
            im = im.convert("RGB")
            radius = max(3, int(im.width * blur / 1600.0))
            im = im.filter(ImageFilter.GaussianBlur(radius))
            im = ImageEnhance.Brightness(im).enhance(max(0.25, 1.0 - darken))
            cache_dir = os.path.join(tempfile.gettempdir(), "deckmaker_bg")
            os.makedirs(cache_dir, exist_ok=True)
            stem = os.path.splitext(os.path.basename(path))[0]
            out = os.path.join(cache_dir, f"{stem}_soft.jpg")
            im.save(out, quality=92)
    except Exception:
        out = path
    _BG_CACHE[key] = out
    return out


_LUM_CACHE: Dict[str, float] = {}


def background_luminance(path: Optional[str]) -> float:
    """Mean brightness (0 dark .. 1 bright) of a background image; 0.3 when unknown."""
    if not path or not os.path.exists(path):
        return 0.3
    key = os.path.abspath(path)
    if key not in _LUM_CACHE:
        try:
            with Image.open(path) as im:
                small = im.convert("L").resize((48, 27))
                px = list(small.getdata())
                _LUM_CACHE[key] = sum(px) / (len(px) * 255.0)
        except Exception:
            _LUM_CACHE[key] = 0.3
    return _LUM_CACHE[key]


def background_scrim(theme: "Theme", path: Optional[str], dense: bool) -> float:
    """Scrim opacity that keeps text readable on THIS artwork.

    The theme's own scrim is the floor; bright artwork gets more, and text-dense slides get a
    little more than title/section slides (which carry only a few large words).
    """
    lum = background_luminance(path)
    extra = max(0.0, lum - 0.35) * 0.9 + (0.05 if dense and lum > 0.25 else 0.0)
    return min(0.88, theme.scrim + extra)


# --------------------------------------------------------------------------------------
# Canvas backends
# --------------------------------------------------------------------------------------

class Canvas:
    """Common drawing API. Coordinates are inches."""

    def rect(self, x, y, w, h, fill=None, line=None, radius=0.0, alpha=1.0, line_w=1.0):
        raise NotImplementedError

    def ellipse(self, x, y, w, h, fill=None, line=None, alpha=1.0, line_w=1.0):
        raise NotImplementedError

    def polygon(self, points, fill=None, line=None, alpha=1.0, line_w=1.0):
        raise NotImplementedError

    def line(self, x1, y1, x2, y2, color, width=1.0, alpha=1.0):
        raise NotImplementedError

    def text(self, x, y, w, h, text, size=14, color="#FFFFFF", bold=False, italic=False,
             align="l", valign="t", alpha=1.0, line_gap=1.22, space_after=0.0, font=None):
        raise NotImplementedError

    def image(self, path, x, y, w, h, mode="cover", alt=""):
        raise NotImplementedError

    # -- structure hooks (no-ops on backends that have no document structure) ------
    def title(self, *args, **kwargs):
        """The slide's title. PowerPoint gets a real title placeholder (outline view,
        slide navigator, screen readers); other backends just draw text."""
        return self.text(*args, **kwargs)

    def notes(self, text):
        return None

    def finish_background(self):
        return None

    def finalize(self):
        return None

    # -- convenience -------------------------------------------------------------
    def label(self, x, y, w, text, size=9, color=None, bold=True, align="l", theme=None):
        th = theme or DARK_THEME
        return self.text(x, y, w, size / 72.0 * 1.5, str(text).upper(), size,
                         color or th.accent, bold=bold, align=align)

    def bullets(self, x, y, w, items, size=13, color=None, theme=None, gap=0.0,
                dot_color=None, line_h=None):
        th = theme or DARK_THEME
        color = color or th.body
        dot_color = dot_color or th.accent
        cy = y
        for item in items:
            self.ellipse(x, cy + 0.11, 0.09, 0.09, fill=dot_color)
            h = self.text(x + 0.22, cy, w - 0.22, 0.4, str(item), size, color, line_gap=1.25)
            cy += (h if h else 0.28) + gap
        return cy - y


class PptxCanvas(Canvas):
    """Draws native, editable PowerPoint shapes."""

    def __init__(self, prs: Presentation, slide):
        self.prs = prs
        self.slide = slide

    # -- helpers -----------------------------------------------------------------
    @staticmethod
    def _alpha(color_elm, alpha: float):
        if alpha >= 0.999:
            return
        # callers hand over the <a:srgbClr> element itself (an earlier version searched for a
        # child of it, found nothing, and silently dropped ALL transparency in the .pptx)
        if color_elm is None:
            return
        srgb = color_elm if color_elm.tag == qn("a:srgbClr") else color_elm.find(qn("a:srgbClr"))
        if srgb is None:
            return
        for old in srgb.findall(qn("a:alpha")):
            srgb.remove(old)
        el = srgb.makeelement(qn("a:alpha"), {"val": str(int(max(0.0, min(1.0, alpha)) * 100000))})
        srgb.append(el)

    def _style_shape(self, shape, fill, line, alpha, line_w):
        if fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = hx(fill)
            self._alpha(shape.fill.fore_color._xFill.find(qn("a:srgbClr")), alpha)
        else:
            shape.fill.background()
        if line:
            shape.line.color.rgb = hx(line)
            shape.line.width = Pt(line_w)
            self._alpha(shape.line.color._xFill.find(qn("a:srgbClr")), alpha)
        else:
            shape.line.fill.background()
        shape.shadow.inherit = False
        return shape

    # -- primitives --------------------------------------------------------------
    def rect(self, x, y, w, h, fill=None, line=None, radius=0.0, alpha=1.0, line_w=1.0):
        if w <= 0 or h <= 0:
            return None
        st = MSO_SHAPE.ROUNDED_RECTANGLE if radius > 0 else MSO_SHAPE.RECTANGLE
        shape = self.slide.shapes.add_shape(st, Inches(x), Inches(y), Inches(w), Inches(h))
        if radius > 0 and st == MSO_SHAPE.ROUNDED_RECTANGLE:
            try:
                shape.adjustments[0] = min(0.5, max(0.0, radius / max(0.01, min(w, h))))
            except Exception:
                pass
        return self._style_shape(shape, fill, line, alpha, line_w)

    def ellipse(self, x, y, w, h, fill=None, line=None, alpha=1.0, line_w=1.0):
        if w <= 0 or h <= 0:
            return None
        shape = self.slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(w), Inches(h))
        return self._style_shape(shape, fill, line, alpha, line_w)

    def polygon(self, points, fill=None, line=None, alpha=1.0, line_w=1.0):
        pts = [(float(px), float(py)) for px, py in points]
        if len(pts) < 3:
            return None
        x0, y0 = pts[0]
        builder = self.slide.shapes.build_freeform(Emu(int(x0 * EMU_PER_IN)), Emu(int(y0 * EMU_PER_IN)),
                                                  scale=EMU_PER_IN)
        builder.add_line_segments([(Emu(int(px * EMU_PER_IN)), Emu(int(py * EMU_PER_IN)))
                                    for px, py in pts[1:]], close=True)
        shape = builder.convert_to_shape()
        return self._style_shape(shape, fill, line, alpha, line_w)

    def line(self, x1, y1, x2, y2, color, width=1.0, alpha=1.0):
        conn = self.slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                               Inches(x2), Inches(y2))
        conn.line.color.rgb = hx(color)
        conn.line.width = Pt(width)
        self._alpha(conn.line.color._xFill.find(qn("a:srgbClr")), alpha)
        return conn

    def _write_text(self, tf, text, size, color, bold, italic, align, valign, line_gap, space_after, font):
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE,
                              "b": MSO_ANCHOR.BOTTOM}.get(valign, MSO_ANCHOR.TOP)
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER,
                           "r": PP_ALIGN.RIGHT, "j": PP_ALIGN.JUSTIFY}.get(align, PP_ALIGN.LEFT)
            p.line_spacing = Pt(size * line_gap)
            if space_after:
                p.space_after = Pt(space_after)
            run = p.add_run()
            run.text = ln
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.italic = italic
            run.font.color.rgb = hx(color)
            run.font.name = font or "Segoe UI"
        return len(lines) * size * line_gap / 72.0

    def text(self, x, y, w, h, text, size=14, color="#FFFFFF", bold=False, italic=False,
             align="l", valign="t", alpha=1.0, line_gap=1.22, space_after=0.0, font=None):
        text = "" if text is None else str(text)
        if not text.strip():
            return 0.0
        size = max(size, MIN_FONT_PT)
        box = self.slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        return self._write_text(box.text_frame, text, size, color, bold, italic, align, valign,
                                line_gap, space_after, font)

    def title(self, x, y, w, h, text, size=14, color="#FFFFFF", bold=False, italic=False,
              align="l", valign="t", alpha=1.0, line_gap=1.22, space_after=0.0, font=None):
        """Write the slide title into the real title placeholder (falls back to a text box)."""
        text = "" if text is None else str(text)
        ph = self.slide.shapes.title
        if ph is None or getattr(self, "_title_used", False) or not text.strip():
            return self.text(x, y, w, h, text, size, color, bold, italic, align, valign, alpha,
                             line_gap, space_after, font)
        self._title_used = True
        size = max(size, MIN_FONT_PT)
        ph.left, ph.top, ph.width, ph.height = Inches(x), Inches(y), Inches(w), Inches(h)
        ph.name = "Title"
        return self._write_text(ph.text_frame, text, size, color, bold, italic, align, valign,
                                line_gap, space_after, font)

    def notes(self, text):
        text = (text or "").strip()
        if text:
            try:
                self.slide.notes_slide.notes_text_frame.text = text
            except Exception:
                pass

    def finish_background(self):
        """Background art was just drawn on top of the (bottom-most) title placeholder: move the
        placeholder above it so it is visible, yet still first in reading order."""
        ph = self.slide.shapes.title
        if ph is not None:
            el = ph._element
            tree = el.getparent()
            tree.remove(el)
            tree.append(el)

    def finalize(self):
        """Drop the title placeholder when no title was written, so no empty prompt remains."""
        ph = self.slide.shapes.title
        if ph is not None and not getattr(self, "_title_used", False):
            ph._element.getparent().remove(ph._element)

    def image(self, path, x, y, w, h, mode="cover", alt=""):
        if not path or not os.path.exists(path):
            return None
        pic = self.slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
        try:   # alt text for screen readers (backdrops are described as decorative)
            pic._element.nvPicPr.cNvPr.set("descr", alt or "Slide image")
            pic._element.nvPicPr.cNvPr.set("name", "Background artwork" if alt else "Picture")
        except Exception:
            pass
        if mode == "cover":
            try:
                from PIL import Image as _I
                with _I.open(path) as im:
                    iw, ih = im.size
                target = w / h
                src = iw / ih
                if src > target:      # source wider -> crop left/right
                    keep = ih * target
                    frac = (iw - keep) / iw / 2
                    pic.crop_left = frac
                    pic.crop_right = frac
                elif src < target:    # source taller -> crop top/bottom
                    keep = iw / target
                    frac = (ih - keep) / ih / 2
                    pic.crop_top = frac
                    pic.crop_bottom = frac
            except Exception:
                pass
        return pic


class PilCanvas(Canvas):
    """Raster preview of the very same drawing instructions."""

    FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    FONT_FILES = {
        (False, False): "segoeui.ttf",
        (True, False): "segoeuib.ttf",
        (False, True): "segoeuii.ttf",
        (True, True): "segoeuiz.ttf",
    }
    FALLBACK = {
        (False, False): "arial.ttf", (True, False): "arialbd.ttf",
        (False, True): "ariali.ttf", (True, True): "arialbi.ttf",
    }

    def __init__(self, width=SLIDE_W, height=SLIDE_H, dpi=110, theme=None):
        self.dpi = dpi
        self.theme = theme or DARK_THEME
        self.px_w = int(round(width * dpi))
        self.px_h = int(round(height * dpi))
        self.img = Image.new("RGBA", (self.px_w, self.px_h), rgb_tuple(self.theme.bg) + (255,))
        self.draw = ImageDraw.Draw(self.img)
        self._fonts: Dict[Tuple[int, bool, bool], ImageFont.FreeTypeFont] = {}

    # -- helpers -----------------------------------------------------------------
    def _s(self, v):
        return v * self.dpi

    def _font(self, size, bold=False, italic=False):
        key = (int(round(size * 4)), bold, italic)
        f = self._fonts.get(key)
        if f is None:
            px = max(6, int(round(size * self.dpi / 72.0)))
            for name in (self.FONT_FILES[(bold, italic)], self.FALLBACK[(bold, italic)]):
                path = os.path.join(self.FONT_DIR, name)
                if os.path.exists(path):
                    try:
                        f = ImageFont.truetype(path, px)
                        break
                    except Exception:
                        f = None
            if f is None:
                f = ImageFont.load_default()
            self._fonts[key] = f
        return f

    def _overlay(self):
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        return layer, ImageDraw.Draw(layer)

    def _merge(self, layer):
        self.img = Image.alpha_composite(self.img, layer)
        self.draw = ImageDraw.Draw(self.img)

    # -- primitives --------------------------------------------------------------
    def rect(self, x, y, w, h, fill=None, line=None, radius=0.0, alpha=1.0, line_w=1.0):
        if w <= 0 or h <= 0:
            return
        layer, d = self._overlay()
        box = [self._s(x), self._s(y), self._s(x + w), self._s(y + h)]
        f = rgb_tuple(fill) + (int(alpha * 255),) if fill else None
        ln = rgb_tuple(line) + (int(alpha * 255),) if line else None
        if radius > 0:
            d.rounded_rectangle(box, radius=self._s(radius), fill=f, outline=ln,
                                width=max(1, int(round(line_w * self.dpi / 72.0))))
        else:
            d.rectangle(box, fill=f, outline=ln, width=max(1, int(round(line_w * self.dpi / 72.0))))
        self._merge(layer)

    def ellipse(self, x, y, w, h, fill=None, line=None, alpha=1.0, line_w=1.0):
        if w <= 0 or h <= 0:
            return
        layer, d = self._overlay()
        box = [self._s(x), self._s(y), self._s(x + w), self._s(y + h)]
        f = rgb_tuple(fill) + (int(alpha * 255),) if fill else None
        ln = rgb_tuple(line) + (int(alpha * 255),) if line else None
        d.ellipse(box, fill=f, outline=ln, width=max(1, int(round(line_w * self.dpi / 72.0))))
        self._merge(layer)

    def polygon(self, points, fill=None, line=None, alpha=1.0, line_w=1.0):
        if len(points) < 3:
            return
        layer, d = self._overlay()
        pts = [(self._s(px), self._s(py)) for px, py in points]
        f = rgb_tuple(fill) + (int(alpha * 255),) if fill else None
        ln = rgb_tuple(line) + (int(alpha * 255),) if line else None
        d.polygon(pts, fill=f, outline=ln, width=max(1, int(round(line_w * self.dpi / 72.0))))
        self._merge(layer)

    def line(self, x1, y1, x2, y2, color, width=1.0, alpha=1.0):
        layer, d = self._overlay()
        d.line([self._s(x1), self._s(y1), self._s(x2), self._s(y2)],
               fill=rgb_tuple(color) + (int(alpha * 255),),
               width=max(1, int(round(width * self.dpi / 72.0))))
        self._merge(layer)

    def _wrap(self, text, font, max_w_px):
        out = []
        for raw in str(text).split("\n"):
            words = raw.split()
            if not words:
                out.append("")
                continue
            cur = words[0]
            for word in words[1:]:
                trial = cur + " " + word
                if self.draw.textlength(trial, font=font) <= max_w_px:
                    cur = trial
                else:
                    out.append(cur)
                    cur = word
            out.append(cur)
        return out

    def text(self, x, y, w, h, text, size=14, color="#FFFFFF", bold=False, italic=False,
             align="l", valign="t", alpha=1.0, line_gap=1.22, space_after=0.0, font=None):
        text = "" if text is None else str(text)
        if not text.strip():
            return 0.0
        size = max(size, MIN_FONT_PT)
        fnt = self._font(size, bold, italic)
        max_w = self._s(w)
        lines = self._wrap(text, fnt, max_w)
        lh = size * line_gap * self.dpi / 72.0
        gap = space_after * self.dpi / 72.0
        total = len(lines) * lh + max(0, len(lines) - 1) * gap
        cy = self._s(y)
        if valign == "m":
            cy = self._s(y) + (self._s(h) - total) / 2
        elif valign == "b":
            cy = self._s(y) + self._s(h) - total
        layer, d = self._overlay()
        col = rgb_tuple(color) + (int(alpha * 255),)
        for i, ln in enumerate(lines):
            ly = cy + i * (lh + gap)
            tw = d.textlength(ln, font=fnt)
            if align == "c":
                tx = self._s(x) + (max_w - tw) / 2
            elif align == "r":
                tx = self._s(x) + max_w - tw
            else:
                tx = self._s(x)
            d.text((tx, ly), ln, font=fnt, fill=col)
        self._merge(layer)
        return total / self.dpi

    def image(self, path, x, y, w, h, mode="cover", alt=""):
        if not path or not os.path.exists(path):
            return
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                tw, th = max(1, int(self._s(w))), max(1, int(self._s(h)))
                if mode == "cover":
                    src = im.width / im.height
                    tgt = tw / th
                    if src > tgt:
                        nw = int(im.height * tgt)
                        left = (im.width - nw) // 2
                        im = im.crop((left, 0, left + nw, im.height))
                    elif src < tgt:
                        nh = int(im.width / tgt)
                        top = (im.height - nh) // 2
                        im = im.crop((0, top, im.width, top + nh))
                im = im.resize((tw, th), Image.LANCZOS)
                self.img.paste(im, (int(self._s(x)), int(self._s(y))))
                self.draw = ImageDraw.Draw(self.img)
        except Exception:
            pass

    def save(self, path, quality=92):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        out = self.img.convert("RGB")
        out.save(path, quality=quality)
        return path


# --------------------------------------------------------------------------------------
# Chrome (header / footer) shared by the non-dark layouts
# --------------------------------------------------------------------------------------

def _accent_bar(c, th, x, y, w=0.72, h=0.045, color=None):
    c.rect(x, y, w, h, fill=color or th.accent)


def estimate_text_height(text, size, width_in, line_gap=1.32):
    """Rough height (inches) of a wrapped text block.

    Used to size cards / panels to their content instead of stretching them to the
    bottom of the slide, which is what makes a deck look ragged.
    """
    text = str(text or "").strip()
    if not text or width_in <= 0:
        return 0.0
    char_w = 0.5 * size / 72.0            # average glyph width of a proportional font
    cpl = max(6, int(width_in / char_w))
    lines = 0
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines += 1
            continue
        cur = 0
        for word in words:
            add = len(word) + (1 if cur else 0)
            if cur + add > cpl:
                lines += 1
                cur = len(word)
            else:
                cur += add
        lines += 1
    return lines * size * line_gap / 72.0


def _center_y(y, available, used, bias=0.35):
    """Place a content block in the canvas: mostly top aligned, nudged towards the middle."""
    if used >= available:
        return y
    return y + (available - used) * bias


def draw_header(c, th, tpl, data, number=None):
    """Family eyebrow + title + accent rule + slide index."""
    title = str(data.get("title") or tpl.name)
    c.text(LEFT, 0.36, 9.8, 0.28, tpl.family.upper(), 9, th.accent, bold=True)
    size = 28 if len(title) <= 46 else (24 if len(title) <= 62 else 21)
    c.title(LEFT, 0.70, 11.4, 0.8, title, size, th.text, bold=True, line_gap=1.15)
    _accent_bar(c, th, LEFT, 1.56)
    if number is not None:
        c.text(11.6, 0.40, 0.9, 0.3, f"{number:02d}", 10, th.muted, bold=True, align="r")


def draw_intro(c, th, data, box, size=14):
    intro = str(data.get("intro") or data.get("summary") or "").strip()
    if not intro:
        return 0.0
    h = c.text(box[0], box[1], box[2], 0.5, intro, size, th.muted, line_gap=1.3)
    return h + 0.22


# --------------------------------------------------------------------------------------
# Kind renderers
# --------------------------------------------------------------------------------------

def _r_title_slide(c, th, tpl, d, box):
    x, y, w, h = box
    c.rect(0, 0, 0.16, SLIDE_H, fill=th.accent)
    c.text(1.15, 1.62, 8.8, 0.32, str(d.get("eyebrow", "")).upper(), 11, th.accent2, bold=True)
    title = str(d.get("title", ""))
    size = 44 if len(title) <= 40 else (36 if len(title) <= 60 else 30)
    c.title(1.12, 2.18, 10.9, 1.6, title, size, th.text, bold=True, line_gap=1.1)
    c.text(1.15, 3.90, 9.8, 0.8, str(d.get("subtitle", "")), 19, th.body, line_gap=1.3)
    c.rect(1.15, 4.86, 1.0, 0.06, fill=th.accent)
    if d.get("footer"):
        c.text(1.15, 5.16, 8.8, 0.4, str(d["footer"]), 11, th.muted)


def _r_outro(c, th, tpl, d, box):
    x, y, w, h = box
    c.rect(0, 0, 0.16, SLIDE_H, fill=th.accent)
    c.text(1.15, 1.55, 8.8, 0.3, "NEXT STEPS", 11, th.accent2, bold=True)
    c.title(1.12, 1.95, 10.9, 1.1, str(d.get("title", "")), 40, th.text, bold=True, line_gap=1.1)
    c.text(1.15, 3.20, 9.6, 0.7, str(d.get("statement", "")), 20, th.body, line_gap=1.3)
    c.rect(1.15, 4.15, 1.0, 0.06, fill=th.accent)
    if d.get("action"):
        c.text(1.15, 4.46, 9.6, 0.4, str(d["action"]), 14, th.text)
    if d.get("contact"):
        c.text(1.15, 4.92, 9.6, 0.4, str(d["contact"]), 12, th.muted)


def _r_section_divider(c, th, tpl, d, box):
    x, y, w, h = box
    c.rect(0, 0, SLIDE_W, SLIDE_H, fill=th.bg, alpha=0.55)
    num = str(d.get("number", "01"))
    c.text(1.05, 1.35, 5.0, 2.2, num, 120, th.accent, bold=True, alpha=0.9, line_gap=1.0)
    c.text(1.12, 3.60, 8.6, 0.3, str(d.get("kicker", "SECTION")).upper(), 11, th.accent2, bold=True)
    c.title(1.10, 3.95, 10.6, 0.9, str(d.get("title", "")), 36, th.text, bold=True, line_gap=1.1)
    c.rect(1.12, 5.00, 1.0, 0.06, fill=th.accent)
    if d.get("subtitle"):
        c.text(1.12, 5.30, 9.4, 0.6, str(d["subtitle"]), 15, th.body)


def _r_bullets(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    bullets = d.get("bullets") or []
    size = 17 if len(bullets) <= 4 else 15
    c.bullets(x, y, min(w, 9.6), bullets, size=size, theme=th, gap=0.20)
    if d.get("note"):
        c.line(x, y + 3.9, x + 6.0, y + 3.9, th.border, 1)
        c.text(x, y + 4.05, 9.4, 0.5, str(d["note"]), 11, th.muted, italic=True)


def _r_cards(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    items = d.get("items") or []
    n = max(1, len(items))
    cols = 3 if n >= 3 else n
    rows = math.ceil(n / cols)
    gap = 0.32
    cw = (w - gap * (cols - 1)) / cols
    pad = 0.28
    # size the cards to their content instead of stretching them to the slide bottom
    head_h = (0.52 if items and items[0].get("number") else 0.0) + 0.48
    body_h = max([estimate_text_height(it.get("body"), 12.5, cw - 2 * pad) for it in items] or [0.0])
    card_h = min((h - 0.25 * (rows - 1)) / rows, pad * 2 + head_h + max(body_h, 0.5))
    ch = card_h
    block_h = rows * ch + 0.25 * (rows - 1)
    y = _center_y(y, h, block_h)
    accents = th.accent_cycle(n)
    for i, item in enumerate(items):
        cx = x + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + 0.25)
        c.rect(cx, cy, cw, ch, fill=th.surface, line=th.border, radius=0.14, alpha=0.86)
        c.rect(cx, cy, cw, 0.06, fill=accents[i % len(accents)])
        ty = cy + pad
        if item.get("number"):
            c.text(cx + pad, ty, cw - 2 * pad, 0.45, str(item["number"]), 22, accents[i % len(accents)], bold=True)
            ty += 0.52
        if item.get("heading"):
            c.text(cx + pad, ty, cw - 2 * pad, 0.45, str(item["heading"]), 16, th.text, bold=True)
            ty += 0.48
        if item.get("body"):
            c.text(cx + pad, ty, cw - 2 * pad, ch - (ty - cy) - pad, str(item["body"]), 12.5, th.body, line_gap=1.32)


def _r_panels(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    panels = d.get("panels") or []
    n = max(1, len(panels))
    gap = 0.36
    pw = (w - gap * (n - 1)) / n
    inner = pw - 0.56
    bullets_h = max([sum(estimate_text_height(b, 12.5, inner - 0.25) + 0.12
                            for b in (p.get("bullets") or [])) for p in panels] or [0.0])
    ph = min(h - 0.1, 1.35 + bullets_h + 0.2)
    y = _center_y(y, h, ph, bias=0.2)
    fills = [th.pale_blue, th.pale_green, th.pale_amber]
    for i, p in enumerate(panels):
        px = x + i * (pw + gap)
        c.rect(px, y, pw, ph, fill=fills[i % len(fills)], line=th.border, radius=0.14, alpha=0.9)
        c.text(px + 0.28, y + 0.30, pw - 0.56, 0.5, str(p.get("heading", "")), 16, th.text, bold=True)
        c.rect(px + 0.28, y + 0.86, 0.6, 0.04, fill=th.accent)
        c.bullets(px + 0.28, y + 1.12, pw - 0.5, p.get("bullets") or [], size=12.5, theme=th, gap=0.12)


def _r_two_panel(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    gap = 0.4
    pw = (w - gap) / 2
    inner = pw - 0.55
    bullets_h = max([sum(estimate_text_height(b, 13, inner - 0.25) + 0.14
                            for b in ((d.get(k) or {}).get("bullets") or []))
                      for k in ("left", "right")] or [0.0])
    ph = min(h - 0.1, 1.35 + bullets_h + 0.2)
    y = _center_y(y, h, ph, bias=0.2)
    for i, key in enumerate(("left", "right")):
        p = d.get(key) or {}
        px = x + i * (pw + gap)
        c.rect(px, y, pw, ph, fill=th.surface, line=th.border, radius=0.14, alpha=0.88)
        c.text(px + 0.3, y + 0.32, pw - 0.6, 0.45, str(p.get("heading", "")), 17, th.text, bold=True)
        c.rect(px + 0.3, y + 0.90, 0.7, 0.05, fill=th.accent if i == 0 else th.accent2)
        c.bullets(px + 0.3, y + 1.20, pw - 0.55, p.get("bullets") or [], size=13, theme=th, gap=0.14)
    if d.get("change"):
        cx = x + pw + gap / 2
        c.ellipse(cx - 0.28, y + ph / 2 - 0.28, 0.56, 0.56, fill=th.accent)
        c.text(cx - 0.28, y + ph / 2 - 0.12, 0.56, 0.3, "→", 16, th.bg, bold=True, align="c")


def _r_pso(c, th, tpl, d, box):
    x, y, w, h = box
    steps = d.get("steps") or []
    n = max(1, len(steps))
    gap = 0.4
    cw = (w - gap * (n - 1)) / n
    fills = [th.pale_red, th.pale_blue, th.pale_green]
    for i, s in enumerate(steps):
        cx = x + i * (cw + gap)
        c.rect(cx, y + 0.35, cw, h - 0.45, fill=fills[i % 3], line=th.border, radius=0.14, alpha=0.9)
        c.text(cx + 0.26, y + 0.62, cw - 0.52, 0.3, str(s.get("label", "")).upper(), 10.5,
              th.accent if i != 0 else th.red, bold=True)
        c.text(cx + 0.26, y + 1.00, cw - 0.52, 0.5, str(s.get("heading", "")), 17, th.text, bold=True)
        c.text(cx + 0.26, y + 1.58, cw - 0.52, h - 2.2, str(s.get("body", "")), 12.5, th.body, line_gap=1.32)
        if i < n - 1:
            ax = cx + cw + 0.06
            c.text(ax, y + h / 2 - 0.2, gap - 0.12, 0.4, "→", 16, th.muted, align="c")


def _r_editorial(c, th, tpl, d, box):
    x, y, w, h = box
    lw = 4.35
    c.text(x, y + 0.15, lw, 1.6, str(d.get("headline", "")), 27, th.text, bold=True, line_gap=1.14)
    c.rect(x, y + 1.95, 0.7, 0.05, fill=th.accent)
    if d.get("summary"):
        c.text(x, y + 2.20, lw - 0.2, 1.2, str(d["summary"]), 14, th.muted, line_gap=1.34)
    rx = x + lw + 0.5
    rw = w - lw - 0.5
    paras = d.get("paragraphs") or []
    cy = y + 0.15
    for i, p in enumerate(paras):
        hgt = c.text(rx, cy, rw, 1.6, str(p), 14.5, th.body, line_gap=1.42)
        cy += hgt + 0.34
        if i < len(paras) - 1:
            c.line(rx, cy - 0.16, rx + rw, cy - 0.16, th.border, 1)


def _r_checklist(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    items = d.get("items") or []
    n = max(1, len(items))
    rowh = min(0.95, (h - 0.1) / n)
    for i, it in enumerate(items):
        ry = y + i * rowh
        c.ellipse(x, ry + 0.06, 0.34, 0.34, fill=th.accent, alpha=0.22)
        c.text(x, ry + 0.10, 0.34, 0.3, "✓", 13, th.accent, bold=True, align="c")
        c.text(x + 0.56, ry + 0.04, w - 0.6, 0.34, str(it.get("heading", "")), 15.5, th.text, bold=True)
        if it.get("body"):
            c.text(x + 0.56, ry + 0.40, w - 0.6, 0.4, str(it["body"]), 12, th.muted)


def _r_icon_strip(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    items = d.get("items") or []
    n = max(1, len(items))
    gap = 0.45
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    for i, it in enumerate(items):
        cx = x + i * (cw + gap)
        c.ellipse(cx + cw / 2 - 0.42, y + 0.10, 0.84, 0.84, fill=accents[i], alpha=0.18)
        c.ellipse(cx + cw / 2 - 0.42, y + 0.10, 0.84, 0.84, line=accents[i], line_w=1.4)
        c.text(cx + cw / 2 - 0.42, y + 0.34, 0.84, 0.4, "0" + str(i + 1), 17, accents[i], bold=True, align="c")
        c.text(cx, y + 1.16, cw, 0.4, str(it.get("heading", "")), 16, th.text, bold=True, align="c")
        c.text(cx, y + 1.62, cw, 1.2, str(it.get("body", "")), 12.5, th.body, align="c", line_gap=1.32)


def _r_quote(c, th, tpl, d, box):
    x, y, w, h = box
    q = str(d.get("quote", ""))
    size = 27 if len(q) <= 110 else (22 if len(q) <= 170 else 19)
    c.rect(x + 0.12, y + 0.15, 0.08, 2.6, fill=th.accent)
    c.text(x + 0.62, y + 0.18, w - 0.9, 2.4, q, size, th.text, bold=True, italic=True, line_gap=1.28)
    c.text(x + 0.66, y + 2.95, 8.0, 0.4, str(d.get("attribution", "")), 13, th.muted)
    if d.get("note"):
        c.text(x + 0.66, y + 3.35, 9.0, 0.4, str(d["note"]), 11, th.muted, italic=True)


def _r_quote_evidence(c, th, tpl, d, box):
    x, y, w, h = box
    mw = w * 0.66
    c.rect(x, y, mw, h - 0.15, fill=th.surface, line=th.border, radius=0.14, alpha=0.85)
    c.rect(x + 0.34, y + 0.36, 0.08, 1.9, fill=th.accent)
    c.text(x + 0.70, y + 0.42, mw - 1.1, 1.9, str(d.get("quote", "")), 21, th.text,
           bold=True, italic=True, line_gap=1.28)
    c.text(x + 0.72, y + 2.55, mw - 1.1, 0.4, str(d.get("attribution", "")), 12, th.muted)
    metric = d.get("metric") or {}
    px = x + mw + 0.35
    pw = w - mw - 0.35
    c.rect(px, y, pw, h - 0.15, fill=th.pale_blue, line=th.border, radius=0.14, alpha=0.92)
    c.text(px + 0.2, y + 0.95, pw - 0.4, 0.9, str(metric.get("value", "")), 33, th.accent, bold=True, align="c")
    c.text(px + 0.2, y + 1.95, pw - 0.4, 0.8, str(metric.get("label", "")), 12.5, th.text,
           bold=True, align="c", line_gap=1.3)


def _r_big_statement(c, th, tpl, d, box):
    x, y, w, h = box
    pw = 4.35
    c.rect(x, y, pw, h - 0.05, fill=th.accent_solid)
    c.text(x + 0.45, y + 0.55, pw - 0.9, 2.4, str(d.get("statement", "")), 30, "#FFFFFF",
           bold=True, line_gap=1.14)
    rx = x + pw + 0.5
    rw = w - pw - 0.5
    c.text(rx, y + 0.45, rw, 0.7, str(d.get("title", "")), 26, th.text, bold=True)
    c.rect(rx, y + 1.28, 0.7, 0.05, fill=th.accent2)
    c.bullets(rx, y + 1.65, rw - 0.2, d.get("bullets") or [], size=15, theme=th, gap=0.22)


def _r_metrics(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    items = d.get("items") or []
    n = max(1, len(items))
    gap = 0.4
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    # the metric block is only as tall as it needs to be
    block_h = 2.45
    y = _center_y(y, h, block_h)
    for i, it in enumerate(items):
        cx = x + i * (cw + gap)
        if i:
            c.line(cx - gap / 2, y + 0.25, cx - gap / 2, y + block_h - 0.45, th.border, 1)
        size = 42 if len(str(it.get("value", ""))) <= 6 else 32
        c.text(cx, y + 0.55, cw, 1.0, str(it.get("value", "")), size, accents[i], bold=True, align="c")
        c.text(cx, y + 1.70, cw, 0.45, str(it.get("label", "")), 15, th.text, bold=True, align="c")
        if it.get("note"):
            c.text(cx, y + 2.18, cw, 0.4, str(it["note"]), 11, th.muted, align="c")


def _r_metric_band(c, th, tpl, d, box):
    x, y, w, h = box
    hl = d.get("headline") or {}
    c.text(x, y + 0.05, w, 1.5, str(hl.get("value", "")), 72, th.accent, bold=True, align="c", line_gap=1.0)
    c.text(x, y + 1.65, w, 0.5, str(hl.get("label", "")), 19, th.text, bold=True, align="c")
    if hl.get("note"):
        c.text(x, y + 2.18, w, 0.5, str(hl["note"]), 12.5, th.muted, align="c")
    stats = d.get("stats") or []
    n = max(1, len(stats))
    gap = 0.3
    cw = (w - gap * (n - 1)) / n
    by = y + 2.95
    for i, s in enumerate(stats):
        cx = x + i * (cw + gap)
        c.rect(cx, by, cw, 1.05, fill=th.surface, line=th.border, radius=0.12, alpha=0.85)
        c.text(cx + 0.16, by + 0.18, cw - 0.32, 0.45, str(s.get("value", "")), 19, th.accent2, bold=True, align="c")
        c.text(cx + 0.16, by + 0.62, cw - 0.32, 0.35, str(s.get("label", "")), 11, th.muted, align="c")


def _r_scorecard(c, th, tpl, d, box):
    x, y, w, h = box
    metrics = d.get("metrics") or []
    n = max(1, len(metrics))
    gap = 0.28
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    for i, m in enumerate(metrics):
        cx = x + i * (cw + gap)
        c.rect(cx, y, cw, 1.75, fill=th.surface, line=th.border, radius=0.12, alpha=0.86)
        c.text(cx + 0.18, y + 0.22, cw - 0.36, 0.6, str(m.get("value", "")), 24, accents[i], bold=True)
        c.text(cx + 0.18, y + 0.86, cw - 0.36, 0.35, str(m.get("label", "")), 11.5, th.text, bold=True)
        if m.get("status"):
            c.text(cx + 0.18, y + 1.25, cw - 0.36, 0.3, str(m["status"]), 10, th.muted)
    ty = y + 2.05
    c.rect(x, ty, w, h - 2.2, fill=th.surface, line=th.border, radius=0.12, alpha=0.7)
    c.text(x + 0.3, ty + 0.22, 4.0, 0.35, "Trend / status summary", 14, th.text, bold=True)
    trend = [num(v) for v in (d.get("trend") or [])] or [0.4, 0.6, 0.5, 0.8]
    vals = trend[-10:]
    mx = max(vals) or 1
    base = ty + (h - 2.2) - 0.35
    bh = (h - 2.2) - 1.0
    bw = 0.36
    step = (w - 1.2) / max(1, len(vals))
    for i, v in enumerate(vals):
        bx = x + 0.55 + i * step
        hh = max(0.08, bh * (v / mx))
        c.rect(bx, base - hh, bw, hh, fill=th.accent if i == len(vals) - 1 else th.bar,
               alpha=1.0 if i == len(vals) - 1 else 0.5)


def _r_numbered_row(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    steps = d.get("steps") or []
    n = max(1, len(steps))
    gap = 0.34
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    body_h = max([estimate_text_height(s.get("body"), 12, cw - 0.4) for s in steps] or [0.0])
    card_h = min(h - 0.6, 1.62 + body_h + 0.2)
    block_h = 0.45 + card_h
    y = _center_y(y, h, block_h, bias=0.2)
    for i, s in enumerate(steps):
        cx = x + i * (cw + gap)
        c.rect(cx, y + 0.45, cw, card_h, fill=th.surface, line=th.border, radius=0.14, alpha=0.86)
        c.ellipse(cx + cw / 2 - 0.28, y, 0.56, 0.56, fill=accents[i])
        c.text(cx + cw / 2 - 0.28, y + 0.12, 0.56, 0.35, str(s.get("number", i + 1)),
               15, th.bg, bold=True, align="c")
        c.text(cx + 0.2, y + 1.15, cw - 0.4, 0.4, str(s.get("heading", "")), 15.5, th.text, bold=True, align="c")
        c.text(cx + 0.2, y + 1.62, cw - 0.4, card_h - 1.25, str(s.get("body", "")), 12, th.body,
               align="c", line_gap=1.32)
        if i < n - 1:
            c.line(cx + cw + 0.06, y + 0.28, cx + cw + gap - 0.06, y + 0.28, th.border, 1.5)


def _r_numbered_stack(c, th, tpl, d, box):
    x, y, w, h = box
    steps = d.get("steps") or []
    n = max(1, len(steps))
    rowh = min(1.15, (h - 0.1) / n)
    c.line(x + 0.34, y + 0.25, x + 0.34, y + rowh * (n - 1) + 0.55, th.border, 2)
    accents = th.accent_cycle(n)
    for i, s in enumerate(steps):
        ry = y + i * rowh
        c.ellipse(x, ry, 0.68, 0.68, fill=accents[i])
        c.text(x, ry + 0.17, 0.68, 0.35, str(s.get("number", i + 1)), 15, th.bg, bold=True, align="c")
        c.text(x + 1.0, ry + 0.02, w - 1.2, 0.4, str(s.get("heading", "")), 16.5, th.text, bold=True)
        c.text(x + 1.0, ry + 0.46, w - 1.2, 0.7, str(s.get("body", "")), 12.5, th.body, line_gap=1.32)


def _r_timeline(c, th, tpl, d, box):
    x, y, w, h = box
    ms = d.get("milestones") or []
    n = max(1, len(ms))
    axis_y = y + 2.05
    c.rect(x + 0.25, axis_y, w - 0.5, 0.045, fill=th.border)
    step = (w - 1.1) / max(1, n - 1) if n > 1 else 0
    accents = th.accent_cycle(n)
    for i, m in enumerate(ms):
        nx = x + 0.55 + i * step
        c.ellipse(nx, axis_y - 0.15, 0.34, 0.34, fill=accents[i])
        above = (i % 2 == 0)
        ty = axis_y - 1.65 if above else axis_y + 0.42
        def _lx(width, nx=nx):      # centred on the dot, but never outside the safe margins
            return min(max(nx + 0.17 - width / 2, LEFT), RIGHT - width)
        c.text(_lx(1.8), ty, 1.8, 0.3, str(m.get("period", "")), 11.5, accents[i], bold=True,
               align="c")
        c.text(_lx(2.0), ty + 0.34, 2.0, 0.35, str(m.get("heading", "")), 15, th.text, bold=True, align="c")
        c.text(_lx(2.2), ty + 0.74, 2.2, 0.6, str(m.get("body", "")), 11, th.muted, align="c", line_gap=1.3)


def _r_swimlane(c, th, tpl, d, box):
    x, y, w, h = box
    periods = d.get("periods") or []
    lanes = d.get("lanes") or []
    n = max(1, len(periods))
    lx = x + 1.75
    colw = (w - 1.85) / max(1, n)
    for j, p in enumerate(periods):
        c.text(lx + j * colw, y, colw, 0.3, str(p).upper(), 10.5, th.muted, bold=True, align="c")
    accents = th.accent_cycle(len(lanes))
    lane_h = (h - 0.6) / max(1, len(lanes))
    for i, lane in enumerate(lanes):
        ly = y + 0.5 + i * lane_h
        c.text(x, ly + 0.22, 1.6, 0.35, str(lane.get("name", "")), 12, th.text, bold=True)
        c.line(x, ly + lane_h - 0.12, x + w, ly + lane_h - 0.12, th.border, 1)
        for j, it in enumerate((lane.get("items") or [])[:n]):
            bx = lx + j * colw + 0.08
            c.rect(bx, ly, colw - 0.16, lane_h - 0.3, fill=th.pale_blue if j % 2 == 0 else th.surface,
                   line=th.border, radius=0.10, alpha=0.9)
            c.text(bx + 0.14, ly + 0.14, colw - 0.44, 0.5, str(it.get("label", "")), 11, th.text, bold=True)


def _r_journey(c, th, tpl, d, box):
    x, y, w, h = box
    stages = d.get("stages") or []
    n = max(1, len(stages))
    gap = 0.26
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    for i, st in enumerate(stages):
        cx = x + i * (cw + gap)
        c.rect(cx, y, cw, 0.62, fill=th.pale_blue, line=th.border, radius=0.10, alpha=0.92)
        c.text(cx + 0.12, y + 0.16, cw - 0.24, 0.35, str(st.get("heading", "")), 13, th.text,
               bold=True, align="c")
        acts = st.get("actions") or []
        for j, a in enumerate(acts):
            ay = y + 0.85 + j * 0.95
            c.text(cx + 0.08, ay, cw - 0.16, 0.25, str(a.get("label", "")), 9.5,
                   th.accent if j == len(acts) - 1 else th.muted, bold=True)
            c.rect(cx + 0.08, ay + 0.28, cw - 0.16, 0.52, fill=th.surface, line=th.border, radius=0.08, alpha=0.85)
            c.text(cx + 0.18, ay + 0.36, cw - 0.36, 0.4, str(a.get("text", "")), 10.5, th.body)


def _r_cycle(c, th, tpl, d, box):
    x, y, w, h = box
    steps = d.get("steps") or []
    n = max(1, len(steps))
    cx, cy = x + w / 2, y + h / 2
    c.ellipse(cx - 1.25, cy - 0.85, 2.5, 1.7, fill=th.pale_blue, line=th.accent, line_w=1.6, alpha=0.95)
    c.text(cx - 1.15, cy - 0.32, 2.3, 0.7, str(d.get("center", "")), 13, th.text, bold=True,
           align="c", line_gap=1.2)
    rx, ry = 3.65, 1.85
    accents = th.accent_cycle(n)
    for i in range(n):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        px = cx + rx * math.cos(ang)
        py = cy + ry * math.sin(ang)
        c.ellipse(px - 0.78, py - 0.4, 1.56, 0.8, fill=th.surface, line=th.accent, line_w=1.4, alpha=0.92)
        c.text(px - 0.78, py - 0.16, 1.56, 0.35, str(steps[i].get("heading", "")), 11.5,
               th.text, bold=True, align="c")


def _r_funnel(c, th, tpl, d, box):
    x, y, w, h = box
    stages = d.get("stages") or []
    n = max(1, len(stages))
    sh = min(0.78, (h - 0.3) / n)
    colors = [th.accent_solid, "#1F2A44", th.accent2, th.green, th.amber, th.red]
    light = {2, 3, 4}          # fills that are too light for white text
    for i, s in enumerate(stages):
        wid = w * (1 - i * 0.11)
        cx = x + (w - wid) / 2
        sy = y + i * (sh + 0.12)
        c.polygon([(cx, sy), (cx + wid, sy), (cx + wid - 0.22, sy + sh), (cx + 0.22, sy + sh)],
                  fill=colors[i % len(colors)], alpha=0.95)
        fg = th.bg if (i % len(colors)) in light else "#FFFFFF"
        c.text(cx + 0.2, sy + sh / 2 - 0.16, wid - 1.5, 0.35, str(s.get("heading", "")), 12.5,
               fg, bold=True, align="c")
        c.text(cx + wid - 1.3, sy + sh / 2 - 0.16, 1.1, 0.35, str(s.get("value", "")), 12.5,
               fg, bold=True, align="r")


def _r_quad(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    quads = d.get("quadrants") or []
    n = max(1, len(quads))
    cols = 2 if n >= 2 else 1
    rows = math.ceil(n / cols)
    gap = 0.3
    cw = (w - gap) / cols
    body_h = max([estimate_text_height(q.get("body"), 12.5, cw - 0.52) for q in quads] or [0.0])
    ch = min((h - 0.1 - gap * (rows - 1)) / rows, 0.95 + body_h + 0.2)
    block_h = rows * ch + gap * (rows - 1)
    y = _center_y(y, h, block_h, bias=0.25)
    fills = [th.pale_blue, th.pale_amber, th.pale_green, th.pale_red]
    for i, q in enumerate(quads):
        cx = x + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + gap)
        c.rect(cx, cy, cw, ch, fill=fills[i % 4], line=th.border, radius=0.14, alpha=0.92)
        c.text(cx + 0.26, cy + 0.26, cw - 0.52, 0.42, str(q.get("heading", "")), 15.5, th.text, bold=True)
        c.text(cx + 0.26, cy + 0.78, cw - 0.52, ch - 0.9, str(q.get("body", "")), 12.5, th.body, line_gap=1.34)


def _r_swot(c, th, tpl, d, box):
    x, y, w, h = box
    quads = d.get("quadrants") or []
    gap = 0.3
    cw = (w - gap) / 2
    body_h = max([estimate_text_height(q.get("body"), 12.5, cw - 0.56) for q in quads] or [0.0])
    ch = min((h - gap) / 2, 0.95 + body_h + 0.2)
    block_h = ch * 2 + gap
    y = _center_y(y, h, block_h, bias=0.25)
    fills = [th.pale_green, th.pale_red, th.pale_blue, th.pale_amber]
    accents = [th.green, th.red, th.accent, th.amber]
    for i, q in enumerate(quads):
        cx = x + (i % 2) * (cw + gap)
        cy = y + (i // 2) * (ch + gap)
        c.rect(cx, cy, cw, ch, fill=fills[i % 4], line=th.border, radius=0.14, alpha=0.92)
        c.rect(cx, cy, 0.07, ch, fill=accents[i % 4])
        c.text(cx + 0.3, cy + 0.26, cw - 0.56, 0.42, str(q.get("heading", "")), 16,
               accents[i % 4], bold=True)
        c.text(cx + 0.3, cy + 0.80, cw - 0.56, ch - 0.9, str(q.get("body", "")), 12.5, th.body, line_gap=1.34)


def _r_triptych(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    panels = d.get("panels") or []
    n = max(1, len(panels))
    gap = 0.36
    pw = (w - gap * (n - 1)) / n
    body_h = max([estimate_text_height(p.get("body"), 13.5, pw - 0.56) for p in panels] or [0.0])
    ph = min(h - 0.15, 1.2 + body_h + 0.25)
    y = _center_y(y, h, ph, bias=0.2)
    accents = th.accent_cycle(n)
    for i, p in enumerate(panels):
        px = x + i * (pw + gap)
        c.rect(px, y, pw, ph, fill=th.surface, line=th.border, radius=0.12, alpha=0.85)
        c.text(px + 0.28, y + 0.32, pw - 0.56, 0.42, str(p.get("heading", "")), 16, accents[i], bold=True)
        c.rect(px + 0.28, y + 0.88, pw - 0.56, 0.02, fill=th.border)
        c.text(px + 0.28, y + 1.08, pw - 0.56, ph - 1.25, str(p.get("body", "")), 13.5, th.body, line_gap=1.36)


def _r_retro(c, th, tpl, d, box):
    x, y, w, h = box
    cols = d.get("columns") or []
    n = max(1, len(cols))
    gap = 0.34
    cw = (w - gap * (n - 1)) / n
    bullets_h = max([sum(estimate_text_height(b, 12.5, cw - 0.75) + 0.14
                            for b in (col.get("bullets") or [])) for col in cols] or [0.0])
    ch = min(h - 0.15, 1.2 + bullets_h + 0.2)
    y = _center_y(y, h, ch, bias=0.2)
    fills = [th.pale_green, th.pale_red, th.pale_blue]
    accents = [th.green, th.red, th.accent]
    for i, col in enumerate(cols):
        cx = x + i * (cw + gap)
        c.rect(cx, y, cw, ch, fill=fills[i % 3], line=th.border, radius=0.14, alpha=0.92)
        c.text(cx + 0.28, y + 0.3, cw - 0.56, 0.4, str(col.get("heading", "")), 16, accents[i % 3], bold=True)
        c.rect(cx + 0.28, y + 0.84, cw - 0.56, 0.02, fill=th.border)
        c.bullets(cx + 0.28, y + 1.06, cw - 0.5, col.get("bullets") or [], size=12.5, theme=th, gap=0.14)


def _r_pyramid(c, th, tpl, d, box):
    x, y, w, h = box
    levels = d.get("levels") or []
    n = max(1, len(levels))
    lh = min(0.95, (h - 0.2) / n)
    colors = [th.accent_solid, "#1F2A44", th.accent2, th.green, th.amber]
    for i, l in enumerate(levels):
        wid = 3.2 + i * 1.35
        cx = x + (w - wid) / 2
        sy = y + i * (lh + 0.10)
        c.polygon([(cx, sy), (cx + wid, sy), (cx + wid - 0.28, sy + lh), (cx + 0.28, sy + lh)],
                  fill=colors[i % len(colors)], alpha=0.95)
        fg = th.bg if (i % len(colors)) in (2, 3, 4) else "#FFFFFF"
        c.text(cx + 0.2, sy + lh / 2 - 0.18, wid - 0.4, 0.4, str(l.get("heading", "")), 13,
               fg, bold=True, align="c")


def _r_layers(c, th, tpl, d, box):
    x, y, w, h = box
    layers = d.get("layers") or []
    n = max(1, len(layers))
    lh = min(0.9, (h - 0.2) / n)
    fills = [th.pale_blue, th.pale_cyan, th.pale_green, "#1F2A44", th.pale_amber]
    for i, l in enumerate(layers):
        sy = y + i * (lh + 0.12)
        c.rect(x + 1.1, sy, w - 2.2, lh, fill=fills[i % len(fills)], line=th.border, radius=0.10, alpha=0.92)
        c.text(x + 1.25, sy + lh / 2 - 0.18, w - 2.5, 0.4, str(l.get("heading", "")), 13.5,
               th.text, bold=True, align="c")
        if l.get("body"):
            c.text(x + 1.25, sy + lh / 2 + 0.18, w - 2.5, 0.35, str(l["body"]), 10.5, th.muted, align="c")


def _r_hub_spoke(c, th, tpl, d, box):
    x, y, w, h = box
    spokes = d.get("spokes") or []
    n = max(1, len(spokes))
    cx, cy = x + w / 2, y + h / 2
    rx, ry = 4.35, 1.95
    c.ellipse(cx - 1.4, cy - 0.72, 2.8, 1.44, fill=th.surface, line=th.accent, line_w=1.6, alpha=0.95)
    c.text(cx - 1.3, cy - 0.22, 2.6, 0.5, str(d.get("hub", "")), 13, th.text, bold=True, align="c")
    accents = th.accent_cycle(n)
    for i in range(n):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        px = cx + rx * math.cos(ang)
        py = cy + ry * math.sin(ang)
        c.line(cx, cy, px, py, th.border, 1.4)
        c.rect(px - 0.95, py - 0.38, 1.9, 0.76, fill=th.pale_blue, line=th.accent, radius=0.10, alpha=0.95)
        c.text(px - 0.95, py - 0.14, 1.9, 0.35, str(spokes[i].get("heading", "")), 11,
               th.text, bold=True, align="c")


def _r_decision(c, th, tpl, d, box):
    x, y, w, h = box
    cx = x + w / 2
    c.polygon([(cx, y + 0.1), (cx + 1.35, y + 0.95), (cx, y + 1.8), (cx - 1.35, y + 0.95)],
              fill=th.pale_amber, line=th.amber, line_w=1.4)
    c.text(cx - 1.2, y + 0.78, 2.4, 0.4, str(d.get("question", "")), 12, th.text, bold=True, align="c")
    branches = d.get("branches") or []
    n = max(1, len(branches))
    bw = 2.8
    start = cx - (n * bw + (n - 1) * 0.5) / 2
    for i, b in enumerate(branches):
        bx = start + i * (bw + 0.5)
        c.line(cx, y + 1.8, bx + bw / 2, y + 2.5, th.border, 1.4)
        fill = th.pale_green if i == 0 else th.pale_red
        c.rect(bx, y + 2.5, bw, 1.5, fill=fill, line=th.border, radius=0.12, alpha=0.92)
        c.text(bx + 0.16, y + 2.68, bw - 0.32, 0.3, str(b.get("label", "")), 10, th.accent, bold=True)
        c.text(bx + 0.16, y + 3.02, bw - 0.32, 0.35, str(b.get("heading", "")), 13.5, th.text, bold=True)
        c.text(bx + 0.16, y + 3.42, bw - 0.32, 0.5, str(b.get("body", "")), 11, th.body)


def _r_ranking(c, th, tpl, d, box):
    x, y, w, h = box
    items = d.get("items") or []
    n = max(1, len(items))
    rowh = min(0.95, (h - 0.1) / n)
    accents = th.accent_cycle(n)
    for i, it in enumerate(items):
        ry = y + i * rowh
        c.rect(x, ry, 0.66, 0.62, fill=accents[i], radius=0.10)
        c.text(x, ry + 0.16, 0.66, 0.35, str(it.get("number", i + 1)), 13, th.bg, bold=True, align="c")
        c.text(x + 0.95, ry + 0.02, 2.6, 0.35, str(it.get("heading", "")), 15, th.text, bold=True)
        c.text(x + 3.75, ry + 0.04, w - 3.9, 0.45, str(it.get("body", "")), 12, th.muted)


def _r_faq(c, th, tpl, d, box):
    x, y, w, h = box
    pairs = d.get("pairs") or []
    n = max(1, len(pairs))
    rowh = min(1.15, (h - 0.1) / n)
    for i, p in enumerate(pairs):
        ry = y + i * rowh
        c.rect(x, ry, 0.06, rowh - 0.16, fill=th.accent)
        c.text(x + 0.28, ry, w * 0.42, 0.4, str(p.get("question", "")), 14, th.text, bold=True)
        c.text(x + w * 0.45, ry, w * 0.53, 0.8, str(p.get("answer", "")), 12, th.body, line_gap=1.32)


def _r_feature_matrix(c, th, tpl, d, box):
    x, y, w, h = box
    options = d.get("options") or []
    rows = d.get("rows") or []
    nopt = max(1, len(options))
    label_w = w * 0.36
    colw = (w - label_w) / nopt
    hy = y + 0.35
    for j, o in enumerate(options):
        c.rect(x + label_w + j * colw + 0.04, hy, colw - 0.08, 0.5,
               fill=th.pale_blue if j == 0 else th.surface, line=th.border, radius=0.08, alpha=0.9)
        c.text(x + label_w + j * colw + 0.14, hy + 0.13, colw - 0.28, 0.3, str(o), 11.5,
               th.accent if j == 0 else th.text, bold=True, align="c")
    rowh = min(0.72, (h - 1.1) / max(1, len(rows)))
    for i, r in enumerate(rows):
        ry = hy + 0.68 + i * rowh
        c.text(x, ry + 0.08, label_w - 0.2, 0.4, str(r.get("feature", "")), 12, th.text, bold=True)
        for j in range(nopt):
            val = str((r.get("values") or [""] * nopt)[j] if j < len(r.get("values") or []) else "")
            c.rect(x + label_w + j * colw + 0.04, ry, colw - 0.08, rowh - 0.1,
                   fill=th.surface if i % 2 else th.surface_alt, line=th.border, radius=0.06, alpha=0.7)
            c.text(x + label_w + j * colw + 0.14, ry + 0.09, colw - 0.28, 0.35, val, 11.5,
                   th.body, align="c")


def _r_personas(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    people = d.get("people") or []
    n = max(1, len(people))
    gap = 0.45
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    for i, p in enumerate(people):
        cx = x + i * (cw + gap)
        c.ellipse(cx + cw / 2 - 0.72, y + 0.1, 1.44, 1.44, fill=th.pale_blue, line=th.border, line_w=1.2)
        initials = "".join(str(p.get("name", "")).split()[:2])[:2].upper()
        c.text(cx + cw / 2 - 0.72, y + 0.62, 1.44, 0.5, initials, 22, accents[i], bold=True, align="c")
        c.text(cx, y + 1.75, cw, 0.4, str(p.get("name", "")), 16, th.text, bold=True, align="c")
        c.text(cx, y + 2.20, cw, 0.3, str(p.get("role", "")), 12, accents[i], bold=True, align="c")
        c.text(cx + 0.2, y + 2.62, cw - 0.4, 1.1, str(p.get("bio", "")), 11.5, th.muted, align="c", line_gap=1.32)


def _r_persona_cards(c, th, tpl, d, box):
    x, y, w, h = box
    people = d.get("people") or []
    n = max(1, len(people))
    gap = 0.34
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    for i, p in enumerate(people):
        cx = x + i * (cw + gap)
        c.rect(cx, y, cw, h - 0.15, fill=th.surface, line=th.border, radius=0.14, alpha=0.86)
        c.ellipse(cx + 0.3, y + 0.28, 0.78, 0.78, fill=accents[i], alpha=0.2)
        c.text(cx + 0.3, y + 0.52, 0.78, 0.4, "".join(str(p.get("name", "")).split()[:1])[:1].upper(),
               18, accents[i], bold=True, align="c")
        c.text(cx + 1.2, y + 0.34, cw - 1.4, 0.35, str(p.get("name", "")), 15, th.text, bold=True)
        c.text(cx + 1.2, y + 0.72, cw - 1.4, 0.3, str(p.get("role", "")), 11, th.muted)
        ty = y + 1.28
        for trait in (p.get("traits") or []):
            c.rect(cx + 0.3, ty, 0.14, 0.14, fill=accents[i], radius=0.05)
            c.text(cx + 0.58, ty - 0.03, cw - 0.9, 0.3, str(trait), 11.5, th.body)
            ty += 0.34
        c.text(cx + 0.3, ty + 0.08, cw - 0.6, 1.1, str(p.get("bio", "")), 11.5, th.muted, line_gap=1.32)


def _r_directory(c, th, tpl, d, box):
    x, y, w, h = box
    people = d.get("people") or []
    n = max(1, len(people))
    cols = 3 if n >= 3 else n
    rows = math.ceil(n / cols)
    gap = 0.28
    cw = (w - gap * (cols - 1)) / cols
    ch = (h - 0.2 - gap * (rows - 1)) / rows
    accents = th.accent_cycle(n)
    for i, p in enumerate(people):
        cx = x + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + gap)
        c.rect(cx, cy, cw, ch, fill=th.surface, line=th.border, radius=0.12, alpha=0.86)
        c.ellipse(cx + 0.26, cy + 0.26, 0.62, 0.62, fill=accents[i], alpha=0.2)
        c.text(cx + 0.26, cy + 0.44, 0.62, 0.35,
               "".join(str(p.get("name", "")).split()[:2])[:2].upper(), 15, accents[i], bold=True, align="c")
        c.text(cx + 1.02, cy + 0.28, cw - 1.2, 0.32, str(p.get("name", "")), 14, th.text, bold=True)
        c.text(cx + 1.02, cy + 0.62, cw - 1.2, 0.28, str(p.get("role", "")), 11, accents[i], bold=True)
        c.text(cx + 0.26, cy + 1.08, cw - 0.5, 0.32, str(p.get("contact", "")), 11, th.muted)


def _r_hierarchy(c, th, tpl, d, box):
    x, y, w, h = box
    children = d.get("children") or []
    n = max(1, len(children))
    c.rect(x + w / 2 - 2.0, y + 0.15, 4.0, 0.72, fill=th.surface, line=th.accent, radius=0.12, alpha=0.9)
    c.text(x + w / 2 - 1.9, y + 0.36, 3.8, 0.4, str(d.get("root", "")), 14, th.text, bold=True, align="c")
    cw = (w - 0.4 * (n - 1)) / n
    top = y + 1.75
    centers = [x + i * (cw + 0.4) + cw / 2 for i in range(n)]
    c.line(x + w / 2, y + 0.87, x + w / 2, y + 1.35, th.border, 1.4)
    if n > 1:
        c.line(centers[0], y + 1.35, centers[-1], y + 1.35, th.border, 1.4)
    for i, ch in enumerate(children):
        cx = x + i * (cw + 0.4)
        c.line(centers[i], y + 1.35, centers[i], top, th.border, 1.4)
        c.rect(cx, top, cw, 1.65, fill=th.surface, line=th.border, radius=0.12, alpha=0.88)
        c.text(cx + 0.22, top + 0.28, cw - 0.44, 0.4, str(ch.get("heading", "")), 14, th.text, bold=True)
        c.text(cx + 0.22, top + 0.76, cw - 0.44, 0.7, str(ch.get("body", "")), 11.5, th.muted, line_gap=1.3)


def _r_architecture(c, th, tpl, d, box):
    x, y, w, h = box
    layers = d.get("layers") or []
    n = max(1, len(layers))
    lh = (h - 0.5 - 0.14 * (n - 1)) / n
    for i, l in enumerate(layers):
        ly = y + i * (lh + 0.14)
        c.rect(x, ly, w, lh, fill=th.surface, line=th.border, radius=0.10, alpha=0.85)
        c.rect(x, ly, 2.1, lh, fill=th.pale_blue, radius=0.10, alpha=0.95)
        c.text(x + 0.18, ly + lh / 2 - 0.30, 1.8, 0.35, str(l.get("heading", "")), 12, th.text, bold=True)
        if l.get("body"):
            c.text(x + 0.18, ly + lh / 2 + 0.02, 1.8, 0.3, str(l["body"]), 9.5, th.muted)
        items = l.get("items") or []
        if items:
            bw = (w - 2.35 - 0.16 * (len(items) - 1)) / len(items)
            for j, it in enumerate(items):
                bx = x + 2.25 + j * (bw + 0.16)
                c.rect(bx, ly + 0.22, bw, lh - 0.44, fill=th.surface_alt, line=th.border, radius=0.08, alpha=0.9)
                c.text(bx + 0.10, ly + lh / 2 - 0.14, bw - 0.20, 0.35, str(it), 10.5, th.body, align="c")
    if d.get("note"):
        c.text(x, y + h - 0.35, w, 0.35, str(d["note"]), 10.5, th.muted, align="c", italic=True)


def _r_bmc(c, th, tpl, d, box):
    x, y, w, h = box
    blocks = d.get("blocks") or []
    n = max(1, len(blocks))
    cols = 5 if n >= 9 else 3
    rows = math.ceil(n / cols)
    gap = 0.14
    cw = (w - gap * (cols - 1)) / cols
    ch = (h - gap * (rows - 1)) / rows
    accents = th.accent_cycle(n)
    for i, b in enumerate(blocks):
        cx = x + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + gap)
        c.rect(cx, cy, cw, ch, fill=th.surface, line=th.border, radius=0.08, alpha=0.88)
        c.rect(cx, cy, cw, 0.30, fill=accents[i % len(accents)], alpha=0.75)
        c.text(cx + 0.12, cy + 0.06, cw - 0.24, 0.25, str(b.get("heading", "")), 9.5, th.bg, bold=True)
        c.text(cx + 0.12, cy + 0.40, cw - 0.24, ch - 0.5, str(b.get("body", "")), 9.5, th.body, line_gap=1.25)


def _r_kanban(c, th, tpl, d, box):
    x, y, w, h = box
    columns = d.get("columns") or []
    n = max(1, len(columns))
    gap = 0.3
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    for i, col in enumerate(columns):
        cx = x + i * (cw + gap)
        c.rect(cx, y, cw, 0.58, fill=accents[i], alpha=0.85, radius=0.08)
        c.text(cx + 0.18, y + 0.15, cw - 0.9, 0.3, str(col.get("heading", "")), 12.5, th.bg, bold=True)
        c.text(cx + cw - 0.62, y + 0.15, 0.45, 0.3, str(len(col.get("cards") or [])), 12.5, th.bg,
               bold=True, align="r")
        cy = y + 0.75
        for card in col.get("cards") or []:
            c.rect(cx, cy, cw, 1.1, fill=th.surface, line=th.border, radius=0.10, alpha=0.88)
            c.text(cx + 0.18, cy + 0.16, cw - 0.36, 0.4, str(card.get("heading", "")), 12, th.text, bold=True)
            c.text(cx + 0.18, cy + 0.58, cw - 0.36, 0.4, str(card.get("note", "")), 10.5, th.muted)
            cy += 1.24


def _r_calendar(c, th, tpl, d, box):
    x, y, w, h = box
    month = str(d.get("month", ""))
    c.text(x, y, 4.0, 0.35, month, 13, th.text, bold=True)
    grid_y = y + 0.55
    cols, rows = 7, 5
    gap = 0.08
    cw = (w - gap * (cols - 1)) / cols
    ch = (h - 0.7 - gap * (rows - 1)) / rows
    days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    for j, dname in enumerate(days):
        c.text(x + j * (cw + gap), grid_y, cw, 0.28, dname, 9.5, th.muted, bold=True, align="c")
    events = {}
    for e in d.get("events") or []:
        try:
            events.setdefault(int(e.get("date", 1)), []).append(str(e.get("heading", "")))
        except Exception:
            pass
    accents = th.accent_cycle(len(events))
    for r in range(rows):
        for cidx in range(cols):
            day = r * 7 + cidx + 1
            if day > 31:
                continue
            dx = x + cidx * (cw + gap)
            dy = grid_y + 0.35 + r * (ch + gap)
            has = day in events
            c.rect(dx, dy, cw, ch, fill=th.surface if has else th.surface_alt,
                   line=th.border, radius=0.06, alpha=0.9 if has else 0.55)
            c.text(dx + 0.08, dy + 0.06, cw - 0.16, 0.25, str(day), 9.5,
                   th.accent if has else th.muted, bold=True)
            if has:
                c.text(dx + 0.08, dy + 0.30, cw - 0.16, ch - 0.36, events[day][0], 9.5, th.body, line_gap=1.2)


def _r_raci(c, th, tpl, d, box):
    x, y, w, h = box
    roles = d.get("roles") or []
    acts = d.get("activities") or []
    label_w = w * 0.40
    colw = (w - label_w) / max(1, len(roles))
    for j, r in enumerate(roles):
        c.rect(x + label_w + j * colw + 0.03, y, colw - 0.06, 0.5, fill=th.pale_blue,
               line=th.border, radius=0.08, alpha=0.9)
        c.text(x + label_w + j * colw + 0.10, y + 0.13, colw - 0.20, 0.3, str(r), 11, th.text,
               bold=True, align="c")
    rowh = min(0.62, (h - 1.25) / max(1, len(acts)))
    colors = {"R": th.accent, "A": th.red, "C": th.amber, "I": th.muted}
    for i, a in enumerate(acts):
        ry = y + 0.62 + i * rowh
        c.text(x, ry + 0.08, label_w - 0.2, 0.35, str(a.get("activity", "")), 11.5, th.text)
        for j in range(len(roles)):
            val = str((a.get("values") or [])[j] if j < len(a.get("values") or []) else "")
            c.rect(x + label_w + j * colw + 0.03, ry, colw - 0.06, rowh - 0.08,
                   fill=th.surface, line=th.border, radius=0.05, alpha=0.7)
            c.text(x + label_w + j * colw + 0.03, ry + 0.08, colw - 0.06, 0.3, val, 11,
                   colors.get(val, th.body), bold=True, align="c")
    ly = y + 0.62 + len(acts) * rowh + 0.12
    legend = [("R", "Responsible"), ("A", "Accountable"), ("C", "Consulted"), ("I", "Informed")]
    lx = x
    for code, meaning in legend:
        c.rect(lx, ly, 0.28, 0.28, fill=colors.get(code, th.muted), radius=0.05)
        c.text(lx, ly + 0.04, 0.28, 0.22, code, 9.5, th.bg, bold=True, align="c")
        c.text(lx + 0.36, ly + 0.04, 1.6, 0.25, meaning, 10, th.muted)
        lx += 2.1


def _r_anatomy(c, th, tpl, d, box):
    x, y, w, h = box
    callouts = d.get("callouts") or []
    n = max(1, len(callouts))
    cx, cy = x + w * 0.42, y + h / 2
    bw, bh = 3.6, 2.6
    c.rect(cx - bw / 2, cy - bh / 2, bw, bh, fill=th.pale_blue, line=th.accent, line_w=1.4,
           radius=0.16, alpha=0.92)
    c.text(cx - bw / 2 + 0.2, cy - 0.32, bw - 0.4, 0.7, "SYSTEM", 16, th.accent, bold=True, align="c")
    left_n = (n + 1) // 2
    right_n = n - left_n
    accents = th.accent_cycle(n)
    cw_, ch_ = 2.3, 0.86
    for i, co in enumerate(callouts):
        if i < left_n:
            row = i
            px = x
            tx = px + cw_
            anchor_x = cx - bw / 2
            py = y + 0.2 + row * ((h - 0.6) / max(1, left_n - 1) if left_n > 1 else 0)
        else:
            row = i - left_n
            px = x + w - cw_
            tx = px
            anchor_x = cx + bw / 2
            py = y + 0.2 + row * ((h - 0.6) / max(1, right_n - 1) if right_n > 1 else 0)
        # leader line from the callout to the nearest edge of the diagram
        c.line(tx if i < left_n else px, py + ch_ / 2, anchor_x, cy, th.border, 1)
        c.rect(px, py, cw_, ch_, fill=th.surface, line=accents[i % len(accents)], radius=0.10, alpha=0.9)
        c.text(px + 0.16, py + 0.10, cw_ - 0.32, 0.3, str(co.get("label", "")), 12,
               accents[i % len(accents)], bold=True)
        c.text(px + 0.16, py + 0.42, cw_ - 0.32, 0.4, str(co.get("body", "")), 10, th.muted)


def _r_risk_matrix(c, th, tpl, d, box):
    x, y, w, h = box
    px, py = x + 0.95, y + 0.15
    pw, ph = w - 1.6, h - 0.95
    c.rect(px, py, pw, ph, fill=th.surface, line=th.border, radius=0.08, alpha=0.6)
    c.line(px + pw / 2, py, px + pw / 2, py + ph, th.border, 1)
    c.line(px, py + ph / 2, px + pw, py + ph / 2, th.border, 1)
    c.text(px - 0.9, py + 0.04, 1.7, 0.3, "HIGH " + str(d.get("y_label", "")).upper(), 9.5, th.red, bold=True)
    c.text(px - 0.9, py + ph - 0.28, 1.7, 0.3, "LOW " + str(d.get("y_label", "")).upper(), 9.5, th.muted)
    c.text(px, py + ph + 0.12, pw * 0.5, 0.3, "LOW " + str(d.get("x_label", "")).upper(), 9.5, th.muted)
    c.text(px + pw / 2, py + ph + 0.12, pw / 2, 0.3, "HIGH " + str(d.get("x_label", "")).upper(),
           9.5, th.amber, bold=True, align="r")
    accents = th.accent_cycle(6)
    for i, pt in enumerate(d.get("points") or []):
        dx = max(0.03, min(0.97, num(pt.get("x", 0.5), 0.5)))
        dy = max(0.03, min(0.97, num(pt.get("y", 0.5), 0.5)))
        bx = px + dx * pw
        by = py + (1 - dy) * ph
        color = accents[i % len(accents)]
        c.ellipse(bx - 0.13, by - 0.13, 0.26, 0.26, fill=color)
        c.text(bx + 0.2, by - 0.14, 1.7, 0.3, str(pt.get("label", "")), 10.5, th.text, bold=True)


def _r_visuals(c, th, tpl, d, box):
    x, y, w, h = box
    items = d.get("items") or []
    n = max(1, len(items))
    cols = 3 if n >= 3 else n
    rows = math.ceil(n / cols)
    gap = 0.28
    cw = (w - gap * (cols - 1)) / cols
    ch = (h - 0.5 - gap * (rows - 1)) / rows
    fills = [th.pale_blue, th.pale_cyan, th.pale_green, th.pale_amber, th.pale_red, th.pale_blue]
    for i, it in enumerate(items):
        cx = x + (i % cols) * (cw + gap)
        cy = y + (i // cols) * (ch + gap)
        c.rect(cx, cy, cw, ch - 0.42, fill=fills[i % len(fills)], line=th.border, radius=0.10, alpha=0.9)
        c.text(cx + 0.15, cy + (ch - 0.42) / 2 - 0.18, cw - 0.3, 0.35, str(it.get("caption", "")),
               12, th.muted, bold=True, align="c")
        c.text(cx, cy + ch - 0.36, cw, 0.32, str(it.get("label", "")), 11.5, th.text, bold=True, align="c")


def _r_spotlight(c, th, tpl, d, box):
    x, y, w, h = box
    pw = 4.6
    c.rect(x, y, pw, h - 0.1, fill=th.pale_blue, line=th.border, radius=0.16, alpha=0.92)
    c.text(x + 0.3, y + h / 2 - 0.4, pw - 0.6, 0.8, "PRODUCT / ARTWORK", 13, th.muted,
           bold=True, align="c")
    rx = x + pw + 0.55
    rw = w - pw - 0.55
    c.text(rx, y + 0.25, rw, 0.6, str(d.get("title", "")), 24, th.text, bold=True)
    c.text(rx, y + 0.95, rw, 0.7, str(d.get("statement", "")), 15, th.accent, line_gap=1.3)
    cy = y + 1.85
    for b in d.get("bullets") or []:
        c.ellipse(rx, cy + 0.08, 0.1, 0.1, fill=th.accent)
        hh = c.text(rx + 0.26, cy, rw - 0.3, 0.4, str(b.get("heading", "")), 13.5, th.text, bold=True)
        if b.get("body"):
            c.text(rx + 0.26, cy + hh, rw - 0.3, 0.4, str(b["body"]), 11.5, th.muted)
        cy += hh + 0.62


def _r_case_study(c, th, tpl, d, box):
    x, y, w, h = box
    res = d.get("result") or {}
    c.text(x, y, 2.0, 0.3, "RESULT", 10.5, th.accent, bold=True)
    c.text(x, y + 0.32, 3.2, 0.9, str(res.get("value", "")), 40, th.accent, bold=True)
    c.text(x, y + 1.25, 3.2, 0.45, str(res.get("label", "")), 12, th.muted)
    blocks = d.get("blocks") or []
    n = max(1, len(blocks))
    gap = 0.3
    bw = (w - 3.7 - gap * (n - 1)) / n
    for i, b in enumerate(blocks):
        bx = x + 3.7 + i * (bw + gap)
        c.rect(bx, y, bw, h - 0.2, fill=th.surface, line=th.border, radius=0.14, alpha=0.88)
        c.text(bx + 0.24, y + 0.26, bw - 0.48, 0.4, str(b.get("heading", "")), 15, th.text, bold=True)
        c.rect(bx + 0.24, y + 0.80, 0.55, 0.04, fill=th.accent)
        c.text(bx + 0.24, y + 1.02, bw - 0.48, h - 1.4, str(b.get("body", "")), 12, th.body, line_gap=1.34)


def _r_image_full(c, th, tpl, d, box):
    x, y, w, h = box
    c.rect(x, y, w, h - 0.75, fill=th.surface_alt, line=th.border, radius=0.10, alpha=0.55)
    c.text(x, y + (h - 0.75) / 2 - 0.3, w, 0.6, "FULL-BLEED ARTWORK / PHOTO ZONE", 16,
           th.text, bold=True, align="c")
    c.text(x, y + h - 0.6, w, 0.4, str(d.get("caption", "")), 12, th.body)
    if d.get("source"):
        c.text(x, y + h - 0.25, w, 0.3, str(d["source"]), 10, th.muted)


def _r_image_text(c, th, tpl, d, box):
    x, y, w, h = box
    iw = w * 0.46
    c.rect(x, y, iw, h - 0.15, fill=th.pale_blue, line=th.border, radius=0.14, alpha=0.9)
    c.text(x + 0.2, y + (h - 0.15) / 2 - 0.2, iw - 0.4, 0.4, "IMAGE / ILLUSTRATION", 13,
           th.muted, bold=True, align="c")
    rx = x + iw + 0.5
    rw = w - iw - 0.5
    c.text(rx, y + 0.2, rw, 0.6, str(d.get("title", "")), 23, th.text, bold=True)
    c.bullets(rx, y + 1.05, rw - 0.1, d.get("bullets") or [], size=13.5, theme=th, gap=0.24)
    if d.get("caption"):
        c.text(rx, y + h - 0.55, rw, 0.35, str(d["caption"]), 10.5, th.muted, italic=True)


def _r_chart_insight(c, th, tpl, d, box):
    x, y, w, h = box
    cw = w * 0.66
    c.rect(x, y, cw, h - 0.1, fill=th.surface, line=th.border, radius=0.14, alpha=0.8)
    series = d.get("series") or []
    vals = [num(s.get("value", 0)) for s in series] or [1]
    mx = max(vals) or 1
    base = y + h - 0.75
    step = (cw - 0.9) / max(1, len(vals))
    c.line(x + 0.35, base, x + cw - 0.3, base, th.border, 1.25)       # zero baseline
    for i, v in enumerate(vals):
        bh = (h - 1.9) * (v / mx)
        bx = x + 0.55 + i * step
        c.rect(bx, base - bh, step * 0.52, bh,
               fill=th.accent if i == len(vals) - 1 else th.bar, alpha=1.0 if i == len(vals) - 1 else 0.55)
        if i < len(series):     # a chart without values forces the reader to guess
            c.text(bx - 0.1, base - bh - 0.32, step * 0.72, 0.28, str(series[i].get("value", "")), 11,
                   th.text, bold=True, align="c")
        c.text(bx - 0.1, base + 0.08, step * 0.72, 0.3, str(series[i].get("label", "")), 10,
               th.muted, align="c")
    px = x + cw + 0.35
    pw = w - cw - 0.35
    c.rect(px, y, pw, h - 0.1, fill=th.pale_blue, line=th.border, radius=0.14, alpha=0.92)
    c.text(px + 0.26, y + 0.3, pw - 0.52, 0.3, "KEY INSIGHT", 11, th.accent, bold=True)
    c.text(px + 0.26, y + 0.75, pw - 0.52, 1.6, str(d.get("insight", "")), 18, th.text,
           bold=True, line_gap=1.26)
    c.bullets(px + 0.26, y + 2.45, pw - 0.5, d.get("bullets") or [], size=11.5, theme=th, gap=0.1)
    if d.get("source"):
        c.text(px + 0.26, y + h - 0.55, pw - 0.52, 0.35, str(d["source"]), 9.5, th.muted)


def _r_financial(c, th, tpl, d, box):
    x, y, w, h = box
    hl = d.get("headline") or {}
    c.text(x, y, 4.0, 0.3, "HEADLINE", 10.5, th.accent, bold=True)
    c.text(x, y + 0.3, 4.4, 1.0, str(hl.get("value", "")), 46, th.text, bold=True)
    c.text(x, y + 1.35, 4.4, 0.4, str(hl.get("label", "")), 14, th.muted)
    c.text(x, y + 1.80, 4.4, 0.3, str(d.get("period", "")), 11, th.muted, italic=True)
    items = d.get("breakdown") or []
    n = max(1, len(items))
    gap = 0.3
    cw = (w - 4.9 - gap * (n - 1)) / n
    total = sum(num(i.get("value", 0)) for i in items) or 1
    for i, it in enumerate(items):
        cx = x + 4.9 + i * (cw + gap)
        v = num(it.get("value", 0))
        bh = (h - 0.6) * (v / total)
        c.rect(cx, y + (h - 0.6) - bh, cw, bh, fill=th.pale_blue if i else th.accent)
        c.text(cx, y + (h - 0.6) - bh - 0.32, cw, 0.3, str(it.get("value", "")), 11, th.text,
               bold=True, align="c")
        c.text(cx, y + (h - 0.3), cw, 0.3, str(it.get("label", "")), 10, th.muted, align="c")


def _r_waterfall(c, th, tpl, d, box):
    x, y, w, h = box
    steps = list(d.get("steps") or [])
    total = d.get("total", "")
    if total:
        steps = steps + [{"label": "End", "value": str(total)}]
    n = max(1, len(steps))
    base_y = y + h - 0.75
    levels = []
    running = 1.6
    for i, s in enumerate(steps):
        label = str(s.get("label", ""))
        if i == 0:
            start, end = 0.0, running
        elif i == n - 1:
            start, end = 0.0, running
        else:
            delta = {"+": 0.55, "-": -0.55}.get(label[:1], 0.4)
            start, end = running, running + delta
            running = end
        levels.append((start, end))
    top = max(max(a, b) for a, b in levels) or 1
    scale = (h - 1.9) / top
    slot = (w - 0.4) / n
    for i, s in enumerate(steps):
        start, end = levels[i]
        lo, hi = min(start, end), max(start, end)
        bh = max(0.12, (hi - lo) * scale)
        sx = x + 0.2 + i * slot
        sy = base_y - hi * scale
        label = str(s.get("label", ""))
        color = th.accent_solid if i in (0, n - 1) else (th.green if "+" in label else th.red)
        c.rect(sx, sy, slot * 0.55, bh, fill=color)
        c.text(sx - 0.2, base_y + 0.12, slot * 0.95, 0.3, label, 10, th.text, bold=True, align="c")
        if i < n - 1:
            c.line(sx + slot * 0.55, sy + (bh if end > start else 0),
                   sx + slot, sy + (bh if end > start else 0), th.muted, 1)
    c.rect(x, base_y, w - 0.2, 0.02, fill=th.muted)


def _r_geo(c, th, tpl, d, box):
    x, y, w, h = box
    pw = w * 0.55
    c.rect(x, y, pw, h - 0.1, fill=th.pale_blue, line=th.border, radius=0.14, alpha=0.9)
    c.text(x + 0.3, y + (h - 0.1) / 2 - 0.3, pw - 0.6, 0.6, "VISUAL / REGIONAL BREAKDOWN", 13,
           th.muted, bold=True, align="c")
    rx = x + pw + 0.5
    rw = w - pw - 0.5
    c.text(rx, y + 0.15, rw, 0.5, str(d.get("headline", "")), 19, th.text, bold=True)
    regions = d.get("regions") or []
    ry = y + 0.85
    mx = 0
    for r in regions:
        mx = max(mx, num(r.get("value", 0)))
    for i, r in enumerate(regions):
        c.text(rx, ry, rw * 0.6, 0.3, str(r.get("name", "")), 12, th.text)
        c.text(rx + rw * 0.6, ry, rw * 0.4, 0.3, str(r.get("value", "")), 12, th.accent, bold=True, align="r")
        v = num(r.get("value", 0))
        c.rect(rx, ry + 0.34, rw, 0.12, fill=th.surface_alt, radius=0.05)
        c.rect(rx, ry + 0.34, rw * (v / mx if mx else 0.5), 0.12, fill=th.accent, radius=0.05)
        ry += 0.75
    if d.get("source"):
        c.text(rx, y + h - 0.45, rw, 0.3, str(d["source"]), 10, th.muted)


def _r_table(c, th, tpl, d, box):
    x, y, w, h = box
    headers = d.get("headers") or []
    rows = d.get("rows") or []
    ncol = max(1, len(headers))
    rowh = min(0.55, (h - 0.1) / max(1, len(rows) + 1))
    c.rect(x, y, w, rowh, fill=th.surface_alt, radius=0.06, alpha=0.95)
    for j, hd in enumerate(headers):
        c.text(x + 0.18 + j * (w / ncol), y + rowh / 2 - 0.13, w / ncol - 0.2, 0.3, str(hd),
               11.5, th.text, bold=True)
    for i, row in enumerate(rows):
        ry = y + rowh + i * rowh
        c.rect(x, ry, w, rowh, fill=th.surface if i % 2 == 0 else th.surface_alt, alpha=0.55)
        for j in range(ncol):
            val = str(row[j]) if j < len(row) else ""
            c.text(x + 0.18 + j * (w / ncol), ry + rowh / 2 - 0.13, w / ncol - 0.2, 0.3, val,
                   11.5, th.body)
        c.line(x, ry + rowh, x + w, ry + rowh, th.border, 0.75)


def _r_progress(c, th, tpl, d, box):
    x, y, w, h = box
    items = d.get("items") or []
    n = max(1, len(items))
    rowh = min(0.9, (h - 0.1) / n)
    for i, it in enumerate(items):
        ry = y + i * rowh
        c.text(x, ry + 0.04, w * 0.55, 0.3, str(it.get("label", "")), 13, th.text, bold=True)
        c.text(x + w * 0.55, ry + 0.06, w * 0.45, 0.3, str(it.get("note", "")), 11, th.muted, align="r")
        c.rect(x, ry + 0.46, w, 0.18, fill=th.surface_alt, radius=0.08)
        try:
            v = max(0, min(100, num(it.get("value", 0))))
        except Exception:
            v = 0
        c.rect(x, ry + 0.46, w * v / 100.0, 0.18, fill=th.accent, radius=0.08)
        c.text(x + w - 0.8, ry + 0.42, 0.8, 0.28, f"{int(v)}%", 11, th.accent2, bold=True, align="r")


def _r_heatmap(c, th, tpl, d, box):
    x, y, w, h = box
    cols = d.get("cols") or []
    rows = d.get("rows") or []
    label_w = w * 0.22
    ncol = max(1, len(cols))
    nrow = max(1, len(rows))
    cw = (w - label_w) / ncol
    ch = (h - 0.55) / nrow
    for j, cn in enumerate(cols):
        c.text(x + label_w + j * cw, y, cw, 0.3, str(cn), 10.5, th.muted, bold=True, align="c")
    for i, r in enumerate(rows):
        ry = y + 0.45 + i * ch
        c.text(x, ry + ch / 2 - 0.14, label_w - 0.15, 0.3, str(r.get("label", "")), 11, th.text)
        vals = r.get("values") or []
        for j in range(ncol):
            v = vals[j] if j < len(vals) else 0
            try:
                v = max(0.0, min(1.0, num(v)))
            except Exception:
                v = 0
            c.rect(x + label_w + j * cw + 0.03, ry + 0.03, cw - 0.06, ch - 0.09,
                   fill=th.accent, alpha=0.12 + 0.72 * v, radius=0.05)
            c.text(x + label_w + j * cw + 0.03, ry + ch / 2 - 0.13, cw - 0.06, 0.28,
                   f"{v:.0%}", 10, th.text if v < 0.6 else th.bg, bold=True, align="c")


def _r_scatter(c, th, tpl, d, box):
    x, y, w, h = box
    px, py, pw, ph = x + 0.6, y + 0.25, w - 1.0, h - 1.0
    c.rect(px, py, pw, ph, fill=th.surface, line=th.border, radius=0.10, alpha=0.6)
    c.line(px + pw / 2, py, px + pw / 2, py + ph, th.border, 1)
    c.line(px, py + ph / 2, px + pw, py + ph / 2, th.border, 1)
    c.text(px, py + ph + 0.12, pw, 0.3, str(d.get("x_label", "")), 10, th.muted, bold=True, align="c")
    c.text(px - 0.1, py - 0.3, 2.2, 0.3, str(d.get("y_label", "")), 10, th.muted, bold=True)
    accents = th.accent_cycle(6)
    for i, pt in enumerate(d.get("points") or []):
        dx = max(0.02, min(0.98, num(pt.get("x", 0.5), 0.5)))
        dy = max(0.02, min(0.98, num(pt.get("y", 0.5), 0.5)))
        bx = px + dx * pw
        by = py + (1 - dy) * ph
        c.ellipse(bx - 0.12, by - 0.12, 0.24, 0.24, fill=accents[i % len(accents)])
        c.text(bx + 0.16, by - 0.13, 1.2, 0.28, str(pt.get("label", "")), 10, th.body)


def _r_stacked(c, th, tpl, d, box):
    x, y, w, h = box
    segs = d.get("segments") or []
    total = sum(num(s.get("value", 0)) for s in segs) or 1
    by = y + 0.9
    bh = 1.15
    cx = x
    accents = th.accent_cycle(len(segs))
    for i, s in enumerate(segs):
        v = num(s.get("value", 0))
        sw = w * v / total
        c.rect(cx, by, sw, bh, fill=accents[i % len(accents)], alpha=0.9)
        c.text(cx + 0.12, by + bh / 2 - 0.14, sw - 0.24, 0.3, f"{v / total * 100:.0f}%", 13,
               th.bg, bold=True, align="c")
        cx += sw
    ly = by + bh + 0.45
    lx = x
    for i, s in enumerate(segs):
        c.rect(lx, ly + 0.05, 0.16, 0.16, fill=accents[i % len(accents)], radius=0.04)
        c.text(lx + 0.26, ly, 2.4, 0.3, str(s.get("label", "")), 11.5, th.body)
        lx += 2.75
    if d.get("total"):
        c.text(x + w - 2.2, y + 0.2, 2.0, 0.5, str(d["total"]), 26, th.accent, bold=True, align="r")


def _r_sources(c, th, tpl, d, box):
    x, y, w, h = box
    c.text(x, y, 6.0, 0.35, "SOURCES & EVIDENCE", 11.5, th.accent, bold=True)
    items = d.get("sources") or []
    n = max(1, len(items))
    rowh = min(0.8, (h - 0.5) / n)
    for i, s in enumerate(items):
        ry = y + 0.55 + i * rowh
        c.ellipse(x + 0.05, ry + 0.10, 0.11, 0.11, fill=th.accent)
        c.text(x + 0.30, ry, w - 0.4, 0.32, str(s.get("name", "")), 13, th.text, bold=True)
        c.text(x + 0.30, ry + 0.34, w - 0.4, 0.4, str(s.get("detail", "")), 11.5, th.muted)


def _r_appendix(c, th, tpl, d, box):
    x, y, w, h = box
    rows = d.get("rows") or []
    n = max(1, len(rows))
    rowh = min(0.7, (h - 0.1) / n)
    for i, r in enumerate(rows):
        ry = y + i * rowh
        c.text(x, ry + 0.04, 1.4, 0.3, str(r.get("code", "")), 11, th.accent, bold=True)
        c.text(x + 1.6, ry + 0.04, w - 1.7, 0.4, str(r.get("text", "")), 12, th.text)
        c.line(x, ry + rowh - 0.1, x + w, ry + rowh - 0.1, th.border, 0.75)


def _r_pricing(c, th, tpl, d, box):
    x, y, w, h = box
    tiers = d.get("tiers") or []
    n = max(1, len(tiers))
    gap = 0.34
    cw = (w - gap * (n - 1)) / n
    for i, t in enumerate(tiers):
        cx = x + i * (cw + gap)
        featured = (i == n // 2)
        c.rect(cx, y - (0.2 if featured else 0), cw, h - 0.05 + (0.2 if featured else 0),
               fill=th.pale_blue if featured else th.surface, line=th.accent if featured else th.border,
               line_w=1.6 if featured else 1.0, radius=0.14, alpha=0.92)
        c.text(cx + 0.28, y + 0.25, cw - 0.56, 0.4, str(t.get("name", "")), 16, th.text, bold=True)
        c.text(cx + 0.28, y + 0.72, cw - 0.56, 0.6, str(t.get("price", "")), 28, th.accent, bold=True)
        if featured:
            c.rect(cx + cw - 1.35, y + 0.12, 1.1, 0.3, fill=th.accent, radius=0.15)
            c.text(cx + cw - 1.35, y + 0.17, 1.1, 0.25, "POPULAR", 8.5, th.bg, bold=True, align="c")
        c.bullets(cx + 0.28, y + 1.55, cw - 0.5, t.get("features") or [], size=12, theme=th, gap=0.12)


KIND_RENDERERS = {
    "title_slide": _r_title_slide, "outro": _r_outro, "section_divider": _r_section_divider,
    "agenda": None, "bullets": _r_bullets, "cards": _r_cards, "panels": _r_panels,
    "two_panel": _r_two_panel, "pso": _r_pso, "editorial": _r_editorial,
    "checklist": _r_checklist, "icon_strip": _r_icon_strip, "triptych": _r_triptych,
    "quote": _r_quote, "quote_evidence": _r_quote_evidence, "big_statement": _r_big_statement,
    "metrics": _r_metrics, "metric_band": _r_metric_band, "scorecard": _r_scorecard,
    "numbered_row": _r_numbered_row, "numbered_stack": _r_numbered_stack,
    "timeline": _r_timeline, "swimlane": _r_swimlane, "journey": _r_journey,
    "cycle": _r_cycle, "funnel": _r_funnel, "quad": _r_quad, "swot": _r_swot,
    "pyramid": _r_pyramid, "layers": _r_layers, "hub_spoke": _r_hub_spoke,
    "decision": _r_decision, "ranking": _r_ranking, "faq": _r_faq,
    "feature_matrix": _r_feature_matrix, "personas": _r_personas,
    "persona_cards": _r_persona_cards, "directory": _r_directory,
    "hierarchy": _r_hierarchy, "architecture": _r_architecture, "bmc": _r_bmc,
    "kanban": _r_kanban, "retro": _r_retro, "calendar": _r_calendar, "raci": _r_raci,
    "anatomy": _r_anatomy, "spotlight": _r_spotlight, "case_study": _r_case_study,
    "image_full": _r_image_full, "image_text": _r_image_text, "visuals": _r_visuals,
    "risk_matrix": _r_risk_matrix,
    "chart_insight": _r_chart_insight, "financial": _r_financial, "waterfall": _r_waterfall,
    "geo": _r_geo, "table": _r_table, "progress": _r_progress, "heatmap": _r_heatmap,
    "scatter": _r_scatter, "stacked": _r_stacked, "sources": _r_sources,
    "appendix": _r_appendix, "pricing": _r_pricing,
}


def _r_agenda(c, th, tpl, d, box):
    x, y, w, h = box
    items = d.get("items") or []
    n = max(1, len(items))
    rowh = min(0.85, (h - 0.1) / n)
    for i, it in enumerate(items):
        ry = y + i * rowh
        c.text(x + 0.2, ry + 0.02, 0.8, 0.4, f"{i + 1:02d}", 16, th.accent, bold=True)
        c.text(x + 1.2, ry + 0.02, w * 0.55, 0.4, str(it.get("heading", "")), 17,
               th.text if i == 0 else th.body, bold=(i == 0))
        if it.get("note"):
            c.text(x + w * 0.62, ry + 0.06, w * 0.38, 0.35, str(it["note"]), 11.5, th.muted, align="r")
        c.line(x + 1.2, ry + 0.60, x + w, ry + 0.60, th.border, 1)


KIND_RENDERERS["agenda"] = _r_agenda


# --------------------------------------------------------------------------------------
# Layouts added in the design review (L65-L68)
# --------------------------------------------------------------------------------------

def _r_executive_summary(c, th, tpl, d, box):
    x, y, w, h = box
    hh = c.text(x, y, min(w, 11.2), 1.0, str(d.get("headline", "")), 24, th.text, bold=True, line_gap=1.2)
    y += max(hh, estimate_text_height(d.get("headline", ""), 24, min(w, 11.2), 1.2), 0.5) + 0.4
    items = d.get("findings") or []
    n = max(1, len(items))
    gap = 0.28
    cw = (w - gap * (n - 1)) / n
    accents = th.accent_cycle(n)
    detail_h = max([estimate_text_height(it.get("detail"), 12.5, cw - 0.44) for it in items] or [0.4])
    ch = min(2.4, 0.26 + 0.62 + 0.4 + max(detail_h, 0.5) + 0.2)
    for i, it in enumerate(items):
        cx = x + i * (cw + gap)
        c.rect(cx, y, cw, ch, fill=th.surface, line=th.border, radius=0.12, alpha=0.86)
        c.rect(cx, y, cw, 0.06, fill=accents[i])
        c.text(cx + 0.22, y + 0.26, cw - 0.44, 0.6, str(it.get("number", "")), 30, accents[i], bold=True)
        c.text(cx + 0.22, y + 0.90, cw - 0.44, 0.35, str(it.get("label", "")), 14, th.text, bold=True)
        c.text(cx + 0.22, y + 1.30, cw - 0.44, ch - 1.4, str(it.get("detail", "")), 12.5, th.body, line_gap=1.3)
    rec = str(d.get("recommendation", "")).strip()
    if rec:
        ry = y + ch + 0.3
        rh = max(0.85, min(CONTENT_BOTTOM - ry, 0.5 + estimate_text_height(rec, 15, w - 0.7)))
        c.rect(x, ry, w, rh, fill=th.pale_blue, line=th.accent, radius=0.12, alpha=0.95)
        c.rect(x, ry, 0.09, rh, fill=th.accent)
        c.text(x + 0.35, ry + 0.14, 4.0, 0.25, "RECOMMENDATION", 10, th.accent, bold=True)
        c.text(x + 0.35, ry + 0.42, w - 0.7, rh - 0.5, rec, 15, th.text, bold=True, line_gap=1.25)


def _r_venn(c, th, tpl, d, box):
    x, y, w, h = box
    circles = (d.get("circles") or [])[:3]
    n = max(2, len(circles))
    accents = th.accent_cycle(n)
    cx0 = x + w * 0.29
    cy0 = y + h * 0.5
    if n == 2:
        r = 1.55
        centres = [(cx0 - 0.95, cy0), (cx0 + 0.95, cy0)]
        label_at = [(cx0 - 1.65, cy0), (cx0 + 1.65, cy0)]
        ov_at = (cx0, cy0)
    else:
        r = 1.45
        centres = [(cx0, cy0 - 0.85), (cx0 - 1.0, cy0 + 0.8), (cx0 + 1.0, cy0 + 0.8)]
        label_at = [(cx0, cy0 - 1.55), (cx0 - 1.55, cy0 + 1.25), (cx0 + 1.55, cy0 + 1.25)]
        ov_at = (cx0, cy0 + 0.25)
    for i in range(n):
        ccx, ccy = centres[i]
        c.ellipse(ccx - r, ccy - r, 2 * r, 2 * r, fill=accents[i], line=accents[i], alpha=0.30, line_w=2)
    for i, it in enumerate(circles[:n]):
        lx, ly = label_at[i]
        c.text(lx - 0.8, ly - 0.3, 1.6, 0.6, str(it.get("label", "")), 14, th.text, bold=True,
               align="c", valign="m", line_gap=1.1)
    c.text(ov_at[0] - 0.55, ov_at[1] - 0.3, 1.1, 0.6, str(d.get("overlap", "")), 11, th.text, bold=True,
           align="c", valign="m", line_gap=1.1)
    # legend: explains each circle and the overlap, so meaning never depends on colour alone
    lx = x + w * 0.62
    lw = w * 0.38
    ly = y + 0.3
    for i, it in enumerate(circles[:n]):
        c.ellipse(lx, ly + 0.07, 0.2, 0.2, fill=accents[i])
        c.text(lx + 0.38, ly, lw - 0.4, 0.3, str(it.get("label", "")), 15, th.text, bold=True)
        nh = c.text(lx + 0.38, ly + 0.36, lw - 0.4, 0.5, str(it.get("note", "")), 12.5, th.body, line_gap=1.3)
        ly += 0.36 + max(nh, 0.3) + 0.3
    c.line(lx, ly, lx + lw, ly, th.border, 1)
    ly += 0.22
    c.text(lx, ly, lw, 0.3, "WHERE THEY MEET", 10, th.accent, bold=True)
    c.text(lx, ly + 0.32, lw, 0.4, str(d.get("overlap", "")), 16, th.text, bold=True)
    if d.get("overlap_note"):
        c.text(lx, ly + 0.76, lw, 0.9, str(d["overlap_note"]), 12.5, th.body, line_gap=1.3)


def _nice_max(v):
    if v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def _fmt_val(v, unit=""):
    a = abs(v)
    if a >= 1_000_000:
        t = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    elif a >= 10_000:
        t = f"{v / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    elif a >= 100 or float(v).is_integer():
        t = f"{v:,.0f}"
    else:
        t = f"{v:.1f}".rstrip("0").rstrip(".")
    return t + (unit or "")


def _r_line_chart(c, th, tpl, d, box):
    x, y, w, h = box
    pts = d.get("points") or []
    labels = [str(p.get("label", "")) for p in pts]
    vals = [num(p.get("value", 0)) for p in pts] or [0.0]
    unit = str(d.get("unit", "") or "")
    cw = w * 0.66
    c.rect(x, y, cw, h - 0.1, fill=th.surface, line=th.border, radius=0.14, alpha=0.8)
    hi = _nice_max(max(vals)) if max(vals) > 0 else 0.0
    lo = -_nice_max(-min(vals)) if min(vals) < 0 else 0.0
    if hi <= lo:
        hi = lo + 1.0
    left, right = x + 1.05, x + cw - 0.45
    top, bottom = y + 0.6, y + h - 0.95
    for k in range(5):                                     # gridlines + y-axis values
        gv = lo + (hi - lo) * k / 4.0
        gy = bottom - (bottom - top) * k / 4.0
        c.line(left, gy, right, gy, th.border, 0.75 if k else 1.25, alpha=0.9)
        c.text(x + 0.15, gy - 0.12, 0.78, 0.25, _fmt_val(gv, unit if k == 4 else ""), 10, th.muted, align="r")
    n = len(vals)
    xs = [left + (right - left) * (i / max(1, n - 1)) for i in range(n)]
    ys = [bottom - (v - lo) / (hi - lo) * (bottom - top) for v in vals]
    for i in range(n - 1):
        c.line(xs[i], ys[i], xs[i + 1], ys[i + 1], th.accent, 3.0)
    every = 1 if n <= 8 else 2
    peak = vals.index(max(vals))
    for i in range(n):
        last = i == n - 1
        r = 0.09 if last else 0.065
        c.ellipse(xs[i] - r, ys[i] - r, 2 * r, 2 * r, fill=th.accent2 if last else th.accent)
        if last or i == 0 or i == peak:                    # label start, peak and end - not every point
            c.text(xs[i] - 0.6, ys[i] - 0.36, 1.2, 0.26, _fmt_val(vals[i], unit), 11, th.text, bold=True, align="c")
        if i % every == 0 or last:
            c.text(xs[i] - 0.5, bottom + 0.12, 1.0, 0.26, labels[i] if i < len(labels) else "", 10, th.muted, align="c")
    px = x + cw + 0.35
    pw = w - cw - 0.35
    c.rect(px, y, pw, h - 0.1, fill=th.pale_blue, line=th.border, radius=0.14, alpha=0.92)
    c.text(px + 0.26, y + 0.3, pw - 0.52, 0.3, "KEY INSIGHT", 11, th.accent, bold=True)
    c.text(px + 0.26, y + 0.75, pw - 0.52, 2.4, str(d.get("insight", "")), 18, th.text, bold=True, line_gap=1.26)
    if n >= 2 and vals[0]:
        chg = (vals[-1] - vals[0]) / abs(vals[0]) * 100
        c.text(px + 0.26, y + h - 1.55, pw - 0.52, 0.5, f"{chg:+.0f}%", 28, th.accent2, bold=True)
        c.text(px + 0.26, y + h - 1.0, pw - 0.52, 0.3, f"{labels[0]} to {labels[-1]}", 11, th.muted)
    if d.get("source"):
        c.text(px + 0.26, y + h - 0.5, pw - 0.52, 0.3, str(d["source"]), 10, th.muted)


_STATUS_STYLE = (
    (("done", "complete", "shipped"), "green"),
    (("on track", "on-track", "green", "progress"), "green"),
    (("risk", "delay", "behind", "slip", "watch"), "amber"),
    (("block", "late", "overdue", "red", "fail"), "red"),
)


def _status_colour(th, status):
    s = str(status or "").lower()
    for words, name in _STATUS_STYLE:
        if any(wd in s for wd in words):
            return getattr(th, name)
    return th.muted


def _r_action_plan(c, th, tpl, d, box):
    x, y, w, h = box
    y += draw_intro(c, th, d, (x, y, w, 0.5))
    rows = d.get("actions") or []
    n = max(1, len(rows))
    cols = [x + 0.2, x + w * 0.52, x + w * 0.70, x + w * 0.82]
    headers = ("ACTION", "OWNER", "DUE", "STATUS")
    hdr_h = 0.46
    c.rect(x, y, w, hdr_h, fill=th.surface_alt, radius=0.06, alpha=0.95)
    for cx, hd in zip(cols, headers):
        c.text(cx, y + 0.13, 2.0, 0.25, hd, 10, th.muted, bold=True)
    avail = CONTENT_BOTTOM - (y + hdr_h)
    rh = min(0.78, avail / n)
    for i, r in enumerate(rows):
        ry = y + hdr_h + i * rh
        c.rect(x, ry, w, rh, fill=th.surface if i % 2 == 0 else th.surface_alt, alpha=0.55)
        c.text(cols[0], ry, w * 0.52 - 0.45, rh, str(r.get("action", "")), 13.5, th.text, valign="m", line_gap=1.2)
        c.text(cols[1], ry, w * 0.18 - 0.2, rh, str(r.get("owner", "")), 12.5, th.body, valign="m")
        c.text(cols[2], ry, w * 0.12 - 0.15, rh, str(r.get("due", "")), 12.5, th.body, valign="m")
        col = _status_colour(th, r.get("status"))
        pw_, ph_ = min(1.6, x + w - cols[3] - 0.15), 0.34
        c.rect(cols[3], ry + (rh - ph_) / 2, pw_, ph_, fill=col, line=col, radius=0.17, alpha=0.22, line_w=1.0)
        c.text(cols[3], ry + (rh - ph_) / 2, pw_, ph_, str(r.get("status", "")), 11, col, bold=True,
               align="c", valign="m")
        c.line(x, ry + rh, x + w, ry + rh, th.border, 0.75)


KIND_RENDERERS["executive_summary"] = _r_executive_summary
KIND_RENDERERS["venn"] = _r_venn
KIND_RENDERERS["line_chart"] = _r_line_chart
KIND_RENDERERS["action_plan"] = _r_action_plan



# --------------------------------------------------------------------------------------
# Top level rendering
# --------------------------------------------------------------------------------------

DARK_KINDS = {"title_slide", "outro", "section_divider"}


def render_template(canvas: Canvas, template: Template, data: Dict[str, Any],
                    theme: Optional[Theme] = None, number: Optional[int] = None,
                    background: Optional[str] = None):
    """Draw one layout (with its structured content) onto a canvas."""
    th = theme or DARK_THEME
    tpl = template if isinstance(template, Template) else get_template(template)
    if tpl is None:
        tpl = Template("L02", "Standard Content", "Core content", "bullets", "", "", "")
    data = data or {}

    if background and os.path.exists(background):
        # Preserve the generated artwork as-is. Do not blur or darken it globally;
        # individual layouts already position text and panels to maintain readability.
        canvas.image(background, 0, 0, SLIDE_W, SLIDE_H, mode="cover", alt="Decorative background artwork")
        dense = tpl.kind not in DARK_KINDS
        if th.dark:
            # bright artwork gets a stronger scrim so body text keeps its contrast
            canvas.rect(0, 0, SLIDE_W, SLIDE_H, fill="#05070D", alpha=background_scrim(th, background, dense))
        else:
            # light theme: dark text on busy artwork is unreadable without a pale veil
            canvas.rect(0, 0, SLIDE_W, SLIDE_H, fill="#FFFFFF", alpha=0.90 if dense else 0.78)
    else:
        canvas.rect(0, 0, SLIDE_W, SLIDE_H, fill=th.bg)
    canvas.finish_background()

    kind = tpl.kind
    if kind in DARK_KINDS:
        box = (LEFT, 1.1, CONTENT_W, SLIDE_H - 1.6)
    else:
        draw_header(canvas, th, tpl, data, number)
        box = (LEFT, CONTENT_TOP, CONTENT_W, CONTENT_H)

    renderer = KIND_RENDERERS.get(kind, _r_bullets)
    renderer(canvas, th, tpl, data, box)

    # A consistent, unobtrusive citation footer is drawn on researched slides,
    # independent of the selected layout kind. Sources are readable in both PNG
    # previews and editable PowerPoint output.
    source_footer = str(data.get("source_footer", "") or "").strip()
    if source_footer:
        if len(source_footer) > 235:
            source_footer = source_footer[:232].rstrip(" ;,.") + "..."
        canvas.line(LEFT, 7.13, RIGHT, 7.13, th.border, 0.6, alpha=0.8)
        canvas.text(LEFT, 7.15, CONTENT_W, 0.24, source_footer,
                    size=MIN_FONT_PT, color=th.muted, align="l", valign="m")

    # Speaker notes carry the detail the slide had to leave out (plus the sources).
    notes = str(data.get("notes", "") or "").strip()
    if source_footer:
        notes = (notes + "\n\n" if notes else "") + source_footer
    if notes:
        canvas.notes(notes)
    canvas.finalize()
    return canvas


def render_to_pptx(template: Template, data: Dict[str, Any], out_path: str,
                    background: Optional[str] = None, theme: Optional[Theme] = None,
                    number: Optional[int] = None) -> str:
    """Write a single slide (native shapes) to a .pptx file."""
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    slide = prs.slides.add_slide(prs.slide_layouts[5])      # "Title Only": gives the slide a real title
    canvas = PptxCanvas(prs, slide)
    render_template(canvas, template, data, theme=theme, number=number, background=background)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    prs.save(out_path)
    return out_path


def render_to_png(template: Template, data: Dict[str, Any], out_path: str,
                  background: Optional[str] = None, theme: Optional[Theme] = None,
                  number: Optional[int] = None, dpi: int = 110) -> str:
    """Write a PNG preview of a slide."""
    th = theme or DARK_THEME
    canvas = PilCanvas(SLIDE_W, SLIDE_H, dpi=dpi, theme=th)
    render_template(canvas, template, data, theme=th, number=number, background=background)
    canvas.save(out_path)
    return out_path


def build_deck_pptx(slides: Sequence[Tuple[Template, Dict[str, Any]]], out_path: str,
                    backgrounds: Optional[Sequence[Optional[str]]] = None,
                    theme: Optional[Theme] = None) -> str:
    """Build a multi-slide deck, one slide per (template, content) pair."""
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    blank = prs.slide_layouts[5]      # "Title Only": gives every slide a real title placeholder
    th = theme or DARK_THEME
    for i, (tpl, data) in enumerate(slides):
        slide = prs.slides.add_slide(blank)
        bg = backgrounds[i] if backgrounds and i < len(backgrounds) else None
        render_template(PptxCanvas(prs, slide), tpl, data, theme=th, number=i + 1, background=bg)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    prs.save(out_path)
    return out_path
