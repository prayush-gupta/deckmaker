"""Optional web-grounded research enrichment for presentation slides.

Uses the local Ollama model to select a small number of high-value research
questions, then calls OpenAI Responses web search and/or Gemini Google Search
only for those questions. Configure OPENAI_API_KEY and/or GEMINI_API_KEY.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Load this project's .env even when the module is imported outside app.py.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

try:
    MAX_QUERIES = max(0, min(6, int(os.getenv("RESEARCH_MAX_QUERIES", "3"))))
except (TypeError, ValueError):
    MAX_QUERIES = 3
OPENAI_RESEARCH_MODEL = os.getenv("OPENAI_RESEARCH_MODEL", "gpt-4.1-mini")
# Try a sequence of Gemini models. Keep this configurable because model availability
# and free-tier quotas can vary by API project and change over time.
_DEFAULT_GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]

def _gemini_api_key() -> str:
    """Accept the common Google/Gemini API-key environment variable names."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""

def _gemini_model_chain() -> List[str]:
    configured = os.getenv("GEMINI_RESEARCH_MODELS", "").strip()
    models = [m.strip() for m in configured.split(",") if m.strip()] if configured else list(_DEFAULT_GEMINI_MODELS)
    # Preserve the legacy single-model setting as a preferred first attempt.
    preferred = os.getenv("GEMINI_RESEARCH_MODEL", "").strip()
    if preferred:
        models = [preferred] + [m for m in models if m != preferred]
    # Stable dedupe and never attempt an empty model name.
    return list(dict.fromkeys(m for m in models if m))


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 60) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", **(headers or {})
    }, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _extract_json(text: str) -> Any:
    from llm_helpers import extract_json
    return extract_json(text)


