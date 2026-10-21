"""Talks to Ollama and produces a validated Deck.

Pipeline: outline (1 call) -> one call per slide. Every call uses Ollama's
structured-output `format` parameter, so the reply is constrained to the
Pydantic schema, and is validated again (with retries) before use.
"""
from typing import Callable, Optional

import ollama
from pydantic import BaseModel, ValidationError

from schema import Deck, Outline, Slide

DEFAULT_MODEL = "gpt-oss"
# Keep the context modest: a big num_ctx eats VRAM and pushes layers onto the CPU.
OPTIONS = {"num_ctx": 8192, "temperature": 0.4}

SYSTEM = (
    "You write concise, clear presentation content. Bullets are short phrases "
    "(max 12 words), not full paragraphs. Do not number the bullets. "
    "Respond only with JSON matching the requested schema."
)


def list_models() -> list[str]:
    """Names of models already pulled into the local Ollama."""
    try:
        resp = ollama.list()
        models = getattr(resp, "models", None) or resp.get("models", [])
        names = []
        for m in models:
            name = getattr(m, "model", None) or m.get("model") or m.get("name")
            if name:
                names.append(name)
        return sorted(names)
    except Exception:
        return []


def _ask(user: str, schema: type[BaseModel], model: str, retries: int = 3) -> BaseModel:
    last_error: Optional[Exception] = None
    prompt = user
    for _ in range(retries):
        resp = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            format=schema.model_json_schema(),
            options=OPTIONS,
        )
        content = resp["message"]["content"] if isinstance(resp, dict) else resp.message.content
        try:
            return schema.model_validate_json(content)
        except ValidationError as e:
            last_error = e
            prompt = f"{user}\n\nYour previous reply was invalid ({e.error_count()} errors). Follow the schema exactly."
    raise RuntimeError(f"Model did not return valid JSON after {retries} tries: {last_error}")


def make_outline(topic: str, audience: str, n_slides: int, model: str = DEFAULT_MODEL) -> Outline:
    outline = _ask(
        f"Create an outline for a presentation.\n"
        f"Topic: {topic}\nAudience: {audience}\n"
        f"Return a title and exactly {n_slides} content slide titles with a logical flow "
        f"(intro, main points, conclusion/next steps).",
        Outline,
        model,
    )
    outline.slide_titles = outline.slide_titles[:n_slides]
    return outline


def make_slide(
    deck_title: str,
    slide_title: str,
    position: int,
    all_titles: list[str],
    audience: str,
    model: str = DEFAULT_MODEL,
) -> Slide:
    overview = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(all_titles))
    slide = _ask(
        f"Deck: {deck_title}\nAudience: {audience}\nFull outline:\n{overview}\n\n"
        f"Write slide {position + 1}: \"{slide_title}\".\n"
        f"Use layout 'bullets' (3-5 bullets) unless the content is a clear two-sided "
        f"comparison, then use 'two_column' and fill right_bullets too. "
        f"Add 2-4 sentences of speaker notes. Keep the title exactly as given.",
        Slide,
        model,
    )
    slide.title = slide_title
    return clean_slide(slide)


def clean_slide(slide: Slide) -> Slide:
    """Hard limits so slides never overflow, whatever the model did."""
    slide.bullets = [b.strip().lstrip("-•* ").strip() for b in slide.bullets if b.strip()][:6]
    slide.right_bullets = [b.strip().lstrip("-•* ").strip() for b in slide.right_bullets if b.strip()][:6]
    if slide.layout == "two_column" and not slide.right_bullets:
        slide.layout = "bullets"
    return slide


def build_deck(
    topic: str,
    audience: str = "general audience",
    n_slides: int = 8,
    model: str = DEFAULT_MODEL,
    outline: Optional[Outline] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Deck:
    """Generate a full deck. Pass `outline` to reuse one the user already edited."""
    outline = outline or make_outline(topic, audience, n_slides, model)
    total = len(outline.slide_titles)
    slides = []
    for i, title in enumerate(outline.slide_titles):
        if progress:
            progress(i, total, title)
        slides.append(make_slide(outline.title, title, i, outline.slide_titles, audience, model))
    if progress:
        progress(total, total, "done")
    return Deck(title=outline.title, subtitle=audience, slides=slides)


if __name__ == "__main__":
    import sys

    topic = " ".join(sys.argv[1:]) or "Introduction to renewable energy"
    deck = build_deck(topic, progress=lambda i, n, t: print(f"[{i}/{n}] {t}"))
    print(deck.model_dump_json(indent=2))
