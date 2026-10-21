"""Offline end-to-end test of the layout pipeline (mock LLM, no ComfyUI needed)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from layout_catalogue import get_template
from layout_templates import (coerce_content, flatten_content, recommend_layouts,
                              structure_for_layout, build_template_deck, write_catalogue_markdown)


class _Msg:
    def __init__(self, content):
        self.content = content
        self.message = self


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class FakeOllama:
    """Answers both the layout-planner and the content-structuring calls."""

    def __init__(self):
        self.calls = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, model=None, messages=None, **kwargs):
        self.calls.append(messages)
        system = messages[0]["content"] if messages else ""
        if "slide designer" in system or "selects slide layouts" in system:
            return _Resp(json.dumps({"slides": [
                {"number": 1, "layout_id": "L01", "reason": "opens the deck"},
                {"number": 2, "layout_id": "L31", "reason": "numbers to watch"},
                {"number": 3, "layout_id": "L08", "reason": "two options compared"},
            ]}))
        # content structuring: echo a valid structure for the requested kind
        user = messages[-1]["content"]
        payload = {
            "title": "Restructured title",
            "subtitle": "A restructured subtitle",
            "eyebrow": "OVERVIEW",
            "footer": "Deckmaker",
            "statement": "One strong idea",
            "attribution": "- Someone",
            "quote": "A concise statement that carries the argument.",
            "intro": "Supporting line",
            "note": "a note",
            "caption": "a caption",
            "source": "source",
            "center": "OUTCOME",
            "hub": "CORE",
            "question": "Build or buy?",
            "change": "12 weeks",
            "x_label": "EFFORT",
            "y_label": "IMPACT",
            "total": "120",
            "month": "March 2026",
            "period": "FY26",
            "items": [{"number": "01", "heading": "Alpha", "body": "First supporting line."},
                      {"number": "02", "heading": "Beta", "body": "Second supporting line."},
                      {"number": "03", "heading": "Gamma", "body": "Third supporting line."}],
            "bullets": ["First point", "Second point", "Third point"],
            "panels": [{"heading": "Option A", "bullets": ["a", "b", "c"], "body": "Body A"},
                       {"heading": "Option B", "bullets": ["d", "e", "f"], "body": "Body B"}],
            "steps": [{"number": "1", "heading": "Step one", "body": "Do the first thing."},
                      {"number": "2", "heading": "Step two", "body": "Do the second thing."},
                      {"number": "3", "heading": "Step three", "body": "Do the third thing."}],
            "milestones": [{"period": "Q1", "heading": "Discover", "body": "First phase."},
                           {"period": "Q2", "heading": "Build", "body": "Second phase."},
                           {"period": "Q3", "heading": "Launch", "body": "Third phase."}],
            "metrics": [{"value": "98.6%", "label": "Reliability", "status": "On track",
                         "note": "vs baseline", "trend": 0.8},
                        {"value": "+18%", "label": "Growth", "status": "On track",
                         "note": "vs baseline", "trend": 0.6},
                        {"value": "4.2/5", "label": "Satisfaction", "status": "Stable",
                         "note": "vs baseline", "trend": 0.9}],
            "headline": {"value": "+27%", "label": "Lift", "note": "Measured over 12 weeks"},
            "stats": [{"value": "12wk", "label": "Window"}, {"value": "4.1%", "label": "Base"},
                      {"value": "n=2.4k", "label": "Sample"}],
            "trend": [0.4, 0.6, 0.5, 0.8, 1.0],
            "series": [{"label": "Q1", "value": 30}, {"label": "Q2", "value": 50},
                       {"label": "Q3", "value": 45}, {"label": "Q4", "value": 80}],
            "breakdown": [{"label": "Subs", "value": "8.1m"}, {"label": "Services", "value": "3.0m"},
                          {"label": "Other", "value": "1.3m"}],
            "segments": [{"label": "Eng", "value": 42}, {"label": "Mkt", "value": 24},
                         {"label": "Ops", "value": 34}],
            "layers": [{"heading": "Experience", "body": "Top layer", "items": ["Web", "Mobile"]},
                       {"heading": "Services", "body": "Middle layer", "items": ["Accounts", "Billing"]},
                       {"heading": "Data", "body": "Bottom layer", "items": ["Store", "Audit"]}],
            "spokes": [{"heading": "Teams", "body": "a"}, {"heading": "Data", "body": "b"},
                        {"heading": "Services", "body": "c"}, {"heading": "Partners", "body": "d"}],
            "children": [{"heading": "Apps", "body": "Capabilities"},
                         {"heading": "Data", "body": "Services"},
                         {"heading": "Enablement", "body": "Support"}],
            "quadrants": [{"heading": "One", "body": "First quadrant."},
                          {"heading": "Two", "body": "Second quadrant."},
                          {"heading": "Three", "body": "Third quadrant."},
                          {"heading": "Four", "body": "Fourth quadrant."}],
            "people": [{"name": "Alex Morgan", "role": "Strategy", "bio": "Short bio.",
                        "traits": ["A", "B", "C"], "contact": "alex@example.com"}],
            "stages": [{"heading": "Discover", "actions": [{"label": "Action", "text": "Does a thing"},
                                                           {"label": "Pain", "text": "Gets stuck"}]},
                       {"heading": "Buy", "actions": [{"label": "Action", "text": "Does a thing"}]}],
            "pairs": [{"question": "Is it a rewrite?", "answer": "No, the API stays the same."}],
            "rows": [["Row one", "1", "2"], ["Row two", "3", "4"]],
            "headers": ["Item", "Value", "Status"],
            "options": ["Option A", "Option B"],
            "features": [{"feature": "Speed", "values": ["Fast", "Slow"]}],
            "activities": [{"activity": "Agree scope", "values": ["A", "R"]}],
            "roles": ["Lead", "Eng"],
            "cols": ["Q1", "Q2"],
            "callouts": [{"label": "Edge", "body": "Entry point"}, {"label": "Core", "body": "Rules"}],
            "points": [{"label": "A", "x": 0.2, "y": 0.7}, {"label": "B", "x": 0.6, "y": 0.4}],
            "events": [{"date": "3", "heading": "Review"}, {"date": "9", "heading": "Launch"}],
            "tiers": [{"name": "Starter", "price": "$19", "features": ["One project"]},
                      {"name": "Growth", "price": "$49", "features": ["Ten projects"]}],
            "blocks": [{"heading": "Partners", "body": "Who we rely on"},
                       {"heading": "Activities", "body": "What we do"},
                       {"heading": "Resources", "body": "What we own"},
                       {"heading": "Value", "body": "What they get"},
                       {"heading": "Customers", "body": "Who we serve"},
                       {"heading": "Channels", "body": "How we reach"},
                       {"heading": "Segments", "body": "Market we win"},
                       {"heading": "Costs", "body": "What we spend"},
                       {"heading": "Revenue", "body": "What we earn"}],
            "left": {"heading": "Current", "bullets": ["a", "b", "c"]},
            "right": {"heading": "Future", "bullets": ["d", "e", "f"]},
            "result": {"value": "+27%", "label": "Outcome metric"},
            "metric": {"value": "4.8/5", "label": "Proof point"},
        }
        for line in user.splitlines():
            if line.strip().startswith('- "'):
                key = line.split('"')[1]
                if key in payload:
                    return _Resp(json.dumps(payload))
        return _Resp(json.dumps({"title": "Title", "bullets": ["a", "b", "c"]}))


def main():
    fake = FakeOllama()

    print("1) layout recommendation")
    picks = recommend_layouts(fake, "gpt-oss", "1. Intro\n2. Numbers\n3. Options",
                               [{"title": "Intro", "content": "opening"},
                                {"title": "Numbers", "content": "42% growth"},
                                {"title": "Options", "content": "A vs B"}])
    print("   ", picks)

    print("2) content structuring for 3 templates")
    for lid in ("L01", "L31", "L08"):
        tpl = get_template(lid)
        data = structure_for_layout(fake, "gpt-oss", tpl, "Slide title", "raw content here", "outline")
        print(f"    {lid} -> keys={sorted(data.keys())}")

    print("3) fallback coercion (no LLM)")
    for lid in ("L03", "L07", "L24", "L49"):
        tpl = get_template(lid)
        data = coerce_content(tpl, "Fallback title", "First line of content\nSecond line of content")
        print(f"    {lid} -> {flatten_content(data)[:70]!r}")

    print("4) template deck + catalogue")
    deck = build_template_deck()
    print("    deck:", deck, os.path.getsize(deck), "bytes")
    md = write_catalogue_markdown()
    print("    catalogue:", md, os.path.getsize(md), "bytes")

    print("5) per-slide generation (pptx + screenshot)")
    import gemini_code_fixed as g
    title, content = "Quarterly results", "Revenue grew 27%\nCosts fell by 11%\nChurn is at 3%"
    tpl = get_template("L05")
    data = structure_for_layout(fake, "gpt-oss", tpl, title, content, "outline")
    pptx, png = g.build_slide(tpl, data, 0)
    print("    pptx:", pptx, os.path.getsize(pptx), "bytes")
    print("    png :", png, os.path.getsize(png), "bytes")

    print("6) compile the whole deck")
    states = []
    for i in range(3):
        t = get_template(["L01", "L05", "L08"][i])
        d = structure_for_layout(fake, "gpt-oss", t, f"Slide {i+1}", "raw content", "outline")
        g.SLIDE_STRUCTURED[i] = d
        states.extend([f"Slide {i+1}", "raw content", t.label, ""])
    states.extend([""] * ((25 - 3) * 4))
    path, status = g.compile_presentation_file("TestDeck", *states)
    print("   ", path, os.path.getsize(path), "bytes")
    print("   ", status.encode("ascii", "replace").decode("ascii").replace("\n", " ")[:120])

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
