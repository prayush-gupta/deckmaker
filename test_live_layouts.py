"""Live test of the layout pipeline against the real local Ollama model."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI

from layout_catalogue import get_template
from layout_templates import (default_layout_for, recommend_layouts, structure_for_layout,
                              flatten_content)

ollama = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")
MODEL = "gpt-oss"

DECK = ("1. Why we are changing the pricing model\n"
        "2. What the numbers say\n"
        "3. Two options on the table\n"
        "4. Recommendation and next steps")

SLIDES = [
    {"title": "A better pricing model", "content": "Opening frame for the pricing review."},
    {"title": "What the numbers say", "content":
        "Revenue grew 27% year on year. Gross margin fell from 62% to 58%. Churn is flat at 3.1%. "
        "Enterprise accounts now drive 44% of revenue, up from 29% a year ago. "
        "Two thirds of new logos arrive through partner channels."},
    {"title": "Two options on the table", "content":
        "Option A keeps the current tiers and adds usage based pricing on top. "
        "Option B replaces three tiers with two and bundles onboarding. "
        "Option A is faster to ship but harder to explain. Option B is cleaner but needs a migration."},
    {"title": "Recommendation and next steps", "content":
        "We recommend Option B. Sign off on the packaging by 14 March. "
        "Migration plan drafted by 28 March. Pilot with the top 50 accounts from 1 April."},
]

print("=" * 70)
print("1) LLM LAYOUT RECOMMENDATION")
t0 = time.time()
picks = recommend_layouts(ollama, MODEL, DECK, SLIDES)
for p in picks:
    print(f"   slide {p['number']}: {p['layout_id']:>4}  {p['reason']}")
print(f"   ({time.time() - t0:.1f}s)")

print("=" * 70)
print("2) LLM CONTENT STRUCTURING (per layout)")
t0 = time.time()
for slide, pick in zip(SLIDES, picks):
    tpl = get_template(pick["layout_id"])
    data = structure_for_layout(ollama, MODEL, tpl, slide["title"], slide["content"], DECK)
    print(f"   {tpl.id} {tpl.name}: {flatten_content(data)[:110].replace(chr(10), ' | ')}")
print(f"   ({time.time() - t0:.1f}s)")

print("=" * 70)
print("3) RENDER THE SLIDES")
import gemini_code_fixed as g
for i, (slide, pick) in enumerate(zip(SLIDES, picks)):
    tpl = get_template(pick["layout_id"])
    data = structure_for_layout(ollama, MODEL, tpl, slide["title"], slide["content"], DECK)
    g.SLIDE_STRUCTURED[i] = data
    pptx, png = g.build_slide(tpl, data, i)
    print(f"   slide {i+1}: {tpl.id} {tpl.name:<28} -> {png}")

states = []
for i, (slide, pick) in enumerate(zip(SLIDES, picks)):
    states.extend([slide["title"], slide["content"], get_template(pick["layout_id"]).label, ""])
states.extend([""] * ((25 - len(SLIDES)) * 4))
path, status = g.compile_presentation_file("LiveLayoutTest", *states)
print("   deck:", path, os.path.getsize(path), "bytes")
print("  ", status.encode("ascii", "replace").decode().replace("\n", " ")[:110])
print("\nLIVE TEST COMPLETE")
