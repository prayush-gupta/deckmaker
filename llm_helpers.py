### This code loads the relevant Local or web model as per the use case

import os
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
import re
import json
import gradio as gr
from prompts import folder_name_prompt
from datetime import datetime

load_dotenv(Path(__file__).resolve().parent / ".env")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "gpt-oss")


def robust_chat_completion(ollama, model, messages, response_format=None, temperature=0, max_tokens=4096):
    """Call Ollama with compatibility fallbacks and retry empty final-content responses.

    GPT-OSS can expose reasoning separately from final content. Never treat the reasoning
    field as user-facing output; instead retry with reasoning disabled where supported.
    """
    base = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens:
        base["max_tokens"] = max_tokens
    variants = []
    if response_format:
        variants.append({**base, "response_format": response_format, "reasoning_effort": "none"})
        variants.append({**base, "response_format": response_format})
    variants.append({**base, "reasoning_effort": "none"})
    variants.append(dict(base))
    # Older Ollama-compatible endpoints may reject max_tokens; keep a final minimal request.
    minimal = {"model": model, "messages": messages, "temperature": temperature}
    variants.append(minimal)
    variants.append({"model": model, "messages": messages})
    errors = []
    for attempt, kwargs in enumerate(variants, 1):
        try:
            response = ollama.chat.completions.create(**kwargs)
            choice = response.choices[0] if getattr(response, "choices", None) else None
            message = getattr(choice, "message", None) if choice else None
            content = getattr(message, "content", None) if message else None
            if isinstance(content, str) and content.strip():
                visible_content = re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I)
                visible_content = re.sub(r"<think>.*$", "", visible_content, flags=re.S | re.I).strip()
                if visible_content:
                    return response
            reasoning = (getattr(message, "reasoning", None) or getattr(message, "thinking", None)) if message else None
            finish_reason = getattr(choice, "finish_reason", None) if choice else None
            usage = getattr(response, "usage", None)
            token_summary = "unknown"
            if usage is not None:
                prompt_tokens = getattr(usage, "prompt_tokens", None)
                completion_tokens = getattr(usage, "completion_tokens", None)
                total_tokens = getattr(usage, "total_tokens", None)
                token_summary = f"prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}"
            diagnostic = (f"attempt {attempt}: empty final content (reasoning={'present' if reasoning else 'absent'}, "
                          f"finish_reason={finish_reason}, tokens={token_summary})")
            print(f"[ollama] {model}: {diagnostic}")
            errors.append(diagnostic)
        except Exception as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {str(exc)[:180]}")
    raise RuntimeError(
        f"Ollama model '{model}' returned no usable final content after {len(variants)} compatible request attempts. "
        + " | ".join(errors[-4:])
    )


# This function generates the model feedback based on the input prompt

def response_generator(ollama, model, prompt):
    response = robust_chat_completion(ollama, model, prompt, temperature=0, max_tokens=1024)
    return response.choices[0].message.content



def folders_setup(ollama, slide_outline, model=DEFAULT_OLLAMA_MODEL):

    raw_name = response_generator(ollama, model, [
        {"role": "system", "content": folder_name_prompt()},
        {"role": "user", "content": slide_outline}
        ])
    # The model's reply becomes a folder AND session name: strip think-blocks, quotes, path
    # separators and characters Windows forbids, so saving/resuming works reliably.
    raw_name = re.sub(r"<think>.*?</think>", "", raw_name or "", flags=re.S | re.I).strip().splitlines()
    raw_name = raw_name[0] if raw_name else ""
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", raw_name)
    safe_name = re.sub(r"\s+", "-", safe_name.strip(" .-_'\"`*#")).strip("-")[:48] or "Presentation"
    PPT_DIR_FOLDER = "generated_presentations/" + safe_name

    if Path(PPT_DIR_FOLDER).exists():
        PPT_DIR_FOLDER = PPT_DIR_FOLDER + "-" + datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

    print(PPT_DIR_FOLDER)

    ARCHIVE_DIR = PPT_DIR_FOLDER+"/archive"
    SESSIONS_DIR = PPT_DIR_FOLDER+"/presentation_sessions"
    SLIDE_PREVIEW_DIR = PPT_DIR_FOLDER+"/slide_previews"
    SLIDE_LAYOUTS = PPT_DIR_FOLDER+"/slide_layouts"

    os.makedirs(PPT_DIR_FOLDER, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    os.makedirs(SLIDE_PREVIEW_DIR, exist_ok=True)
    os.makedirs(SLIDE_LAYOUTS, exist_ok=True)

    return PPT_DIR_FOLDER, ARCHIVE_DIR, SESSIONS_DIR, SLIDE_PREVIEW_DIR, SLIDE_LAYOUTS

# This function creates the format for a combined prompt

# Prompt Engineering

def first_prompt(system_prompt, user_prompt_prefix, user_input, slide_count):

    if slide_count > 0:
        user_input_2 = f"""
        The presentation should contain {slide_count} slides.
        """
    else:
        user_input_2 = ""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_prefix + user_input + user_input_2}
    ]

