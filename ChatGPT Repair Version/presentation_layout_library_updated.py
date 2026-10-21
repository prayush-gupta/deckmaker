"""
Presentation Layout Archetype Library
=====================================
A data-driven PowerPoint template catalogue and visual specimen deck.

Requirements:
    pip install python-pptx

Run:
    python presentation_layout_library.py
    python presentation_layout_library.py --output my_layouts.pptx --summary layout_catalog.md

Notes:
- Layouts are editable native PowerPoint shapes and text, not flattened screenshots.
- Sample copy and data are illustrative placeholders; replace them with slide-specific content.
- The catalogue is intentionally separate from rendering so an AI slide planner can select
  layouts by ID, name, purpose, content pattern, and implementation notes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

def hx(value: int) -> RGBColor:
    """Convert a 24-bit hexadecimal color to python-pptx RGBColor."""
    return RGBColor((value >> 16) & 255, (value >> 8) & 255, value & 255)


WIDE_WIDTH = Inches(13.333)
WIDE_HEIGHT = Inches(7.5)
FONT = "Aptos"

C = {
    "dark": RGBColor(0x11, 0x18, 0x27),       # Obsidian slate
    "dark2": RGBColor(0x1F, 0x2A, 0x3D),
    "light": RGBColor(0xF8, 0xFA, 0xFC),      # Off-white canvas
    "white": RGBColor(0xFF, 0xFF, 0xFF),
    "accent": RGBColor(0x25, 0x63, 0xEB),     # Cobalt
    "accent2": RGBColor(0x06, 0xB6, 0xD4),    # Cyan
    "green": RGBColor(0x10, 0xB9, 0x81),
    "amber": RGBColor(0xF5, 0x9E, 0x0B),
    "red": RGBColor(0xEF, 0x44, 0x44),
    "text": RGBColor(0x37, 0x41, 0x51),
    "muted": RGBColor(0x6B, 0x72, 0x80),
    "border": RGBColor(0xE2, 0xE8, 0xF0),
    "pale_blue": hx(0xEAF1FF),
    "pale_cyan": hx(0xE6FAFD),
    "pale_green": hx(0xE7F8F0),
    "pale_amber": hx(0xFFF5DF),
    "pale_red": hx(0xFEECEC),
}

# Consistent 16:9 canvas margins and content bounds.
LEFT = 0.82
RIGHT = 12.51
CONTENT_TOP = 1.85
CONTENT_BOTTOM = 6.78


@dataclass(frozen=True)
class Layout:
    id: str
    name: str
    family: str
    best_for: str
    implementation: str
    content_pattern: str
    density: str = "medium"
    image_strategy: str = "Optional; use only when it adds evidence or context."


# Keep these IDs stable: they are suitable for an AI planner or JSON layout index.
LAYOUTS: list[Layout] = [
    Layout("L01", "Modern Title", "Opening / closing", "Open a presentation with one clear promise.", "Dark full-bleed canvas, large left-aligned title, short subtitle, restrained accent rule.", "title + subtitle + optional presenter/date", "low"),
    Layout("L02", "Standard Content", "Core content", "Explain one idea with a short narrative and supporting points.", "Editorial title band, readable body copy, clear bullet hierarchy and generous line spacing.", "title + paragraph + 3–5 bullets", "medium"),
    Layout("L03", "3-Column Card Grid", "Core content", "Present three parallel pillars, features, or options.", "Three equal cards, numbered eyebrow, consistent gutters, short headings and compact descriptions.", "three equivalent items", "medium", "Optional icon per card"),
    Layout("L04", "Split Frame Hero", "Core content", "Pair a strong focal statement with supporting explanation.", "Asymmetric 35/65 split, saturated accent panel, contrasting editorial content area.", "focal phrase + title + paragraph", "low", "Optional artwork in focal panel"),
    Layout("L05", "Big Numbers Metric", "Data / evidence", "Emphasize two to four headline KPIs.", "Large numeric values, concise labels, subtle dividers and a shared baseline.", "2–4 metric/value/label triples", "low"),
    Layout("L06", "Timeline Flow", "Process / sequence", "Show milestones in chronological order.", "Explicit horizontal axis, evenly spaced nodes, alternating labels above/below axis.", "3–6 dated milestones", "medium"),
    Layout("L07", "Data Grid Table", "Data / evidence", "Compare structured values across rows and columns.", "Strong header row, subtle row banding, aligned numeric columns, restrained borders.", "table headers + records", "high"),
    Layout("L08", "Two-Column Contrast", "Comparison", "Compare alternatives, current/future states, or pros/cons.", "Two balanced panels with contrasting headings, aligned bullet groups and visible separation.", "left option + right option", "medium"),
    Layout("L09", "Key Callout / Quote", "Emphasis", "Highlight a thesis, customer quote, or memorable insight.", "Large quotation or statement, narrow accent bar, attribution separated from body.", "quote + speaker/source", "low"),
    Layout("L10", "Process Pipeline Flow", "Process / sequence", "Explain a repeatable workflow with discrete stages.", "Four connected step cards, numbered nodes, concise action labels and directional flow.", "3–6 ordered steps", "medium", "Optional simple icon per step"),
    Layout("L11", "Four-Quadrant Matrix", "Frameworks", "Organize a topic into four related dimensions.", "Balanced 2×2 grid, equal card dimensions, clear quadrant labels and short descriptions.", "four dimensions", "medium"),
    Layout("L12", "Left-Heavy Editorial", "Narrative", "Lead with a strong argument and provide deeper explanation.", "Large left headline and summary, right reading column with paragraph hierarchy.", "headline + dek + 2–4 paragraphs", "high"),
    Layout("L13", "Team & Bio Overview", "People / organization", "Introduce three or four team members or stakeholders.", "Aligned portrait placeholders, name/role hierarchy, short bio and consistent image crop.", "person + role + bio", "medium", "Portraits recommended"),
    Layout("L14", "Modern Outro", "Opening / closing", "Close with a decision, next step, or contact details.", "Dark canvas, concise closing statement, action/contact line and minimal visual noise.", "closing statement + CTA/contact", "low"),
    Layout("L15", "Agenda / Section Map", "Navigation", "Preview the talk or signal the structure of a long deck.", "Numbered agenda list with current section highlighted and concise section names.", "4–7 sections", "low"),
    Layout("L16", "Full-Bleed Image + Caption", "Visual storytelling", "Use a photograph or artwork as the primary evidence or emotional anchor.", "Large image zone with controlled caption band and strong contrast for any overlay.", "image + title/caption/source", "low", "Image-led; use high-quality artwork"),
    Layout("L17", "Image + Text Split", "Visual storytelling", "Explain an object, product, place, or concept using supporting imagery.", "Roughly 50/50 image and text columns, image crop aligned to content height.", "image + title + 3 points", "medium", "Image required or strongly recommended"),
    Layout("L18", "Chart + Insight Panel", "Data / evidence", "Pair a chart with the takeaway the audience should notice.", "Chart area takes two-thirds; right insight panel states the conclusion and caveat.", "chart + one insight + source", "medium", "Chart required"),
    Layout("L19", "Funnel / Conversion", "Data / process", "Show narrowing stages, conversion, or prioritization.", "Vertically stacked or tapered stages, consistent stage labels and values.", "3–6 stages + counts/rates", "medium"),
    Layout("L20", "Pyramid / Maturity Levels", "Frameworks", "Show hierarchy, maturity, or foundational-to-advanced progression.", "Layered pyramid or tier stack, broad foundation and progressively narrower upper levels.", "3–5 ordered levels", "medium"),
    Layout("L21", "Flywheel / Circular Cycle", "Process / systems", "Explain a reinforcing loop or recurring operating model.", "Circular sequence of 4–6 nodes around a central outcome, directional cues.", "cycle steps + center outcome", "medium"),
    Layout("L22", "Hub-and-Spoke Ecosystem", "Systems / architecture", "Show a central platform connected to teams, services, or partners.", "Central hub with radial nodes and clean connector lines; avoid crossing connectors.", "central entity + 4–6 connected entities", "medium"),
    Layout("L23", "Roadmap / Swimlane", "Planning", "Map initiatives across time and workstreams.", "Time columns with swimlane rows, phase bars and clear milestones.", "time periods + workstreams + initiatives", "high"),
    Layout("L24", "Risk / Impact Matrix", "Decision support", "Prioritize risks or opportunities using two variables.", "2×2 or 3×3 plotted matrix with labeled axes, colored zones and concise item labels.", "items + likelihood + impact", "medium"),
    Layout("L25", "Before / After Transformation", "Comparison / change", "Show the effect of a change or intervention.", "Two matched panels, explicit before/after labels, central transition cue.", "before state + after state + change", "medium"),
    Layout("L26", "Case Study / Proof Point", "Evidence / narrative", "Tell a compact story with challenge, intervention, and result.", "Outcome metric strip plus three narrative blocks for challenge, action and result.", "context + challenge + action + measurable result", "medium"),
    Layout("L27", "Portfolio / Gallery Grid", "Visual storytelling", "Show examples, products, work samples, or visual directions.", "Two-by-three thumbnail grid, short captions, uniform image frames and consistent gutters.", "4–6 visuals + labels", "medium", "Images required"),
    Layout("L28", "Organization / Hierarchy Tree", "People / systems", "Explain reporting lines, ownership, or system decomposition.", "Top-down hierarchy with aligned nodes, connector lines and limited depth per slide.", "parent node + child nodes", "medium"),
    Layout("L29", "Technical Architecture Map", "Systems / architecture", "Explain components, integrations, and data movement.", "Layered component containers, labeled interfaces and directional connectors.", "systems + interfaces + data flows", "high", "Use simplified vector diagrams; avoid tiny labels"),
    Layout("L30", "SWOT Analysis", "Frameworks", "Summarize strengths, weaknesses, opportunities, and threats.", "Four color-coded quadrants, consistent label/description treatment, short phrases.", "four SWOT categories", "medium"),
    Layout("L31", "Scorecard / KPI Dashboard", "Data / evidence", "Monitor a group of measures against targets or status.", "Compact metric cards plus status indicators and a small trend/comparison region.", "4–6 KPIs + target/status/trend", "high"),
    Layout("L32", "Waterfall / Bridge", "Data / evidence", "Explain how a starting value changes through positive and negative drivers.", "Floating bars on a common numeric axis, opening/closing totals visually distinct.", "start + incremental changes + end", "medium", "Chart required"),
    Layout("L33", "Geographic / Regional Overview", "Data / evidence", "Compare regions, markets, or locations.", "Map or abstract regional visual paired with a ranked metric/legend panel.", "regions + values + source", "medium", "Map or regional illustration recommended"),
    Layout("L34", "Customer Journey Map", "Experience / process", "Show customer stages, actions, pain points, and opportunities.", "Horizontal stage columns with swimlanes for behavior, friction, and interventions.", "stages + actions + emotions/pain points", "high"),
    Layout("L35", "Problem → Solution → Outcome", "Narrative / persuasion", "Make a persuasive case for an intervention.", "Three-step horizontal narrative with problem, response and outcome visibly distinguished.", "problem + solution + outcome", "medium"),
    Layout("L36", "Layered Stack / Platform", "Systems / architecture", "Explain layers of a platform, operating model, or capability stack.", "Stacked horizontal layers with distinct fills, labels and optional side annotations.", "3–6 layers + relationships", "medium"),
    Layout("L37", "Decision Tree", "Decision support", "Explain a branching decision or diagnostic path.", "Top decision node with limited branching, yes/no labels and legible terminal outcomes.", "decision questions + branches + outcomes", "high"),
    Layout("L38", "Ranked List / Priority Ladder", "Decision support", "Rank initiatives, recommendations, or opportunities.", "Numbered vertical ranking with highlighted top priority and short evidence per item.", "3–7 ranked items", "medium"),
    Layout("L39", "Quote + Evidence", "Emphasis / evidence", "Pair a human voice with a supporting metric or proof point.", "Quote occupies the main field; side metric/source validates the claim.", "quote + attribution + metric", "medium"),
    Layout("L40", "FAQ / Myth vs Fact", "Education", "Resolve recurring questions or correct misconceptions.", "Question-answer rows or paired myth/fact cards with clear visual labels.", "3–5 question-answer pairs", "high"),
    Layout("L41", "Product / Feature Spotlight", "Product / marketing", "Explain one product capability or differentiator.", "Large product/artwork zone, feature callouts and concise value statement.", "hero visual + 2–4 feature callouts", "medium", "Product artwork recommended"),
    Layout("L42", "Financial Snapshot", "Data / evidence", "Summarize revenue, cost, growth, margin, or budget.", "Headline financial metric, compact breakdown chart and notes for period/units.", "financial KPIs + breakdown + period", "high", "Chart recommended"),
    Layout("L43", "Source / Methodology", "Reference", "Show how evidence was collected and how to interpret it.", "Readable source list, methodology notes, date range and limitations.", "sources + method + caveats", "high"),
    Layout("L44", "Appendix / Dense Reference", "Reference", "Place supporting detail outside the main narrative.", "Structured table or grouped bullets with compact but legible typography.", "reference facts / detailed table", "high"),
    Layout("L45", "Executive Summary", "Executive / strategy", "Summarize the decision, evidence, and recommended action on one slide.", "Prominent takeaway, three supporting proof cards, and a clear decision ask.", "takeaway + 3 points + ask", "medium"),
    Layout("L46", "One Big Idea", "Emphasis", "Make a single thesis or strategic message memorable.", "Oversized central statement, restrained accent motif, and one supporting proof point.", "one statement + proof", "low"),
    Layout("L47", "Three-Act Story", "Narrative", "Structure a story as context, tension, and resolution.", "Three connected narrative panels with a clear progression.", "setup + tension + resolution", "medium"),
    Layout("L48", "Milestone Gates", "Planning / governance", "Show stage gates, approvals, and exit criteria.", "Horizontal stages with gate markers and decision criteria beneath each.", "gates + criteria", "medium"),
    Layout("L49", "Capability Map", "Strategy / systems", "Map capabilities by domain, maturity, or ownership.", "Grouped capability tiles organized into meaningful domains.", "capability groups", "high"),
    Layout("L50", "Value Chain", "Strategy / operations", "Show how activities create and deliver value.", "Ordered value-creation stages with outputs and hand-offs.", "ordered value stages", "medium"),
    Layout("L51", "Operating Model", "Organization / operations", "Connect governance, people, process, data, and technology.", "Central operating-model frame surrounded by aligned component cards.", "operating model components", "high"),
    Layout("L52", "Service Blueprint", "Experience / operations", "Connect customer actions to frontstage and backstage operations.", "Horizontal journey stages over customer, frontstage, backstage, and support lanes.", "journey + support lanes", "high"),
    Layout("L53", "Product Lifecycle", "Product / strategy", "Show a product from discovery through retirement.", "Lifecycle stages on a horizontal arc or sequence with stage outputs.", "lifecycle stages", "medium"),
    Layout("L54", "Market Segmentation", "Market / strategy", "Compare audience segments by need, size, or attractiveness.", "Segment cards with needs, relative size, and value opportunity.", "segments + attributes", "medium"),
    Layout("L55", "Competitive Positioning Map", "Comparison / strategy", "Plot alternatives across two meaningful dimensions.", "Two-axis scatter map with readable competitor labels and a legend.", "competitors + two axes", "medium"),
    Layout("L56", "Opportunity Prioritization", "Decision support", "Rank opportunities by value, effort, and strategic fit.", "Prioritization matrix or scored list with the top opportunity emphasized.", "opportunities + scores", "medium"),
    Layout("L57", "Scenario Planning", "Strategy / risk", "Compare plausible futures and their implications.", "Two to four scenario cards with assumptions and strategic responses.", "2–4 scenarios", "medium"),
    Layout("L58", "Assumptions & Hypotheses", "Strategy / validation", "Make assumptions testable with evidence and experiments.", "Assumption, test, evidence, and decision columns.", "assumption + test + evidence", "medium"),
    Layout("L59", "Implementation Plan", "Planning / execution", "Translate a recommendation into owners, dates, and actions.", "Action rows with owner, timing, dependency, and status.", "actions + owners + timing", "high"),
    Layout("L60", "Decision / Approval", "Decision support", "Make the requested decision and consequences explicit.", "Decision question, options, recommendation, implications, and approval ask.", "decision + options + ask", "low"),
]


# ---------------------------------------------------------------------------
# Reusable drawing helpers
# ---------------------------------------------------------------------------

def set_background(slide, color=C["light"]):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def add_shape(slide, shape_type, x, y, w, h, fill, line=None, radius=False):
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    return shape


def add_text(slide, text, x, y, w, h, size=16, color=None, bold=False,
             align=PP_ALIGN.LEFT, italic=False, font=FONT, margin=0.02,
             valign=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    p = tf.paragraphs[0]
    p.text = str(text)
    p.alignment = align
    p.font.name = font
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.italic = italic
    p.font.color.rgb = color or C["text"]
    return box


def add_header(slide, title, family, slide_no):
    add_text(slide, family.upper(), LEFT, 0.34, 9.8, 0.25, 9, C["accent"], True)
    add_text(slide, title, LEFT, 0.67, 11.6, 0.72, 28, C["dark"], True)
    add_shape(slide, MSO_SHAPE.RECTANGLE, LEFT, 1.52, 0.72, 0.045, C["accent"])
    add_text(slide, f"{slide_no:02d}", 11.78, 0.38, 0.7, 0.25, 10, C["muted"], True, PP_ALIGN.RIGHT)


def add_card(slide, x, y, w, h, title, body, number=None, accent=None):
    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, C["white"], C["border"])
    if number is not None:
        add_text(slide, str(number), x + 0.22, y + 0.20, w - 0.44, 0.35, 22, accent or C["accent"], True)
        title_y = y + 0.75
    else:
        title_y = y + 0.25
    add_text(slide, title, x + 0.22, title_y, w - 0.44, 0.55, 15, C["dark"], True)
    add_text(slide, body, x + 0.22, title_y + 0.62, w - 0.44, h - (title_y - y) - 0.75, 11, C["muted"])


def add_bullet_list(slide, items, x, y, w, line_h=0.72, size=15):
    for i, item in enumerate(items):
        yy = y + i * line_h
        add_shape(slide, MSO_SHAPE.OVAL, x, yy + 0.10, 0.11, 0.11, C["accent"])
        add_text(slide, item, x + 0.24, yy, w - 0.24, line_h - 0.05, size, C["text"])


# ---------------------------------------------------------------------------
# Renderers: each family has a purposeful visual treatment.
# ---------------------------------------------------------------------------

def render_layout(prs: Presentation, layout: Layout, slide_no: int):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    dark_slide = layout.id in {"L01", "L14"}
    set_background(slide, C["dark"] if dark_slide else C["light"])
    if layout.id not in {"L01", "L14"}:
        add_header(slide, layout.name, layout.family, slide_no)

    # Opening and closing slides
    if layout.id in {"L01", "L14"}:
        add_shape(slide, MSO_SHAPE.RECTANGLE, 0, 0, 0.16, 7.5, C["accent"])
        title = "Design with a system." if layout.id == "L01" else "Make the next move."
        subtitle = "A global library of presentation layout archetypes" if layout.id == "L01" else "Decision • Discussion • Next steps"
        add_text(slide, "PRESENTATION DESIGN SYSTEM", 1.15, 1.65, 8.8, 0.3, 11, C["accent2"], True)
        add_text(slide, title, 1.12, 2.25, 10.7, 1.25, 42, C["white"], True)
        add_text(slide, subtitle, 1.15, 3.75, 9.8, 0.7, 20, C["white"])
        add_shape(slide, MSO_SHAPE.RECTANGLE, 1.15, 4.72, 1.0, 0.06, C["accent"])
        add_text(slide, "Editable native PowerPoint layout specimen", 1.15, 5.05, 8.8, 0.35, 11, C["muted"])
        return slide

    # A: cards, options, and grouped concepts
    if layout.id in {"L03", "L11", "L13", "L27", "L30", "L31", "L40"}:
        if layout.id in {"L11", "L30"}:
            items = [("01  FOUNDATION", "Core capability or strength"), ("02  CONSTRAINT", "Limitation or weakness"),
                     ("03  OPPORTUNITY", "External opening to pursue"), ("04  RISK", "Threat or uncertainty")]
            coords = [(0.9, 2.0), (6.85, 2.0), (0.9, 4.35), (6.85, 4.35)]
            fills = [C["pale_blue"], C["pale_amber"], C["pale_green"], C["pale_red"]]
            for i, ((t, b), (x, y)) in enumerate(zip(items, coords)):
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, 5.55, 2.0, fills[i], C["border"])
                add_text(slide, t, x + 0.25, y + 0.25, 5.0, 0.4, 15, C["dark"], True)
                add_text(slide, b, x + 0.25, y + 0.82, 5.0, 0.8, 13, C["text"])
        elif layout.id == "L13":
            for i, (name, role) in enumerate([("Alex Morgan", "Strategy"), ("Jordan Lee", "Engineering"), ("Sam Taylor", "Design")]):
                x = 0.95 + i * 3.95
                add_shape(slide, MSO_SHAPE.OVAL, x + 0.92, 2.0, 1.45, 1.45, C["pale_blue"], C["border"])
                add_text(slide, name, x, 3.68, 3.3, 0.35, 16, C["dark"], True, PP_ALIGN.CENTER)
                add_text(slide, role, x, 4.12, 3.3, 0.3, 12, C["accent"], True, PP_ALIGN.CENTER)
                add_text(slide, "Short role summary and relevant expertise.", x + 0.1, 4.62, 3.1, 0.9, 11, C["muted"], align=PP_ALIGN.CENTER)
        elif layout.id == "L27":
            for i in range(6):
                x = 0.92 + (i % 3) * 3.95
                y = 2.0 + (i // 3) * 2.25
                add_shape(slide, MSO_SHAPE.RECTANGLE, x, y, 3.55, 1.45, [C["pale_blue"], C["pale_cyan"], C["pale_green"]][i % 3], C["border"])
                add_text(slide, f"VISUAL {i+1}", x + 0.1, y + 0.53, 3.35, 0.3, 12, C["muted"], True, PP_ALIGN.CENTER)
                add_text(slide, f"Caption {i+1}", x, y + 1.55, 3.55, 0.3, 11, C["text"], True)
        elif layout.id == "L31":
            vals = [("98.6%", "Availability"), ("+18%", "Growth"), ("4.2/5", "Satisfaction"), ("72", "Active projects")]
            for i, (v, label) in enumerate(vals):
                x = 0.95 + i * 2.95
                add_card(slide, x, 2.2, 2.65, 1.7, label, "Target / trend context", v, [C["accent"], C["green"], C["accent2"], C["amber"]][i])
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.95, 4.35, 11.55, 1.55, C["white"], C["border"])
            add_text(slide, "Trend / status summary", 1.25, 4.65, 3.2, 0.35, 15, C["dark"], True)
            for i, h in enumerate([0.45, 0.72, 0.58, 0.95, 1.12, 0.84, 1.28, 1.05]):
                add_shape(slide, MSO_SHAPE.RECTANGLE, 5.0 + i * 0.75, 5.45 - h * 0.55, 0.38, h * 0.55, C["accent"] if i == 7 else C["pale_blue"])
        else:
            n = 3 if layout.id == "L03" else 4
            for i in range(n):
                x = 0.95 + (i % 3) * 3.95
                y = 2.25 if i < 3 else 4.55
                title = (["Clarity", "Consistency", "Scalability"][i] if layout.id == "L03" else
                         ["Signal", "Structure", "Action", "Outcome"][i] if layout.id == "L40" else
                         ["Focus", "Evidence", "Delivery", "Learning"][i])
                body = "A concise explanation that supports the main point without overloading the card."
                add_card(slide, x, y, 3.5, 1.85, title, body, f"{i+1:02d}")
        return slide

    # B: comparisons, before/after, editorial and problem-solution
    if layout.id in {"L04", "L08", "L12", "L25", "L35", "L41"}:
        if layout.id == "L04":
            add_shape(slide, MSO_SHAPE.RECTANGLE, 0, 0, 4.35, 7.5, C["accent"])
            add_text(slide, "FOCUS", 0.65, 3.0, 3.1, 0.7, 34, C["white"], True)
            add_text(slide, "One strong idea", 5.0, 2.4, 6.8, 0.65, 28, C["dark"], True)
            add_text(slide, "Use the open side for context, evidence, or a short narrative that explains why this matters.", 5.0, 3.3, 6.7, 1.5, 17, C["text"])
        elif layout.id == "L12":
            add_text(slide, "A strong editorial claim", 0.95, 2.1, 4.35, 1.5, 28, C["dark"], True)
            add_text(slide, "A short supporting deck that tells the audience what to look for.", 0.95, 3.8, 4.15, 1.0, 15, C["muted"])
            add_text(slide, "Develop the argument in a right-hand reading column. Use two or three concise paragraphs, a clear evidence point, and a closing implication. Avoid turning the column into a wall of text; use subheads or a pull quote if the material is dense.", 5.65, 2.2, 6.2, 3.3, 16, C["text"])
        elif layout.id == "L41":
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.95, 2.1, 5.0, 4.0, C["pale_blue"], C["border"])
            add_text(slide, "PRODUCT / ARTWORK", 1.2, 3.65, 4.5, 0.4, 14, C["muted"], True, PP_ALIGN.CENTER)
            add_text(slide, "One capability, clearly framed", 6.45, 2.25, 5.4, 0.65, 22, C["dark"], True)
            add_bullet_list(slide, ["Benefit-led feature callout", "Supporting proof or use case", "Clear differentiation"], 6.5, 3.25, 5.3, 0.78, 14)
        else:
            labels = ("CURRENT STATE", "FUTURE STATE") if layout.id == "L25" else (("PROBLEM", "SOLUTION", "OUTCOME") if layout.id == "L35" else ("OPTION A", "OPTION B"))
            n = len(labels)
            width = 5.35 if n == 2 else 3.55
            gap = 0.55
            start = (13.333 - (n * width + (n - 1) * gap)) / 2
            fills = [C["pale_blue"], C["pale_green"], C["pale_amber"]]
            for i, label in enumerate(labels):
                x = start + i * (width + gap)
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.45, width, 3.25, fills[i % len(fills)], C["border"])
                add_text(slide, label, x + 0.25, 2.8, width - 0.5, 0.45, 15, C["accent"] if i == 0 else C["dark"], True)
                add_bullet_list(slide, ["Key point / evidence", "Trade-off or implication", "Recommended next step"], x + 0.25, 3.55, width - 0.5, 0.58, 11)
        return slide

    # C: timelines, roadmaps, process, journey and cycles
    if layout.id in {"L06", "L10", "L19", "L21", "L23", "L34"}:
        if layout.id == "L06":
            add_shape(slide, MSO_SHAPE.RECTANGLE, 1.05, 4.0, 11.2, 0.045, C["border"])
            for i, (period, title) in enumerate([("Q1", "Discover"), ("Q2", "Design"), ("Q3", "Build"), ("Q4", "Launch")]):
                x = 1.15 + i * 2.95
                add_shape(slide, MSO_SHAPE.OVAL, x + 0.65, 3.84, 0.34, 0.34, C["accent"])
                y = 2.2 if i % 2 == 0 else 4.55
                add_text(slide, period, x, y, 1.8, 0.28, 11, C["accent"], True)
                add_text(slide, title, x, y + 0.35, 2.2, 0.35, 16, C["dark"], True)
                add_text(slide, "Milestone summary", x, y + 0.8, 2.3, 0.5, 11, C["muted"])
        elif layout.id == "L23":
            lane_names = ["Platform", "Experience", "Operations"]
            periods = ["NOW", "NEXT", "LATER"]
            for j, lane in enumerate(lane_names):
                y = 2.15 + j * 1.35
                add_text(slide, lane, 0.95, y + 0.22, 1.6, 0.35, 12, C["dark"], True)
                for i, period in enumerate(periods):
                    x = 2.7 + i * 3.15
                    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, 2.8, 0.82, [C["pale_blue"], C["pale_cyan"], C["pale_green"]][i], C["border"])
                    add_text(slide, f"{period}: initiative", x + 0.12, y + 0.25, 2.55, 0.28, 11, C["text"], True)
        elif layout.id == "L34":
            stages = ["Discover", "Evaluate", "Purchase", "Use"]
            for i, stage in enumerate(stages):
                x = 0.95 + i * 2.95
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.15, 2.65, 0.65, C["pale_blue"], C["border"])
                add_text(slide, stage, x + 0.1, 2.33, 2.45, 0.3, 13, C["dark"], True, PP_ALIGN.CENTER)
                for j, label in enumerate(["Customer action", "Pain point", "Opportunity"]):
                    yy = 3.05 + j * 0.83
                    add_text(slide, label, x + 0.08, yy, 2.5, 0.25, 10, C["accent"] if j == 2 else C["muted"], True)
                    add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x + 0.08, yy + 0.28, 2.48, 0.35, C["white"], C["border"])
        elif layout.id == "L21":
            add_shape(slide, MSO_SHAPE.OVAL, 5.35, 3.15, 2.55, 1.65, C["pale_blue"], C["accent"])
            add_text(slide, "REINFORCING\nOUTCOME", 5.6, 3.65, 2.05, 0.55, 14, C["dark"], True, PP_ALIGN.CENTER)
            positions = [(5.25, 2.0), (8.35, 3.2), (5.35, 5.0), (2.25, 3.2)]
            names = ["Attract", "Engage", "Deliver", "Learn"]
            for i, ((x, y), name) in enumerate(zip(positions, names)):
                add_shape(slide, MSO_SHAPE.OVAL, x, y, 1.45, 0.78, C["white"], C["accent"])
                add_text(slide, name, x + 0.08, y + 0.23, 1.3, 0.28, 11, C["dark"], True, PP_ALIGN.CENTER)
        else:
            count = 5 if layout.id == "L19" else 4
            for i in range(count):
                if layout.id == "L19":
                    w = 8.8 - i * 1.15
                    x = (13.333 - w) / 2
                    y = 2.05 + i * 0.88
                    add_shape(slide, MSO_SHAPE.TRAPEZOID, x, y, w, 0.72, [C["accent"], C["dark2"], C["accent2"], C["green"], C["amber"]][i], None)
                    add_text(slide, ["Awareness", "Interest", "Consideration", "Intent", "Conversion"][i], x + 0.2, y + 0.18, w - 0.4, 0.28, 12, C["white"] if i < 4 else C["dark"], True, PP_ALIGN.CENTER)
                else:
                    x = 0.95 + i * 2.95
                    add_card(slide, x, 2.65, 2.55, 2.65, ["Intake", "Validate", "Create", "Review"][i], "One clear action and its output.", i + 1)
        return slide

    # D: data, charts, matrices and financial views
    if layout.id in {"L05", "L07", "L18", "L24", "L32", "L33", "L42"}:
        if layout.id == "L05":
            for i, (v, label) in enumerate([("98.6%", "Reliability"), ("2.4×", "Throughput"), ("−31%", "Cycle time")]):
                x = 1.05 + i * 3.9
                add_text(slide, v, x, 2.7, 3.3, 1.0, 42, C["accent"], True, PP_ALIGN.CENTER)
                add_text(slide, label, x, 3.85, 3.3, 0.4, 14, C["dark"], True, PP_ALIGN.CENTER)
                add_text(slide, "vs. baseline / target", x, 4.38, 3.3, 0.3, 10, C["muted"], align=PP_ALIGN.CENTER)
        elif layout.id == "L07":
            rows = [["Core platform", "4,500", "94%", "On track"], ["Experience", "8,900", "98%", "Stable"], ["Delivery", "12,100", "99%", "Active"]]
            headers = ["Component", "Volume", "Efficiency", "Status"]
            shape = slide.shapes.add_table(4, 4, Inches(0.95), Inches(2.25), Inches(11.45), Inches(3.55))
            table = shape.table
            for cidx, h in enumerate(headers):
                cell = table.cell(0, cidx); cell.text = h
                cell.fill.solid(); cell.fill.fore_color.rgb = C["dark"]
            for ridx, row in enumerate(rows, 1):
                for cidx, val in enumerate(row):
                    cell = table.cell(ridx, cidx); cell.text = val
                    cell.fill.solid(); cell.fill.fore_color.rgb = C["white"] if ridx % 2 else C["pale_blue"]
            for ridx in range(4):
                for cidx in range(4):
                    cell = table.cell(ridx, cidx)
                    cell.margin_left = Inches(0.14); cell.margin_right = Inches(0.1)
                    for p in cell.text_frame.paragraphs:
                        p.font.name = FONT; p.font.size = Pt(12); p.font.bold = (ridx == 0)
                        p.font.color.rgb = C["white"] if ridx == 0 else C["text"]
        elif layout.id == "L18":
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.95, 2.15, 7.3, 4.1, C["white"], C["border"])
            for i, h in enumerate([1.0, 1.55, 1.3, 2.25, 2.75, 2.4]):
                x = 1.45 + i * 0.95
                add_shape(slide, MSO_SHAPE.RECTANGLE, x, 5.6 - h, 0.48, h, C["accent"] if i == 4 else C["pale_blue"])
            add_text(slide, "Illustrative trend", 1.35, 5.78, 5.9, 0.3, 10, C["muted"])
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 8.55, 2.15, 3.85, 4.1, C["pale_blue"], C["border"])
            add_text(slide, "KEY INSIGHT", 8.85, 2.55, 3.2, 0.3, 11, C["accent"], True)
            add_text(slide, "The strongest movement occurs in the final period.", 8.85, 3.0, 3.0, 1.2, 19, C["dark"], True)
            add_text(slide, "Add source, time range, units and caveats.", 8.85, 4.8, 3.0, 0.7, 11, C["muted"])
        elif layout.id == "L24":
            add_shape(slide, MSO_SHAPE.RECTANGLE, 2.0, 2.15, 8.8, 4.15, C["white"], C["border"])
            add_shape(slide, MSO_SHAPE.RECTANGLE, 6.4, 2.15, 0.025, 4.15, C["border"])
            add_shape(slide, MSO_SHAPE.RECTANGLE, 2.0, 4.22, 8.8, 0.025, C["border"])
            add_text(slide, "HIGH IMPACT", 2.2, 2.35, 1.7, 0.3, 10, C["red"], True)
            add_text(slide, "LOW IMPACT", 2.2, 5.78, 1.7, 0.3, 10, C["muted"], True)
            for x, y, label, color in [(3.1, 3.0, "Risk A", C["red"]), (7.4, 2.9, "Risk B", C["amber"]), (4.3, 4.85, "Risk C", C["green"]), (8.2, 5.0, "Risk D", C["accent"])]:
                add_shape(slide, MSO_SHAPE.OVAL, x, y, 0.24, 0.24, color)
                add_text(slide, label, x + 0.32, y - 0.03, 1.3, 0.3, 10, C["text"], True)
            add_text(slide, "LOW LIKELIHOOD", 2.0, 6.42, 2.3, 0.25, 10, C["muted"], True)
            add_text(slide, "HIGH LIKELIHOOD", 9.0, 6.42, 2.0, 0.25, 10, C["muted"], True, PP_ALIGN.RIGHT)
        elif layout.id == "L32":
            base_y = 5.6
            heights = [1.6, 0.7, 1.0, 0.55, 1.25]
            xs = [1.4, 3.35, 5.3, 7.25, 9.2]
            labels = ["Start", "+ Growth", "− Cost", "+ Mix", "End"]
            current = base_y
            for i, (x, h, label) in enumerate(zip(xs, heights, labels)):
                y = base_y - h if i in (0, 4) else current - h if i in (1, 3) else current
                add_shape(slide, MSO_SHAPE.RECTANGLE, x, y, 1.15, h, C["accent"] if i in (0, 4) else (C["green"] if "+" in label else C["red"]))
                add_text(slide, label, x - 0.15, 5.85, 1.45, 0.3, 10, C["text"], True, PP_ALIGN.CENTER)
                current = y
            add_shape(slide, MSO_SHAPE.RECTANGLE, 1.0, base_y, 10.2, 0.025, C["muted"])
        else:
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.95, 2.15, 7.1, 4.15, C["pale_blue"], C["border"])
            add_text(slide, "VISUAL / REGIONAL BREAKDOWN", 1.4, 3.75, 6.2, 0.4, 14, C["muted"], True, PP_ALIGN.CENTER)
            add_text(slide, "Headline result", 8.55, 2.35, 3.5, 0.45, 19, C["dark"], True)
            add_text(slide, "Revenue / region / period", 8.55, 2.9, 3.4, 0.3, 11, C["muted"])
            add_bullet_list(slide, ["Largest contributor", "Fastest-growing segment", "Source and reporting period"], 8.55, 3.55, 3.7, 0.75, 12)
        return slide

    # E: frameworks, architecture and branching models
    if layout.id in {"L20", "L22", "L28", "L29", "L36", "L37"}:
        if layout.id == "L20":
            for i, (name, fill) in enumerate([("ADVANCED", C["accent"]), ("DEFINED", C["dark2"]), ("REPEATABLE", C["accent2"]), ("FOUNDATIONAL", C["green"])]):
                w = 3.0 + i * 1.4
                x = (13.333 - w) / 2
                y = 2.0 + i * 1.05
                add_shape(slide, MSO_SHAPE.TRAPEZOID, x, y, w, 0.78, fill)
                add_text(slide, name, x + 0.1, y + 0.22, w - 0.2, 0.3, 12, C["white"], True, PP_ALIGN.CENTER)
        elif layout.id == "L22":
            add_shape(slide, MSO_SHAPE.OVAL, 5.25, 3.25, 2.75, 1.35, C["dark"])
            add_text(slide, "CORE PLATFORM", 5.45, 3.73, 2.35, 0.3, 13, C["white"], True, PP_ALIGN.CENTER)
            positions = [(1.5, 2.2), (4.0, 2.0), (8.4, 2.0), (10.2, 4.4), (3.0, 5.0)]
            for i, (x, y) in enumerate(positions):
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, 1.9, 0.72, C["pale_blue"], C["accent"])
                add_text(slide, ["Teams", "Data", "Services", "Partners", "Tools"][i], x + 0.08, y + 0.22, 1.74, 0.25, 11, C["dark"], True, PP_ALIGN.CENTER)
        elif layout.id == "L37":
            add_shape(slide, MSO_SHAPE.DIAMOND, 5.25, 2.0, 2.7, 1.35, C["pale_amber"], C["amber"])
            add_text(slide, "Decision?", 5.75, 2.52, 1.7, 0.28, 13, C["dark"], True, PP_ALIGN.CENTER)
            for x, y, label, fill in [(2.25, 4.25, "YES → Action A", C["pale_green"]), (8.55, 4.25, "NO → Action B", C["pale_red"])]:
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, 2.65, 0.95, fill, C["border"])
                add_text(slide, label, x + 0.12, y + 0.32, 2.4, 0.3, 12, C["dark"], True, PP_ALIGN.CENTER)
        elif layout.id == "L36":
            layers = [("EXPERIENCE LAYER", C["pale_blue"]), ("SERVICES & ORCHESTRATION", C["pale_cyan"]), ("DATA & INTEGRATION", C["pale_green"]), ("INFRASTRUCTURE", C["dark2"])]
            for i, (label, fill) in enumerate(layers):
                y = 2.0 + i * 1.05
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 2.0, y, 8.7, 0.78, fill, C["border"])
                add_text(slide, label, 2.25, y + 0.23, 8.2, 0.28, 12, C["white"] if i == 3 else C["dark"], True, PP_ALIGN.CENTER)
        else:
            levels = [("Strategy / goals", 0.95, 2.25, 11.4), ("Applications / capabilities", 1.5, 3.45, 10.3), ("Data / integrations", 2.05, 4.65, 9.2)]
            for label, x, y, w in levels:
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, 0.72, C["white"], C["accent"])
                add_text(slide, label, x + 0.2, y + 0.2, w - 0.4, 0.3, 13, C["dark"], True, PP_ALIGN.CENTER)
            add_text(slide, "Label interfaces, ownership, direction of flow, and system boundaries.", 1.0, 5.85, 11.3, 0.45, 12, C["muted"], align=PP_ALIGN.CENTER)
        return slide

    # F: narrative, quotes, case studies, rankings, FAQ, sources and appendix
    if layout.id in {"L02", "L09", "L15", "L16", "L17", "L26", "L38", "L39", "L43", "L44"}:
        if layout.id == "L09":
            add_shape(slide, MSO_SHAPE.RECTANGLE, 1.15, 2.45, 0.08, 2.7, C["accent"])
            add_text(slide, "“Clarity is not the absence of detail; it is the result of deliberate hierarchy.”", 1.55, 2.5, 9.7, 1.65, 25, C["dark"], True, italic=True)
            add_text(slide, "— Example attribution / source", 1.6, 4.65, 7.0, 0.4, 13, C["muted"])
        elif layout.id == "L15":
            for i, item in enumerate(["Context and objective", "What the evidence says", "Options and trade-offs", "Recommendation", "Decision and next steps"]):
                y = 2.05 + i * 0.82
                add_text(slide, f"{i+1:02d}", 1.1, y, 0.7, 0.4, 16, C["accent"], True)
                add_text(slide, item, 2.0, y, 7.8, 0.4, 17, C["dark"] if i == 0 else C["text"], i == 0)
                add_shape(slide, MSO_SHAPE.RECTANGLE, 2.0, y + 0.52, 8.8, 0.015, C["border"])
        elif layout.id == "L16":
            add_shape(slide, MSO_SHAPE.RECTANGLE, 0.85, 1.95, 11.65, 4.15, C["dark2"])
            add_text(slide, "FULL-BLEED ARTWORK / PHOTO ZONE", 1.2, 3.65, 10.95, 0.45, 16, C["white"], True, PP_ALIGN.CENTER)
            add_text(slide, "Caption: explain why this image matters • Source / credit", 0.95, 6.25, 11.4, 0.3, 10, C["muted"])
        elif layout.id == "L17":
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.95, 2.05, 5.2, 4.25, C["pale_blue"], C["border"])
            add_text(slide, "IMAGE / ILLUSTRATION", 1.25, 3.85, 4.6, 0.35, 14, C["muted"], True, PP_ALIGN.CENTER)
            add_text(slide, "A visual explanation", 6.7, 2.25, 5.0, 0.5, 22, C["dark"], True)
            add_bullet_list(slide, ["What the audience should notice", "Why it matters", "Implication or action"], 6.7, 3.1, 5.0, 0.85, 13)
        elif layout.id == "L26":
            add_text(slide, "RESULT", 1.0, 2.0, 2.0, 0.25, 10, C["accent"], True)
            add_text(slide, "+27%", 1.0, 2.35, 3.0, 0.8, 36, C["accent"], True)
            add_text(slide, "Illustrative outcome metric", 1.0, 3.25, 3.0, 0.4, 12, C["muted"])
            for i, (t, b) in enumerate([("Challenge", "Define the customer or business problem."), ("Intervention", "Describe the action and why it was chosen."), ("Result", "Quantify the result and state the evidence.")]):
                add_card(slide, 4.1 + i * 2.75, 2.25, 2.45, 3.15, t, b, i+1)
        elif layout.id == "L38":
            for i, (title, desc) in enumerate([("Critical", "Immediate impact / unblock"), ("High value", "Strong return / near-term"), ("Strategic", "Longer-term capability"), ("Monitor", "Keep visible; revisit later")]):
                y = 2.05 + i * 1.0
                add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 1.0, y, 0.65, 0.62, [C["accent"], C["accent2"], C["green"], C["muted"]][i])
                add_text(slide, str(i+1), 1.15, y+0.18, 0.35, 0.25, 13, C["white"], True, PP_ALIGN.CENTER)
                add_text(slide, title, 1.95, y+0.02, 2.4, 0.3, 15, C["dark"], True)
                add_text(slide, desc, 4.45, y+0.02, 6.2, 0.42, 12, C["muted"])
        elif layout.id == "L39":
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 0.95, 2.15, 7.4, 3.9, C["white"], C["border"])
            add_text(slide, "“A concise customer voice that captures the value proposition.”", 1.35, 2.8, 6.5, 1.3, 21, C["dark"], True, italic=True)
            add_text(slide, "— Customer / role / source", 1.4, 4.55, 5.8, 0.3, 11, C["muted"])
            add_shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, 8.7, 2.15, 3.55, 3.9, C["pale_blue"], C["border"])
            add_text(slide, "4.8 / 5", 9.0, 3.05, 2.95, 0.7, 29, C["accent"], True, PP_ALIGN.CENTER)
            add_text(slide, "Supporting proof point", 9.0, 3.95, 2.95, 0.45, 12, C["dark"], True, PP_ALIGN.CENTER)
        elif layout.id == "L43":
            add_text(slide, "SOURCES & EVIDENCE", 1.0, 2.1, 4.0, 0.3, 11, C["accent"], True)
            add_bullet_list(slide, ["Source name, publication date and link", "Method used to collect or calculate the data", "Sample size, scope and reporting period", "Known limitations, assumptions and exclusions"], 1.0, 2.7, 10.8, 0.8, 13)
        elif layout.id == "L44":
            for i in range(5):
                y = 2.0 + i * 0.83
                add_text(slide, f"REF-{i+1:02d}", 1.0, y, 1.3, 0.3, 11, C["accent"], True)
                add_text(slide, "Reference item / detailed supporting information", 2.55, y, 8.8, 0.3, 12, C["text"])
                add_shape(slide, MSO_SHAPE.RECTANGLE, 1.0, y + 0.48, 10.9, 0.015, C["border"])
        else:
            add_text(slide, "Lead with the conclusion.", 1.0, 2.15, 7.5, 0.6, 24, C["dark"], True)
            add_text(slide, "Support it with evidence, examples, and implications. Keep each bullet focused on one idea; use a new slide when the content changes purpose.", 1.0, 3.0, 9.7, 1.1, 16, C["text"])
            add_bullet_list(slide, ["Claim → evidence → implication", "Prefer specific, parallel bullet wording", "Cite sources for external facts and metrics"], 1.0, 4.5, 10.0, 0.62, 13)
        return slide

    # Safe fallback for future catalog entries.
    add_text(slide, layout.name, 1.0, 2.3, 10.5, 0.6, 26, C["dark"], True)
    add_text(slide, layout.implementation, 1.0, 3.2, 10.5, 1.2, 16, C["text"])
    return slide


def build_presentation(output_path: Path, layouts: Iterable[Layout] = LAYOUTS) -> None:
    prs = Presentation()
    prs.slide_width = WIDE_WIDTH
    prs.slide_height = WIDE_HEIGHT
    prs.core_properties.title = "Presentation Layout Archetype Library"
    prs.core_properties.subject = "Editable specimen slides for a programmatic presentation builder"
    prs.core_properties.author = "Presentation Layout Library"
    for number, layout in enumerate(layouts, start=1):
        render_layout(prs, layout, number)
    prs.save(output_path)


def write_summary(output_path: Path, layouts: Iterable[Layout] = LAYOUTS) -> None:
    lines = [
        "# Presentation Layout Archetype Library",
        "",
        f"**Total archetypes: {len(list(layouts))}.** This is a reusable starting catalogue, not a claim that every possible slide design has been enumerated.",
        "",
        "Use the stable layout ID and content pattern as inputs to your AI layout-selection stage. The implementation details describe the visual grammar; the renderer can then populate that grammar with slide-specific content.",
        "",
        "| Slide # | Layout Archetype | Design Implementation Details |",
        "| --- | --- | --- |",
    ]
    for i, layout in enumerate(layouts, start=1):
        implementation = layout.implementation.replace("|", "\\|")
        lines.append(f"| **{i:02d}** (`{layout.id}`) | **{layout.name}** | {implementation} |")
    lines += [
        "",
        "## Suggested selection metadata",
        "",
        "For production use, consider extending each catalogue record with: `required_fields`, `optional_fields`, `min_items`, `max_items`, `image_slots`, `chart_slots`, `preferred_density`, `aspect_ratio`, `content_intent`, `accessibility_notes`, and `overflow_strategy`.",
        "",
        "## Important implementation guidance",
        "",
        "- Keep layout selection separate from content generation and from final rendering.",
        "- Have the planner return a stable `layout_id` plus structured content, not arbitrary coordinates.",
        "- Define maximum title length, body length, and item counts for every layout; if content exceeds limits, shorten it, split the slide, or choose a denser archetype.",
        "- Use consistent design tokens for margins, typography, colors, and spacing.",
        "- Charts, maps, portraits, and screenshots should be real assets or native charts where appropriate; placeholder blocks in this specimen deck only demonstrate intended placement.",
        "- Validate every generated slide for text overflow, overlap, minimum font size, contrast, and empty placeholders before approval.",
        "- The example copy, names, and metrics in the PowerPoint are illustrative and should not be presented as factual claims.",
        "",
    ]
    output_path.write_text("\\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Build a PowerPoint specimen deck and layout catalogue.")
    parser.add_argument("--output", default="presentation_layout_library.pptx", help="Output PowerPoint path")
    parser.add_argument("--summary", default="presentation_layout_catalog.md", help="Output Markdown summary path")
    args = parser.parse_args()
    output = Path(args.output)
    summary = Path(args.summary)
    build_presentation(output)
    write_summary(summary)
    print(f"Created {output.resolve()} ({len(LAYOUTS)} slides)")
    print(f"Created {summary.resolve()} ({len(LAYOUTS)} layout records)")


if __name__ == "__main__":
    main()
