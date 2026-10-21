"""
Presentation layout engine for the Gradio presentation maker.

Dependencies:
    pip install gradio python-pptx pillow

Optional for exact PPTX-to-PNG screenshots:
    Install LibreOffice and ensure `soffice` is on PATH.
    Without it, a Pillow preview is generated from the same content/layout model.

The module keeps layout selection, LLM content structuring, PowerPoint rendering,
and preview generation separate. It uses existing ComfyUI slide artwork when found.
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, textwrap
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "presentation_output"
PREVIEW_DIR = ROOT / "layout_previews"
OUTPUT_DIR.mkdir(exist_ok=True)
PREVIEW_DIR.mkdir(exist_ok=True)
W, H = 13.333, 7.5
NAVY = (17,24,39); NAVY2=(31,42,61); BLUE=(37,99,235); CYAN=(6,182,212)
WHITE=(255,255,255); LIGHT=(248,250,252); TEXT=(55,65,81); MUTED=(107,114,128)
BORDER=(226,232,240); PALE=(234,241,255); GREEN=(16,185,129); AMBER=(245,158,11); RED=(239,68,68)
FONT_NAME = "Aptos"

# Existing 44 archetypes plus additional useful variants. IDs are stable for saved sessions.
_BASE = [
("L01","Modern Title","Opening / closing","Open with one clear promise.","title + subtitle"),
("L02","Standard Content","Core content","Explain one idea with a short narrative and supporting points.","paragraph + 3–5 bullets"),
("L03","3-Column Card Grid","Core content","Present three parallel pillars, features, or options.","three parallel items"),
("L04","Split Frame Hero","Core content","Pair a strong focal statement with supporting explanation.","focal phrase + explanation"),
("L05","Big Numbers Metric","Data / evidence","Emphasize two to four headline KPIs.","2–4 metrics"),
("L06","Timeline Flow","Process / sequence","Show milestones in chronological order.","3–6 milestones"),
("L07","Data Grid Table","Data / evidence","Compare structured values across rows and columns.","table or aligned records"),
("L08","Two-Column Contrast","Comparison","Compare alternatives, states, or pros and cons.","two option groups"),
("L09","Key Callout / Quote","Emphasis","Highlight a thesis, quote, or memorable insight.","quote + attribution"),
("L10","Process Pipeline Flow","Process / sequence","Explain a repeatable workflow with discrete stages.","3–6 ordered steps"),
("L11","Four-Quadrant Matrix","Frameworks","Organize a topic into four related dimensions.","four dimensions"),
("L12","Left-Heavy Editorial","Narrative","Lead with an argument and provide deeper explanation.","headline + narrative"),
("L13","Team & Bio Overview","People / organization","Introduce team members or stakeholders.","people + roles"),
("L14","Modern Outro","Opening / closing","Close with a decision, next step, or contact details.","closing statement + CTA"),
("L15","Agenda / Section Map","Navigation","Preview the talk or signal the structure of a long deck.","4–7 sections"),
("L16","Full-Bleed Image + Caption","Visual storytelling","Use artwork as the primary emotional or evidentiary anchor.","image + caption"),
("L17","Image + Text Split","Visual storytelling","Explain an object or concept with supporting imagery.","image + 3 points"),
("L18","Chart + Insight Panel","Data / evidence","Pair a chart with the audience takeaway.","chart + insight"),
("L19","Funnel / Conversion","Data / process","Show narrowing stages, conversion, or prioritization.","3–6 funnel stages"),
("L20","Pyramid / Maturity Levels","Frameworks","Show hierarchy or foundational-to-advanced progression.","3–5 ordered levels"),
("L21","Flywheel / Circular Cycle","Process / systems","Explain a reinforcing loop or recurring model.","cycle + outcome"),
("L22","Hub-and-Spoke Ecosystem","Systems / architecture","Show a central platform connected to related entities.","hub + connected nodes"),
("L23","Roadmap / Swimlane","Planning","Map initiatives across time and workstreams.","periods + workstreams"),
("L24","Risk / Impact Matrix","Decision support","Prioritize items using two variables.","items + likelihood + impact"),
("L25","Before / After Transformation","Comparison / change","Show the effect of a change or intervention.","before + after"),
("L26","Case Study / Proof Point","Evidence / narrative","Tell a compact challenge-action-result story.","challenge + action + result"),
("L27","Portfolio / Gallery Grid","Visual storytelling","Show examples, products, or visual directions.","4–6 visuals"),
("L28","Organization / Hierarchy Tree","People / systems","Explain reporting lines, ownership, or decomposition.","parent + children"),
("L29","Technical Architecture Map","Systems / architecture","Explain components, integrations, and data movement.","components + connections"),
("L30","SWOT Analysis","Frameworks","Summarize strengths, weaknesses, opportunities, and threats.","four SWOT categories"),
("L31","Scorecard / KPI Dashboard","Data / evidence","Monitor measures against targets or status.","4–6 KPIs"),
("L32","Waterfall / Bridge","Data / evidence","Explain how a starting value changes through drivers.","start + changes + end"),
("L33","Geographic / Regional Overview","Data / evidence","Compare regions, markets, or locations.","regions + values"),
("L34","Customer Journey Map","Experience / process","Show stages, actions, pain points, and opportunities.","stages + actions"),
("L35","Problem → Solution → Outcome","Narrative / persuasion","Make a persuasive case for an intervention.","problem + solution + outcome"),
("L36","Layered Stack / Platform","Systems / architecture","Explain layers of a platform or operating model.","3–6 layers"),
("L37","Decision Tree","Decision support","Explain a branching decision or diagnostic path.","question + branches"),
("L38","Ranked List / Priority Ladder","Decision support","Rank recommendations or opportunities.","3–7 ranked items"),
("L39","Quote + Evidence","Emphasis / evidence","Pair a human voice with supporting proof.","quote + metric"),
("L40","FAQ / Myth vs Fact","Education","Resolve questions or correct misconceptions.","3–5 Q&A pairs"),
("L41","Product / Feature Spotlight","Product / marketing","Explain one product capability or differentiator.","hero visual + callouts"),
("L42","Financial Snapshot","Data / evidence","Summarize revenue, cost, growth, margin, or budget.","financial KPIs + breakdown"),
("L43","Source / Methodology","Reference","Show how evidence was collected and interpreted.","sources + method + caveats"),
("L44","Appendix / Dense Reference","Reference","Place supporting detail outside the main narrative.","reference facts or table"),
("L45","Executive Summary","Executive / strategy","Summarize the decision, evidence, and recommended action on one slide.","takeaway + 3 points + ask"),
("L46","One Big Idea","Emphasis","Make a single thesis or strategic message memorable.","one statement + proof"),
("L47","Three-Act Story","Narrative","Structure a story as context, tension, resolution.","setup + tension + resolution"),
("L48","Milestone Gates","Planning / governance","Show stage gates, approvals, and exit criteria.","gates + criteria"),
("L49","Capability Map","Strategy / systems","Map capabilities by domain, maturity, or ownership.","capability groups"),
("L50","Value Chain","Strategy / operations","Show how activities create and deliver value.","ordered value stages"),
("L51","Operating Model","Organization / operations","Connect governance, people, process, data, and technology.","operating model components"),
("L52","Service Blueprint","Experience / operations","Connect customer actions to frontstage and backstage operations.","journey + support lanes"),
("L53","Product Lifecycle","Product / strategy","Show a product from discovery through retirement.","lifecycle stages"),
("L54","Market Segmentation","Market / strategy","Compare audience segments by need, size, or attractiveness.","segments + attributes"),
("L55","Competitive Positioning Map","Comparison / strategy","Plot alternatives across two meaningful dimensions.","competitors + two axes"),
("L56","Opportunity Prioritization","Decision support","Rank opportunities by value, effort, and strategic fit.","opportunities + scores"),
("L57","Scenario Planning","Strategy / risk","Compare plausible futures and their implications.","2–4 scenarios"),
("L58","Assumptions & Hypotheses","Strategy / validation","Make assumptions testable with evidence and experiments.","assumption + test + evidence"),
("L59","Implementation Plan","Planning / execution","Translate a recommendation into owners, dates, and actions.","actions + owners + timing"),
("L60","Decision / Approval","Decision support","Make the requested decision and consequences explicit.","decision + options + ask"),
]
LAYOUTS = [
    {"id":i,"name":n,"family":f,"best_for":b,"content_pattern":p,
     "implementation":f"{n}: use clear hierarchy, consistent spacing, readable typography, and editable native PowerPoint objects."}
    for i,n,f,b,p in _BASE
]
LAYOUT_BY_ID = {x["id"]:x for x in LAYOUTS}
LAYOUT_OPTIONS = [f'{x["id"]} — {x["name"]}' for x in LAYOUTS]
AUTO_LAYOUT = "AUTO — LLM recommendation"

def parse_layout_id(value: str) -> str:
    m = re.match(r"\s*(L\d{2})", str(value or ""))
    return m.group(1) if m else "L02"

def _font(size=18, bold=False):
    candidates = ["arialbd.ttf" if bold else "arial.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for candidate in candidates:
        for root in ["/usr/share/fonts/truetype/msttcorefonts", "/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts"]:
            try: return ImageFont.truetype(str(Path(root)/candidate), size)
            except Exception: pass
    return ImageFont.load_default()

def _find_artwork(index: int | None = None, explicit: str | None = None):
    if explicit and Path(explicit).is_file(): return Path(explicit)
    if index is not None:
        for p in [OUTPUT_DIR/f"slide_{index+1}_0.png", ROOT/f"slide_{index+1}_0.png",
                  OUTPUT_DIR/f"slide_{index+1}.png", ROOT/f"slide_{index+1}.png"]:
            if p.is_file(): return p
        # ComfyUI function may save using another extension/prefix.
        matches = list(ROOT.glob(f"slide_{index+1}*")) + list(OUTPUT_DIR.glob(f"slide_{index+1}*"))
        for p in matches:
            if p.suffix.lower() in {".png",".jpg",".jpeg",".webp"} and p.is_file(): return p
    return None

def _safe_text(value):
    if isinstance(value, list): return [str(x).strip().lstrip("•-* ").strip() for x in value if str(x).strip()]
    if isinstance(value, dict): return [f"{k}: {v}" for k,v in value.items()]
    if value is None: return []
    return [x.strip().lstrip("•-* ").strip() for x in str(value).splitlines() if x.strip()]

def recommend_layout(client, model, title, content, deck_outline=""):
    """Ask the local OpenAI-compatible model to recommend a catalogue layout."""
    choices = [{"id":x["id"],"name":x["name"],"best_for":x["best_for"],"pattern":x["content_pattern"]} for x in LAYOUTS]
    messages = [
      {"role":"system","content":"You are an expert presentation art director. Select the single best layout from the supplied catalogue. Return only JSON: {\"layout_id\":\"L##\",\"reason\":\"short reason\"}. Never invent an ID. Prefer a layout that fits the content's purpose and amount."},
      {"role":"user","content":json.dumps({"title":title,"content":content,"deck_outline":deck_outline,"layouts":choices},ensure_ascii=False)}
    ]
    try:
        r=client.chat.completions.create(model=model,messages=messages,response_format={"type":"json_object"})
        data=json.loads(r.choices[0].message.content)
        lid=str(data.get("layout_id","L02")).upper()
        if lid not in LAYOUT_BY_ID: lid="L02"
        return lid, str(data.get("reason","Recommended based on the content structure."))
    except Exception:
        return heuristic_layout(title, content), "Fallback recommendation because the local model did not return a valid layout."

def heuristic_layout(title, content):
    text=(str(title)+" "+str(content)).lower()
    tests=[
      (["swot"],"L30"),(["roadmap","quarter","timeline"],"L23"),(["architecture","integration","api","system"],"L29"),
      (["revenue","margin","budget","financial"],"L42"),(["kpi","metric","growth","percent","%"],"L31"),
      (["risk","impact","likelihood"],"L24"),(["before","after","transformation"],"L25"),
      (["process","workflow","steps"],"L10"),(["journey","customer experience"],"L34"),
      (["decision","approve","approval"],"L60"),(["team","leadership","people"],"L13"),
      (["agenda","sections"],"L15"),(["conclusion","thank you","next steps"],"L14"),
    ]
    for words,lid in tests:
        if any(w in text for w in words): return lid
    items=_safe_text(content)
    return "L03" if 3 <= len(items) <= 4 else "L02"

def structure_slide_content(client, model, title, content, layout_id, deck_title=""):
    """Fit slide copy to a selected layout while preserving factual meaning."""
    layout=LAYOUT_BY_ID.get(layout_id,LAYOUT_BY_ID["L02"])
    messages=[
      {"role":"system","content":(
       "You are a presentation content editor. Fit the supplied content to the chosen slide layout. "
       "Preserve all factual claims and numbers; never invent facts, sources, metrics, names, or dates. "
       "If data is missing, mark it as a placeholder such as [add source]. Be concise and presentation-ready. "
       "Return valid JSON with keys title (string), subtitle (string), takeaway (string), bullets (array of strings), "
       "sections (array of objects with heading and body), metrics (array of objects with value, label, context), "
       "steps (array of objects with label, detail), left_heading, left_items (array), right_heading, right_items (array), "
       "quote, attribution, source, notes. Use only relevant keys; arrays should be short and fit the layout."
      )},
      {"role":"user","content":json.dumps({"deck_title":deck_title,"title":title,"content":content,"layout":{"id":layout_id,"name":layout["name"],"purpose":layout["best_for"],"content_pattern":layout["content_pattern"]}},ensure_ascii=False)}
    ]
    r=client.chat.completions.create(model=model,messages=messages,response_format={"type":"json_object"})
    data=json.loads(r.choices[0].message.content)
    data["title"]=str(data.get("title") or title).strip()
    data["bullets"]=_safe_text(data.get("bullets") or content)[:7]
    for key in ("sections","metrics","steps"):
        if not isinstance(data.get(key),list): data[key]=[]
    return data

def _rgb(t): return RGBColor(int(t[0]),int(t[1]),int(t[2]))
def _shape(slide, x,y,w,h, fill=WHITE, line=BORDER, kind=MSO_SHAPE.ROUNDED_RECTANGLE):
    s=slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb=_rgb(fill)
    if line is None: s.line.fill.background()
    else: s.line.color.rgb=_rgb(line); s.line.width=Pt(0.8)
    return s
def _text(slide, txt, x,y,w,h, size=16, color=TEXT, bold=False, align=PP_ALIGN.LEFT):
    box=slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf=box.text_frame; tf.clear(); tf.word_wrap=True
    tf.margin_left=Inches(.04); tf.margin_right=Inches(.04); tf.margin_top=Inches(.025); tf.margin_bottom=Inches(.02)
    tf.vertical_anchor=MSO_ANCHOR.TOP
    p=tf.paragraphs[0]; p.text=str(txt or ""); p.alignment=align
    p.font.name=FONT_NAME; p.font.size=Pt(size); p.font.bold=bold; p.font.color.rgb=_rgb(color)
    return box
def _bullet_list(slide, items, x,y,w, max_h=3.8, size=17):
    items=items[:7] or ["Add supporting point"]
    line_h=min(.62,max_h/max(1,len(items)))
    for i,item in enumerate(items):
        yy=y+i*line_h
        _shape(slide,x,yy+.10,.09,.09,BLUE,None,MSO_SHAPE.OVAL)
        _text(slide,item,x+.22,yy,w-.22,line_h-.03,size,TEXT)

def _content(slide, data, x=0.9, y=2.0, w=11.55, h=4.8, layout_id="L02"):
    title=str(data.get("title","")).strip()
    subtitle=str(data.get("subtitle","")).strip()
    bullets=_safe_text(data.get("bullets"))[:7]
    sections=data.get("sections") or []
    steps=data.get("steps") or []
    metrics=data.get("metrics") or []
    if subtitle: _text(slide,subtitle,x,y,w,.5,16,MUTED)
    y0=y+(.55 if subtitle else 0)
    if layout_id in {"L03","L11","L30","L45","L47","L35","L40","L54","L57"}:
        n=4 if layout_id in {"L11","L30","L40","L45"} else 3
        items=sections or [{"heading":f"Key point {i+1}","body":b} for i,b in enumerate(bullets[:n])]
        items=items[:n] or [{"heading":"Key point","body":"Add supporting detail"}]
        cols=2 if n==4 else 3; rows=(len(items)+cols-1)//cols
        cw=(w-.22*(cols-1))/cols; ch=(h-.22*(rows-1))/rows
        for i,it in enumerate(items):
            if not isinstance(it,dict): it={"heading":f"Point {i+1}","body":str(it)}
            xx=x+(i%cols)*(cw+.22); yy=y0+(i//cols)*(ch+.22)
            fill=[PALE,(230,250,253),(231,248,240),(255,245,223)][i%4]
            _shape(slide,xx,yy,cw,ch,fill)
            _text(slide,it.get("heading",f"Point {i+1}"),xx+.2,yy+.2,cw-.4,.48,17,NAVY,True)
            _text(slide,it.get("body",""),xx+.2,yy+.82,cw-.4,max(.45,ch-1.0),13,TEXT)
    elif layout_id in {"L05","L31","L42"}:
        n=min(4,max(2,len(metrics) or 3)); items=metrics[:n]
        if not items: items=[{"value":f"[{i+1}]","label":b,"context":""} for i,b in enumerate((bullets+["Key metric"]*4)[:n])]
        cw=(w-.18*(n-1))/n
        for i,it in enumerate(items):
            if not isinstance(it,dict): it={"value":"","label":str(it)}
            xx=x+i*(cw+.18); _shape(slide,xx,y0,cw,1.8,WHITE)
            _text(slide,it.get("value","[value]"),xx+.2,y0+.25,cw-.4,.65,28,BLUE,True)
            _text(slide,it.get("label","Metric"),xx+.2,y0+1.0,cw-.4,.35,14,NAVY,True)
            _text(slide,it.get("context",""),xx+.2,y0+1.4,cw-.4,.3,10,MUTED)
        if bullets: _bullet_list(slide,bullets,x,y0+2.15,w,1.9,14)
    elif layout_id in {"L08","L25","L35","L47"}:
        halves=[(data.get("left_heading","Current / Option A"),data.get("left_items") or bullets[:3]),(data.get("right_heading","Future / Option B"),data.get("right_items") or bullets[3:6] or bullets[:3])]
        for i,(head,items) in enumerate(halves):
            xx=x+i*(w/2+.15); ww=(w-.15)/2
            _shape(slide,xx,y0,ww,h,PALE if i==0 else (230,250,253))
            _text(slide,head,xx+.25,y0+.25,ww-.5,.45,18,NAVY,True)
            _bullet_list(slide,_safe_text(items),xx+.25,y0+.9,ww-.5,h-1.1,14)
    elif layout_id in {"L06","L10","L19","L20","L23","L34","L48","L50","L53","L59"}:
        items=steps or [{"label":f"Step {i+1}","detail":b} for i,b in enumerate(bullets[:5])]
        items=items[:5] or [{"label":"Define","detail":"Add milestone"}]
        gap=.12; cw=(w-gap*(len(items)-1))/len(items)
        for i,it in enumerate(items):
            if not isinstance(it,dict): it={"label":str(it),"detail":""}
            xx=x+i*(cw+gap)
            _shape(slide,xx,y0+.3,cw,2.75,PALE if i%2==0 else WHITE)
            _shape(slide,xx+.15,y0+.5,.38,.38,BLUE,None,MSO_SHAPE.OVAL)
            _text(slide,str(i+1),xx+.15,y0+.55,.38,.22,10,WHITE,True,PP_ALIGN.CENTER)
            _text(slide,it.get("label","Stage"),xx+.15,y0+1.05,cw-.3,.55,14,NAVY,True)
            _text(slide,it.get("detail",""),xx+.15,y0+1.7,cw-.3,.95,11,TEXT)
    elif layout_id in {"L09","L39","L46"}:
        quote=data.get("quote") or data.get("takeaway") or (bullets[0] if bullets else title)
        _shape(slide,x,y0,w,h,PALE)
        _shape(slide,x,y0,.12,h,BLUE,None,MSO_SHAPE.RECTANGLE)
        _text(slide,quote,x+.45,y0+.55,w-.9,2.1,25,NAVY,True)
        _text(slide,data.get("attribution") or data.get("source") or "",x+.48,y0+3.0,w-.95,.5,13,MUTED)
        if layout_id=="L39" and metrics:
            _text(slide,str(metrics[0].get("value","")),x+w-2.5,y0+3.7,2.0,.5,22,BLUE,True)
    elif layout_id in {"L16","L17","L27","L33","L41"}:
        _shape(slide,x,y0,w*.54,h,(230,238,250))
        _text(slide,"ARTWORK / IMAGE AREA",x+.25,y0+h*.43,w*.5,.5,15,MUTED,True,PP_ALIGN.CENTER)
        _text(slide,data.get("takeaway") or "Key message",x+w*.59,y0+.15,w*.38,.6,18,NAVY,True)
        _bullet_list(slide,bullets,x+w*.59,y0+.95,w*.38,h-1.0,14)
    elif layout_id in {"L11","L24","L30","L55"}:
        coords=[(x,y0),(x+w/2+.05,y0),(x,y0+h/2+.05),(x+w/2+.05,y0+h/2+.05)]
        items=sections or [{"heading":f"Quadrant {i+1}","body":b} for i,b in enumerate((bullets+["Add detail"]*4)[:4])]
        for i,(xx,yy) in enumerate(coords):
            it=items[i] if i<len(items) else {"heading":f"Area {i+1}","body":""}
            if not isinstance(it,dict): it={"heading":str(it),"body":""}
            _shape(slide,xx,yy,(w-.1)/2,(h-.1)/2,[PALE,(255,245,223),(231,248,240),(254,236,236)][i])
            _text(slide,it.get("heading",""),xx+.2,yy+.2,(w-.1)/2-.4,.4,15,NAVY,True)
            _text(slide,it.get("body",""),xx+.2,yy+.75,(w-.1)/2-.4,.8,12,TEXT)
    elif layout_id in {"L07","L44","L43"}:
        items=sections or [{"heading":f"Reference {i+1}","body":b} for i,b in enumerate(bullets[:6])]
        for i,it in enumerate(items[:6]):
            if not isinstance(it,dict): it={"heading":f"Item {i+1}","body":str(it)}
            yy=y0+i*.62
            _shape(slide,x,yy,w,.52,PALE if i==0 else (WHITE if i%2 else LIGHT),BORDER,MSO_SHAPE.RECTANGLE)
            _text(slide,it.get("heading",""),x+.15,yy+.1,w*.32,.3,12,NAVY,True)
            _text(slide,it.get("body",""),x+w*.34,yy+.1,w*.63,.34,11,TEXT)
    else:
        _text(slide,data.get("takeaway",""),x,y0,w,.65,18,NAVY,True)
        _bullet_list(slide,bullets,x,y0+.8,w,h-.85,16)

def render_pptx_slide(title, data, layout_id, output_pptx, artwork_path=None, slide_number=1):
    prs=Presentation(); prs.slide_width=Inches(W); prs.slide_height=Inches(H)
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    dark=layout_id in {"L01","L14"}
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=_rgb(NAVY if dark else LIGHT)
    if artwork_path and Path(artwork_path).is_file():
        # Keep existing ComfyUI artwork as a full-bleed base; add a translucent-looking
        # opaque reading panel to preserve text contrast.
        # Tone down the AI artwork while keeping it visible behind the editable slide elements.
        try:
            softened = Image.open(artwork_path).convert("RGB").resize((1600,900))
            softened = Image.blend(softened, Image.new("RGB", softened.size, WHITE), 0.68)
            softened_path = OUTPUT_DIR / "softened_artwork_background.jpg"
            softened.save(softened_path, quality=90)
            slide.shapes.add_picture(str(softened_path),0,0,width=Inches(W),height=Inches(H))
        except Exception:
            slide.shapes.add_picture(str(artwork_path),0,0,width=Inches(W),height=Inches(H))
    if dark:
        _shape(slide,0,0,.16,H/1,BLUE,None,MSO_SHAPE.RECTANGLE)
        _text(slide,"PRESENTATION",.85,.65,8,.3,10,CYAN,True)
        _text(slide,data.get("title") or title,.85,1.45,11.5,1.35,34,WHITE,True)
        _text(slide,data.get("subtitle") or data.get("takeaway") or "",.88,3.0,10.5,1.0,19,WHITE)
        _text(slide,data.get("notes") or "",.88,5.3,10.5,.7,12,(190,200,215))
    else:
        _text(slide,LAYOUT_BY_ID.get(layout_id,LAYOUT_BY_ID["L02"])["family"].upper(),.82,.28,9.8,.25,9,BLUE,True)
        _text(slide,data.get("title") or title,.82,.62,11.3,.72,27,NAVY,True)
        _shape(slide,.82,1.48,.72,.045,BLUE,None,MSO_SHAPE.RECTANGLE)
        _text(slide,f"{slide_number:02d}",11.9,.32,.55,.25,10,MUTED,True,PP_ALIGN.RIGHT)
        _content(slide,data,x=.85,y=1.78,w=11.6,h=4.95,layout_id=layout_id)
    output_pptx=Path(output_pptx); output_pptx.parent.mkdir(parents=True,exist_ok=True); prs.save(output_pptx)
    return str(output_pptx)

def _preview_from_data(title, data, layout_id, destination, artwork_path=None):
    """Pillow preview fallback; dimensions mirror the widescreen slide."""
    im=Image.new("RGB",(1280,720),LIGHT); d=ImageDraw.Draw(im)
    if artwork_path and Path(artwork_path).is_file():
        try:
            bg=Image.open(artwork_path).convert("RGB").resize((1280,720))
            im=Image.blend(bg,Image.new("RGB",bg.size,WHITE),.76); d=ImageDraw.Draw(im)
        except Exception: pass
    lid=layout_id
    d.rectangle((0,0,1280,9),fill=BLUE)
    title_text=(data.get("title") or title)[:100]
    d.text((72,34),LAYOUT_BY_ID.get(lid,LAYOUT_BY_ID["L02"])["family"].upper(),font=_font(15,True),fill=BLUE)
    d.text((72,68),title_text,font=_font(34,True),fill=NAVY)
    bullets=_safe_text(data.get("bullets"))[:6]
    if lid in {"L03","L11","L30","L45","L47","L35","L40","L54","L57"}:
        items=data.get("sections") or [{"heading":f"Key point {i+1}","body":b} for i,b in enumerate(bullets[:4])]
        cols=2 if len(items)>3 else 3
        for i,it in enumerate(items[:6]):
            if not isinstance(it,dict): it={"heading":f"Point {i+1}","body":str(it)}
            x=72+(i%cols)*(1120//cols); y=170+(i//cols)*230; ww=1060//cols
            d.rounded_rectangle((x,y,x+ww,y+190),radius=15,fill=PALE if i%2==0 else (230,250,253),outline=BORDER,width=2)
            d.text((x+20,y+20),str(it.get("heading","Key point"))[:34],font=_font(20,True),fill=NAVY)
            for j,line in enumerate(textwrap.wrap(str(it.get("body","")),width=max(15,ww//10))[:4]):
                d.text((x+20,y+65+j*25),line,font=_font(15),fill=TEXT)
    else:
        if data.get("subtitle"): d.text((72,145),str(data["subtitle"])[:130],font=_font(18),fill=MUTED)
        y=190
        for b in bullets:
            d.ellipse((78,y+7,91,y+20),fill=BLUE)
            wrapped=textwrap.wrap(b,width=105)[:2]
            for j,line in enumerate(wrapped):
                d.text((110,y+j*27),line,font=_font(19),fill=TEXT)
            y+=72
    im.save(destination)
    return str(destination)

def create_template_previews(artwork_path=None):
    """Create selector thumbnails for every template, reusing artwork when available."""
    made=[]
    for layout in LAYOUTS:
        dest=PREVIEW_DIR/f'{layout["id"]}_{re.sub(r"[^a-z0-9]+","_",layout["name"].lower()).strip("_")}.png'
        sample={"title":layout["name"],"subtitle":layout["best_for"],
                "bullets":["Key point one","Supporting evidence","Implication / next step"],
                "sections":[{"heading":"Key point","body":"A concise supporting explanation."},{"heading":"Evidence","body":"One clear proof point."},{"heading":"Action","body":"What the audience should do next."}],
                "metrics":[{"value":"98.6%","label":"Reliability","context":"vs. target"},{"value":"+18%","label":"Growth","context":"year over year"},{"value":"2.4×","label":"Throughput","context":"vs. baseline"}]}
        _preview_from_data(layout["name"],sample,layout["id"],dest,artwork_path)
        made.append((str(dest),f'{layout["id"]} — {layout["name"]}'))
    return made

def generate_slide(client, model, title, content, selected_layout, slide_index=0, deck_title="", artwork_path=None):
    """Structure slide content, render editable PPTX, and refresh its PNG preview."""
    chosen=parse_layout_id(selected_layout)
    reason=""
    if str(selected_layout).startswith("AUTO") or not selected_layout:
        chosen,reason=recommend_layout(client,model,title,content,deck_title)
    data=structure_slide_content(client,model,title,content,chosen,deck_title)
    if reason: data["notes"]=f"LLM layout recommendation: {reason}"
    artwork=Path(artwork_path) if artwork_path and Path(artwork_path).is_file() else _find_artwork(slide_index)
    pptx_path=OUTPUT_DIR/f"slide_{slide_index+1}.pptx"
    png_path=ROOT/f"slide_{slide_index+1}_current.png"
    render_pptx_slide(title,data,chosen,pptx_path,artwork,slide_index+1)
    converted=False
    soffice=shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            pdf_dir=OUTPUT_DIR/"pdf_render"; pdf_dir.mkdir(exist_ok=True)
            subprocess.run([soffice,"--headless","--convert-to","pdf","--outdir",str(pdf_dir),str(pptx_path)],capture_output=True,timeout=90,check=True)
            pdf=pdf_dir/(pptx_path.stem+".pdf")
            pdftoppm=shutil.which("pdftoppm")
            if pdf.exists() and pdftoppm:
                subprocess.run([pdftoppm,"-f","1","-singlefile","-png","-r","110",str(pdf),str(OUTPUT_DIR/f"slide_{slide_index+1}_render")],capture_output=True,timeout=90,check=True)
                candidate=OUTPUT_DIR/f"slide_{slide_index+1}_render.png"
                if candidate.exists(): candidate.replace(png_path); converted=True
        except Exception:
            pass
    if not converted: _preview_from_data(title,data,chosen,png_path,artwork)
    return str(png_path),str(pptx_path),chosen,data,reason

def render_selector_previews():
    return create_template_previews(_find_artwork(0))