def response_append(prompt, new_text, role):
    return prompt + [{"role": role, "content": new_text}]


def slide_outline(title: str, slides: list[str]) -> str:
    lines = [f"# {title}"] + [f"{n}. {s}" for n, s in enumerate(slides, 1)]
    return "\n".join(lines)

def remove_prefix_numbers(items):
    return [re.sub(r'^\d+\.\s*', '', item).strip() for item in items]


def title_list(ollama, global_prompt, model=DEFAULT_OLLAMA_MODEL):

    prompt = f"""

    You are a helpful assistant that only answers to the point and responds with the exact information that is asked for, in minimum number of words possible.
    Share only the approved slide titles from the conversation transcript for the all slides in order of the slide number.
    No other information should be included in this response, there should not be any headers etc included either.

    Conversation Transcript:
    ---
    {global_prompt}
    ---
    """

    response = robust_chat_completion(
        ollama, model, [{"role": "system", "content": prompt}],
        temperature=0, max_tokens=2048,
    )
    return remove_prefix_numbers(response.choices[0].message.content.split("\n"))



def content_list(ollama, response, model=DEFAULT_OLLAMA_MODEL):

    prompt = f"""

    You are a very supportive assistant that helps the user in creating a presentation deck for them to use for their work.
    You will review the attached conversation and reply with detailed descrriptions of the content that should be included in each of the slides. 
    You will respond back with slide contents in detail including:
    
    1. Slide Contents including explanations, description, key facts and figures.
    2. The slide needs to have a consistent story based on the overall slide flows.
    3. Also highlight key pieces of data/figures/trends that should be highlighted and included in each slide 
    even if we do not have the data readily available since that can be extracted via separate web search calls.
    
    Share the detailed content for the all slides in order of the slide number and DO NOT include any reference to the slide number or title as that information is captured separately.
    Each slide description should start with ` except for the first slide. There should only be one ` per slide.

    Conversation Transcript:
    ---
    {response}
    ---
    """

    slide_content_raw = robust_chat_completion(
        ollama, model, [{"role": "system", "content": prompt}],
        temperature=0, max_tokens=4096,
    ).choices[0].message.content
    
    slide_content_stg = slide_content_raw.split('`')

    slide_content = [text for text in slide_content_stg if len(text.strip()) >= 5]

    return slide_content


