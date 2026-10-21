"""Local presentation maker UI.  Run:  streamlit run app.py"""
import tempfile
from pathlib import Path

import streamlit as st

from generate import DEFAULT_MODEL, build_deck, list_models, make_outline
from render_pptx import export_pdf, render_pptx
from schema import Deck, Outline

st.set_page_config(page_title="Local Deck Maker", page_icon="📊", layout="wide")
# st.set_page_config(layout="wide")
st.title("📊 Local Deck Maker")
st.caption("Runs entirely on your machine through Ollama.")

models = list_models()

with st.sidebar:
    st.header("Settings")
    if models:
        default = models.index(DEFAULT_MODEL) if DEFAULT_MODEL in models else 0
        model = st.selectbox("Model", models, index=default)
    else:
        st.warning("No Ollama models found. Is Ollama running? Try `ollama pull qwen2.5:14b`.")
        model = st.text_input("Model", DEFAULT_MODEL)
    n_slides = st.slider("Content slides (0 to let model decide)", 0, 25, 8)

topic = st.text_area("What is the presentation about?", height=90, width="stretch",
                     placeholder="e.g. Quarterly security review for the engineering team")
audience = st.text_input("Audience", "general audience")

# ---- Step 1: outline ------------------------------------------------------
if st.button("1. Generate outline", disabled=not topic.strip()):
    with st.spinner("Writing outline..."):
        try:
            st.session_state["outline"] = make_outline(topic, audience, n_slides, model)
            st.session_state.pop("deck", None)
        except Exception as e:
            st.error(str(e))

if "outline" in st.session_state:
    outline: Outline = st.session_state["outline"]
    st.subheader("Outline (edit before generating)")
    title = st.text_input("Deck title", outline.title)
    titles_text = st.text_area("Slide titles, one per line",
                               "\n".join(outline.slide_titles), height=220)
    edited = Outline(title=title, slide_titles=[t.strip() for t in titles_text.splitlines() if t.strip()])

    # ---- Step 2: slides ---------------------------------------------------
    if st.button("2. Generate slides"):
        bar = st.progress(0.0, text="Starting...")

        def progress(i: int, total: int, name: str) -> None:
            bar.progress(i / total, text=f"Slide {min(i + 1, total)}/{total}: {name}")

        try:
            st.session_state["deck"] = build_deck(topic, audience, model=model,
                                                  outline=edited, progress=progress)
        except Exception as e:
            st.error(str(e))
        bar.empty()

# ---- Step 3: review, regenerate, export ------------------------------------
if "deck" in st.session_state:
    deck: Deck = st.session_state["deck"]
    st.subheader("Review")
    for i, slide in enumerate(deck.slides):
        with st.expander(f"{i + 1}. {slide.title}"):
            slide.title = st.text_input("Title", slide.title, key=f"t{i}")
            slide.bullets = [b for b in st.text_area(
                "Bullets (one per line)", "\n".join(slide.bullets), key=f"b{i}").splitlines() if b.strip()]
            if slide.layout == "two_column":
                slide.right_bullets = [b for b in st.text_area(
                    "Right column", "\n".join(slide.right_bullets), key=f"r{i}").splitlines() if b.strip()]
            slide.notes = st.text_area("Speaker notes", slide.notes, key=f"n{i}")

    out_dir = Path(tempfile.mkdtemp(prefix="deck_"))
    pptx_path = render_pptx(deck, out_dir / "presentation.pptx")
    col1, col2 = st.columns(2)
    col1.download_button("⬇️ Download .pptx", pptx_path.read_bytes(),
                         file_name="presentation.pptx",
                         mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")
    try:
        pdf_path = export_pdf(pptx_path)
    except Exception:
        pdf_path = None
    if pdf_path:
        col2.download_button("⬇️ Download PDF", pdf_path.read_bytes(),
                             file_name="presentation.pdf", mime="application/pdf")
    else:
        col2.caption("Install LibreOffice to enable PDF export.")