def plan_research_queries(ollama, model: str, deck_outline: str,
                          slides: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Ask the local model to identify only the highest-value evidence gaps."""
    if MAX_QUERIES <= 0 or not slides:
        return []
    compact_slides = [{"slide_number": i + 1, "title": s.get("title", ""),
                       "content": (s.get("content", "") or "")[:900]}
                      for i, s in enumerate(slides)]
    system = (
        "You are a rigorous presentation fact-checking researcher. Identify only the few "
        "research questions whose answers would materially improve the presentation with "
        "useful quantitative figures, benchmarks, market sizes, outcomes, or comparisons. "
        "Do not invent answers. Prefer questions answerable from credible public sources. "
        "Return ONLY JSON: {\"queries\":[{\"slide_number\":1,\"question\":\"...\","
        "\"why\":\"...\"}]}. Select 0 to the requested maximum questions, avoid duplicates, "
        "and use valid slide numbers."
    )
    user = (f"Maximum queries: {MAX_QUERIES}\nDeck outline:\n{deck_outline}\n"
            f"Slides:\n{json.dumps(compact_slides, ensure_ascii=False)}\n"
            "Choose questions that add concrete, verifiable value; avoid generic background research.")
    from llm_helpers import robust_chat_completion
    response = robust_chat_completion(
        ollama, model,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"}, temperature=0.2, max_tokens=2048,
    )
    parsed = _extract_json(response.choices[0].message.content or "{}")
    raw = parsed.get("queries", []) if isinstance(parsed, dict) else []
    result = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            slide_no = int(entry.get("slide_number", 0))
        except (TypeError, ValueError):
            continue
        question = " ".join(str(entry.get("question", "")).split())
        if 1 <= slide_no <= len(slides) and question:
            result.append({"slide_number": slide_no, "question": question[:500],
                           "why": " ".join(str(entry.get("why", "")).split())[:240]})
        if len(result) >= MAX_QUERIES:
            break
    return result


def _openai_research(question: str) -> Tuple[str, List[Dict[str, str]]]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return "", []
    prompt = (
        "Research this specific question for a presentation using web search. Prioritize primary, "
        "official, or reputable sources. Return 1-3 concise findings, especially useful numerical "
        "figures with units, geography, date/year, and context. Do not guess. If evidence is weak, "
        "say so. Keep the response under 180 words.\nQuestion: " + question
    )
    payload = {
        "model": OPENAI_RESEARCH_MODEL,
        "tools": [{"type": "web_search"}],
        "input": prompt,
    }
    data = _post_json("https://api.openai.com/v1/responses", payload,
                      {"Authorization": f"Bearer {key}"})
    text_parts, sources = [], []
    if isinstance(data.get("output_text"), str):
        text_parts.append(data["output_text"])
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text") and part.get("text"):
                if not text_parts or part["text"] not in text_parts:
                    text_parts.append(part["text"])
            for ann in part.get("annotations", []) or []:
                citation = ann.get("url_citation") or ann
                url = citation.get("url")
                if url:
                    sources.append({"title": str(citation.get("title") or _domain(url)), "url": url,
                                    "provider": "OpenAI web search"})
    return "\n".join(text_parts).strip(), _dedupe_sources(sources)


def _gemini_research(question: str) -> Tuple[str, List[Dict[str, str]]]:
    """Try configured Gemini models in order and return only search-grounded results."""
    key = _gemini_api_key()
    if not key:
        raise RuntimeError(
            "Gemini API key not found. Add GEMINI_API_KEY=... to the project's .env "
            "(or set GOOGLE_API_KEY) and restart the app. Having Gemini available in a browser "
            "does not automatically configure API access for this application."
        )
    prompt = (
        "Research this specific question for a presentation using Google Search grounding. "
        "Prioritize primary, official, or reputable sources. Return 1-3 concise findings, especially "
        "useful numerical figures with units, geography, date/year, and context. Do not guess. "
        "If evidence is weak, say so. Keep the response under 180 words.\nQuestion: " + question
    )
    failures = []
    for model_name in _gemini_model_chain():
        model = urllib.parse.quote(model_name, safe=".-")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
               f"?key={urllib.parse.quote(key)}")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
        }
        try:
            data = _post_json(url, payload, timeout=75)
            text_parts, sources = [], []
            for candidate in data.get("candidates", []) or []:
                for part in (candidate.get("content", {}) or {}).get("parts", []) or []:
                    if part.get("text"):
                        text_parts.append(part["text"])
                metadata = candidate.get("groundingMetadata", {}) or {}
                for chunk in metadata.get("groundingChunks", []) or []:
                    web = chunk.get("web", {}) or {}
                    source_url = web.get("uri")
                    if source_url:
                        sources.append({"title": str(web.get("title") or _domain(source_url)),
                                        "url": source_url, "provider": f"Gemini ({model_name}) Google Search"})
            answer = "\n".join(text_parts).strip()
            sources = _dedupe_sources(sources)
            # The deck only accepts grounded research, so continue to the next model if
            # this model returned no usable answer or no source URLs.
            if answer and sources:
                print(f"[research] Gemini model succeeded: {model_name}")
                return answer, sources
            failures.append(f"{model_name}: no answer or no grounded source URLs")
        except Exception as exc:
            failures.append(f"{model_name}: {exc}")
            print(f"[research] Gemini model {model_name} failed; trying fallback: {exc}")
    raise RuntimeError("All configured Gemini research models failed. " + " | ".join(failures)[:1800])


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.removeprefix("www.")
    except Exception:
        return url


def _dedupe_sources(sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen, out = set(), []
    for source in sources:
        url = str(source.get("url", "")).strip()
        if not url or not url.startswith(("http://", "https://")):
            continue
        key = url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        source["title"] = re.sub(r"\s+", " ", str(source.get("title", "Source"))).strip()[:100]
        out.append(source)
    return out


def enrich_slides_with_research(ollama, model: str, deck_outline: str,
                                slides: List[Dict[str, str]]) -> Tuple[List[Dict[str, str]], Dict[int, dict], str]:
    """Append researched evidence to selected slides and return slide-indexed citations.

    The slide index keys in the returned source map are zero-based. If neither API key is
    configured, no network calls are made and slide text remains unchanged.
    """
    try:
        queries = plan_research_queries(ollama, model, deck_outline, slides)
    except Exception as exc:
        return slides, {}, f"Research planning failed: {exc}"
    if not queries:
        return slides, {}, "No additional research questions were recommended for this deck."
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key = _gemini_api_key()
    if not openai_key and not gemini_key:
        questions = "; ".join(q["question"] for q in queries[:3])
        print(f"[research] No online research API key was detected. Suggested questions: {questions}")
        return slides, {}, (f"The local LLM suggested {len(queries)} research question(s), but no online API key "
                            "was detected by this process. For Gemini, add GEMINI_API_KEY=... to the .env "
                            "file next to app.py (or set GOOGLE_API_KEY), then fully restart the app. "
                            "A Gemini web/app subscription does not automatically provide API credentials.")

    enriched = [dict(s) for s in slides]
    source_map: Dict[int, dict] = {}
    findings_count = 0
    providers = []
    if openai_key:
        providers.append(("OpenAI", _openai_research))
    if gemini_key:
        providers.append(("Gemini", _gemini_research))

    for item in queries:
        slide_idx = item["slide_number"] - 1
        evidence_lines, sources = [], []
        for provider_name, fetch in providers:
            try:
                answer, found_sources = fetch(item["question"])
                # Only include a provider's findings when it supplied actual source URLs;
                # an ungrounded answer should not become a statistic in the deck.
                if answer and found_sources:
                    evidence_lines.append(f"{provider_name} research: {answer}")
                sources.extend(found_sources)
            except Exception as exc:
                print(f"[research] {provider_name} failed for slide {slide_idx + 1}: {exc}")
        sources = _dedupe_sources(sources)
        if evidence_lines:
            evidence = "\n\nEvidence from targeted web research (retain dates, units, and caveats):\n" + "\n".join(evidence_lines)
            enriched[slide_idx]["content"] = (enriched[slide_idx].get("content", "") or "").rstrip() + evidence
            findings_count += len(evidence_lines)
        if sources:
            existing = source_map.setdefault(slide_idx, {"sources": [], "questions": []})
            existing["sources"] = _dedupe_sources(existing["sources"] + sources)[:4]
            existing["questions"].append(item["question"])

    providers_text = " + ".join(name for name, _ in providers)
    return enriched, source_map, f"Research complete: {len(queries)} targeted question(s), {findings_count} provider finding(s) via {providers_text}."