def extract_json(text):
    """Extract a JSON object/array from an LLM reply, including fenced or narrated output.

    Handles common local-model quirks: <think> blocks, markdown fences, leading
    commentary, and JSON embedded in surrounding text. Raises a diagnostic error
    with a short reply excerpt when no JSON can be recovered.
    """
    if text is None:
        text = ""
    if not isinstance(text, str):
        text = str(text)

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    # Some reasoning models return an unclosed think block; don't try to parse it.
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.S | re.I)
    cleaned = re.sub(r"```\s*(?:json|JSON)?\s*", "", cleaned)
    cleaned = cleaned.replace("```", "").strip()

    if not cleaned:
        excerpt = (text.strip()[:400] or "<empty response>").replace("\n", " ")
        raise ValueError(f"Model reply was empty after removing reasoning markup. Reply excerpt: {excerpt}")

    # First try the whole response (works for clean JSON objects and arrays).
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass

    # Then scan for the first balanced object/array, rather than greedily taking
    # everything from the first '{' to the final '}' (which breaks on commentary).
    for start, char in enumerate(cleaned):
        if char not in "{[":
            continue
        closing = "}" if char == "{" else "]"
        stack = []
        in_string = False
        escaped = False
        for idx in range(start, len(cleaned)):
            current = cleaned[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                stack.append("}")
            elif current == "[":
                stack.append("]")
            elif current in "}]":
                if not stack or stack[-1] != current:
                    break
                stack.pop()
                if not stack:
                    candidate = cleaned[start:idx + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    excerpt = re.sub(r"\s+", " ", cleaned[:500]).strip()
    raise ValueError(f"No valid JSON object or array found in model reply. Reply excerpt: {excerpt or '<empty>'}")


def transcript_text(messages):
    """Readable transcript (user/assistant turns only) from an OpenAI-style message list."""
    lines = []
    for m in messages or []:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            lines.append(f"{m['role'].capitalize()}: {m['content']}")
    return "\n\n".join(lines)


_OUTLINE_LINE = re.compile(
    r"^\s*(?:[-*\u2022]\s*)?(?:\*\*|__)?\s*(?:slide\s*)?(\d{1,2})\s*[.:)\-\u2013]\s*(?:\*\*|__)?\s*(.+?)\s*$",
    re.I,
)


def outline_titles_from_conversation(messages):
    """Return the slide titles of the most recent numbered outline in the assistant turns."""
    for m in reversed(messages or []):
        if not (isinstance(m, dict) and m.get("role") == "assistant" and m.get("content")):
            continue
        found = {}
        for line in str(m["content"]).splitlines():
            hit = _OUTLINE_LINE.match(line)
            if hit:
                raw_title = re.sub(r"^slide\s*\d+\s*[:.\-\u2013]\s*", "", hit.group(2), flags=re.I)
                title = re.split(r"\s+[\u2013\u2014-]\s+|:\s", raw_title.replace("**", "").replace("__", ""), maxsplit=1)[0]
                found.setdefault(int(hit.group(1)), title.strip(" *_\"'"))
        if len(found) >= 2:
            return [found[k] for k in sorted(found)]
    return []


def _single_slide(ollama, model, transcript, number, total, title):
    """Generate one slide on its own (used to fill gaps when the model returned too few slides)."""
    msgs = [
        {"role": "system", "content": (
            "You write one slide of a presentation. Return one JSON object only: "
            '{"title": "...", "content": ["bullet", "bullet", "bullet"]} with 3-6 concise bullets '
            "(about 18 words max each), no bullet characters.\n\nConversation Transcript:\n---\n"
            f"{transcript}\n---")},
        {"role": "user", "content": f"Write slide {number} of {total}, titled: {title}"},
    ]
    resp = robust_chat_completion(
        ollama, model, msgs, response_format={"type": "json_object"},
        temperature=0, max_tokens=2048,
    )
    data = extract_json(resp.choices[0].message.content)
    if isinstance(data, dict) and isinstance(data.get("slides"), list) and data["slides"]:
        data = data["slides"][0]
    content = data.get("content", "") if isinstance(data, dict) else ""
    if isinstance(content, list):
        content = "\n".join(f"\u2022 {str(l).strip().lstrip('\u2022-* ').strip()}" for l in content if str(l).strip())
    return (title, str(content).strip())


def slides_from_conversation(ollama, messages, model=DEFAULT_OLLAMA_MODEL, max_slides=25, expected_titles=None):
    """Generate aligned (title, content) slide tuples, with robust JSON retries.

    When ``expected_titles`` (the approved outline) is given, exactly that many slides are
    produced, in that order; any slide the model leaves out is generated individually.
    """
    transcript = transcript_text(messages)
    expected_titles = list(expected_titles or [])[:max_slides]
    if expected_titles:
        max_slides = len(expected_titles)
        count_rule = (f'- "slides" MUST contain EXACTLY {max_slides} slide objects, one per outline item, in this order:\n'
                      + "\n".join(f"  {i}. {t}" for i, t in enumerate(expected_titles, 1))
                      + "\n- Never merge, skip, or stop after the first slide.")
    else:
        count_rule = f'- "slides" must be an array containing between 1 and {max_slides} slide objects (one per outline item).'
    prompt = f"""
You are a professional presentation content writer. Read the transcript and produce the final
slides for the deck in the approved outline's order. Return one valid JSON object only.
Do not include markdown fences, explanations, analysis, or <think> text in the final answer.

Required schema:
{{"slides": [{{"title": "Short slide title", "content": ["Bullet 1", "Bullet 2", "Bullet 3"]}}]}}

Rules:
- Return a JSON object with a top-level key named "slides".
{count_rule}
- Each slide object must have a non-empty string "title" and a "content" array of 3 to 6 concise strings.
- Titles should be max 8 words. Each bullet should be around 18 words or fewer.
- Do not include slide numbers or bullet characters in strings.
- Keep the same order and story as the approved outline; avoid repeating information.

Conversation Transcript:
---
{transcript}
---
""".strip()

    retry_prompt = prompt + """

FINAL OUTPUT REQUIREMENT: Your entire response must be parseable by json.loads().
Start with { and end with }. Use double quotes for every key and string. No trailing commas.
If a detail is uncertain, write a concise bullet rather than adding commentary.
"""

    last_err = None
    last_reply = ""
    for attempt, active_prompt in enumerate((prompt, retry_prompt), start=1):
        msgs = [
            {"role": "system", "content": active_prompt},
            {"role": "user", "content": "Return only the required JSON object now."},
        ]
        try:
            response = robust_chat_completion(
                ollama, model, msgs, response_format={"type": "json_object"},
                temperature=0, max_tokens=8192,
            )
            message = response.choices[0].message
            last_reply = getattr(message, "content", None) or ""
            if not last_reply.strip():
                raise ValueError("Model returned an empty final content field after compatibility retries")

            data = extract_json(last_reply)
            raw_slides = data.get("slides") if isinstance(data, dict) else data
            if isinstance(raw_slides, dict):
                raw_slides = [raw_slides]
            if not isinstance(raw_slides, list):
                raise ValueError("JSON must contain a 'slides' array")

            slides = []
            for item in raw_slides:
                if not isinstance(item, dict):
                    continue
                title = re.sub(
                    r"^\s*(slide\s*\d+\s*[:.\-–]\s*|\d+\.\s*)", "",
                    str(item.get("title", "")), flags=re.I
                ).strip()
                content = item.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        f"• {str(line).strip().lstrip('•-* ').strip()}"
                        for line in content if str(line).strip()
                    )
                elif isinstance(content, dict):
                    content = json.dumps(content, ensure_ascii=False)
                if title:
                    slides.append((title, str(content).strip()))

            if slides:
                slides = slides[:max_slides]
                if expected_titles:
                    slides = [(expected_titles[i], content) for i, (_, content) in enumerate(slides)]
                # model returned too few slides -> fill the rest one at a time from the outline
                for n in range(len(slides) + 1, len(expected_titles) + 1):
                    try:
                        one = _single_slide(ollama, model, transcript, n, len(expected_titles), expected_titles[n - 1])
                        if not one[1].strip():
                            raise ValueError("single-slide response had empty content")
                        slides.append((expected_titles[n - 1], one[1]))
                    except Exception as exc:
                        print(f"[slides] could not generate slide {n}: {type(exc).__name__}: {str(exc)[:220]}")
                        slides.append((expected_titles[n - 1],
                                       "• Content generation needs retry or manual completion.\n"
                                       f"• Add verified evidence and key points for: {expected_titles[n - 1]}.\n"
                                       "• Check facts and sources before presenting."))
                return slides
            raise ValueError("JSON was valid but contained no slide objects with titles")

        except Exception as exc:
            last_err = exc

    excerpt = re.sub(r"\s+", " ", (last_reply or "<empty response>")).strip()[:700]
    if expected_titles:
        # Last-resort recovery: if the batch response is unusable, try each approved outline
        # item separately. If the model still fails, preserve the slide slot with clearly marked
        # editable placeholders rather than silently returning a one-slide deck or aborting.
        print(f"[slides] batch generation failed ({last_err}); recovering {len(expected_titles)} outline slide(s) individually.")
        recovered = []
        for n, title in enumerate(expected_titles, 1):
            try:
                one = _single_slide(ollama, model, transcript, n, len(expected_titles), title)
                content = one[1].strip()
                if not content:
                    raise ValueError("single-slide response had empty content")
                recovered.append((title, content))
            except Exception as exc:
                print(f"[slides] slide {n} recovery failed: {type(exc).__name__}: {str(exc)[:220]}")
                recovered.append((title, (
                    "• Content generation needs retry or manual completion.\n"
                    f"• Add verified evidence and key points for: {title}.\n"
                    "• Check facts and sources before presenting."
                )))
        return recovered

    raise ValueError(
        f"Could not parse slides from Ollama model '{model}' after 2 attempts. "
        f"Last error: {last_err}. Model reply excerpt: {excerpt}. "
        "Try selecting a different installed Ollama model, or verify the model is fully downloaded with `ollama list`."
    )


def convo_backup(global_prompt, file_path):
    formatted_lines = []
    for msg in global_prompt:
        role = msg["role"].capitalize()
        content = msg["content"]
        formatted_lines.append(f"{role}:\n{content}\n" + "-" * 40 + "\n")

    output_text = "".join(formatted_lines)

    # Save the formatted text to a .txt file
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    formatted_lines = []
    for msg in global_prompt:
        formatted_lines.append(f"{msg}")
    output_text = "".join(formatted_lines)


    # Save the formatted text to a .txt file
    with open(file_path[:-4]+"_raw_format.txt", "w", encoding="utf-8") as f:
        f.write(output_text)

    return 0


def summarize_conversation(ollama, file_path, summarizer_prompt, model_name=DEFAULT_OLLAMA_MODEL):
    """Reads a local conversation file and generates a summary using a local LLM."""
    
    # 1. Read the local file
    try:
        conversation_text = Path(file_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: The file at {file_path} was not found."

    # 2. Craft a structured prompt for the LLM
    prompt = f"""
    
    {summarizer_prompt}

    Conversation Transcript:
    ---
    {conversation_text}
    ---
    
    Summary:
    """

    # 3. Stream the response from the local LLM
    try:
        response = robust_chat_completion(
            ollama, model_name, [{"role": "system", "content": prompt}],
            temperature=0, max_tokens=4096,
        )
        return response.choices[0].message.content
        
    except Exception as e:
        return f"An error occurred while communicating with Ollama: {e}"


# Unify your global color tokens natively over the theme constructor
unified_theme = gr.themes.Soft().set(
    background_fill_primary="#0b0f19",      # Deep dark navy outer background padding
    background_fill_secondary="#0b0f19",    # Inner container backgrounds
    block_background_fill="#0b0f19",        # Block unit elements backgrounds
    panel_background_fill="#0b0f19",        # Nested subgroup backgrounds
    input_background_fill="#151a26",        # Textbox and text area backgrounds
    input_border_color="#242b3d",           # Thin clean lines for text fields
    border_color_primary="transparent"       # Force layout dividing lines to vanish
)


dark_panel_css = """
    /* Make collapsible accordions discoverable: larger chevron and a clear hit target. */
    .gradio-container .gr-accordion > button svg,
    .gradio-container [data-testid="accordion"] > button svg,
    .gradio-container button[aria-expanded] svg {
        width: 1.45rem !important;
        height: 1.45rem !important;
        min-width: 1.45rem !important;
        min-height: 1.45rem !important;
        stroke-width: 2.5 !important;
    }
    .gradio-container .gr-accordion > button,
    .gradio-container [data-testid="accordion"] > button {
        min-height: 2.8rem !important;
        gap: 0.65rem !important;
    }

    .gradio-container {
        --block-background-fill: transparent !important;
        --input-background-fill: #0b0f19 !important;
    }

    /* Outer dropdown container: keep the border here */
    .gradio-container [data-testid="dropdown"] {
        border: 1px solid #303643 !important;
        border-radius: 9px !important;
        box-shadow: none !important;
    }

    /* Inner selection field: remove its border */
    .gradio-container [data-testid="dropdown"] input,
    .gradio-container [data-testid="dropdown"] [role="combobox"] {
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        background: transparent !important;
    }

    /* 1. Flatten panel containers and remove their backgrounds */
    .gr-group,
    div[class*="gr-group"],
    .gradio-container div.form,
    fieldset.gr-block,
    .gr-accordion,
    div[class*="gr-accordion"] {
        background: transparent !important;
        border-color: transparent !important;
        box-shadow: none !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
        margin-left: 0 !important;
        margin-right: 0 !important;
    }

    /* 2. Remove backgrounds from block wrappers */
    .g-block,
    div[class*="g-block"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }

    /* 3. Flatten nested layout wrappers */
    div[class*="gr-group"] > div,
    .gr-group > .form {
        padding-left: 0 !important;
        padding-right: 0 !important;
        background: transparent !important;
    }

    /* 4. Match textboxes, textareas, and dropdowns
        to the main document background */
    .gradio-container input,
    .gradio-container textarea,
    .gradio-container select,
    .gradio-container .gr-input,
    .gradio-container .gr-dropdown,
    .gradio-container [role="listbox"] {
        background-color: #0b0f19 !important;
        color: #f3f4f6 !important;
        border: 1px solid #252a35 !important;
        border-radius: 6px !important;
        box-shadow: none !important;
    }

    /* 5. Ensure labels have transparent backgrounds */
    .gradio-container label,
    .gradio-container .gr-form label span {
        background-color: transparent !important;
    }

    /* Keep the studio title visible while scrolling the slide workspace. */
    #app-header {
        position: sticky !important;
        top: 0 !important;
        z-index: 1001 !important;
        background: #0b0f19 !important;
        padding: 0.65rem 1rem !important;
        margin: 0 !important;
        border-bottom: 1px solid #303643 !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.28) !important;
    }

    /* The actions stay pinned only while the initialized workspace is visible. */
    #compile-action-bar {
        position: fixed !important;
        left: 0 !important;
        right: 0 !important;
        bottom: 0 !important;
        z-index: 1000 !important;
        box-sizing: border-box !important;
        width: 100vw !important;
        padding: 0.65rem 1.5rem !important;
        margin: 0 !important;
        background: rgba(11, 15, 25, 0.97) !important;
        border-top: 1px solid #303643 !important;
        box-shadow: 0 -6px 18px rgba(0, 0, 0, 0.28) !important;
        backdrop-filter: blur(8px) !important;
    }

    /* Leave room so the fixed controls do not cover the final slide. */
    #workspace-section {
        padding-bottom: 110px !important;
    }

    /* 6. Keep placeholders readable */
    .gradio-container input::placeholder,
    .gradio-container textarea::placeholder {
        color: #788397 !important;
        opacity: 1 !important;
    }

    /* 7. Preserve the dark main application background */
    .gradio-container {
        background-color: #0b0f19 !important;
    }

    /* --- ADDED: ACCORDION HORIZONTAL OVERFLOW SCROLLBAR FIXES --- */
    /* Target all accordion structures and force their horizontal axes to clip */
    .gr-accordion,
    div[class*="gr-accordion"],
    .accordion,
    .gradio-container .accordion,
    .gradio-container div[class*="row"] {
        overflow-x: hidden !important;
    }

    /* Force inner form rows and child grid blocks to remain strictly within container boundaries */
    div[class*="gr-accordion"] > div,
    .accordion > .form,
    .gradio-container .form {
        max-width: 100% !important;
        overflow-x: hidden !important;
    }
    """