### This code loads the relevant Local or web model as per the use case

import os
from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
import re
import json
import gradio as gr



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


def title_list(ollama, global_prompt, model='gpt-oss'):

    prompt = f"""

    You are a helpful assistant that only answers to the point and responds with the exact information that is asked for, in minimum number of words possible.
    Share only the approved slide titles from the conversation transcript for the all slides in order of the slide number.
    No other information should be included in this response, there should not be any headers etc included either.

    Conversation Transcript:
    ---
    {global_prompt}
    ---
    """

    return remove_prefix_numbers(ollama.chat.completions.create(
        model=model, 
        messages=[{"role": "system", "content": prompt}]
        ).choices[0].message.content.split("\n"))



def content_list(ollama, response, model='gpt-oss'):

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

    slide_content_raw = ollama.chat.completions.create(
                        model=model, 
                        messages=[{"role": "system", "content": prompt}]
                        ).choices[0].message.content
    
    slide_content_stg = slide_content_raw.split('`')

    slide_content = [text for text in slide_content_stg if len(text.strip()) >= 5]

    return slide_content


def extract_json(text):
    """Pull the first JSON object out of an LLM reply (handles <think> blocks and code fences)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in model reply")
    return json.loads(text[start:end + 1])


def transcript_text(messages):
    """Readable transcript (user/assistant turns only) from an OpenAI-style message list."""
    lines = []
    for m in messages or []:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            lines.append(f"{m['role'].capitalize()}: {m['content']}")
    return "\n\n".join(lines)


def slides_from_conversation(ollama, messages, model="gpt-oss", max_slides=25):
    """One LLM call -> list of (title, content) tuples.

    Title and content come from the SAME JSON entry, so they can never drift out of
    alignment (the old title_list/content_list pair used two separate calls and parsers).
    """
    prompt = f"""
    You are a presentation content writer. Read the conversation transcript and produce the final slides
    for the deck exactly as agreed in the approved outline (same number of slides, same order).

    Reply with ONLY a JSON object, no commentary, in this shape:
    {{"slides": [{{"title": "Short slide title", "content": ["Bullet 1", "Bullet 2", "Bullet 3"]}}]}}

    Rules:
    - "title": the approved slide title, no slide number, max 8 words.
    - "content": 3 to 6 concise bullet strings (max ~18 words each) with key facts, figures and trends.
    - Do not put numbering or bullet characters inside the strings.
    - Keep one consistent story across slides and avoid repeating information.

    Conversation Transcript:
    ---
    {transcript_text(messages)}
    ---
    """
    msgs = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Produce the JSON now."},
    ]

    last_err = None
    for attempt in range(2):
        try:
            try:
                reply = ollama.chat.completions.create(
                    model=model, messages=msgs, response_format={"type": "json_object"}
                ).choices[0].message.content
            except Exception:  # model/server without JSON mode
                reply = ollama.chat.completions.create(model=model, messages=msgs).choices[0].message.content

            data = extract_json(reply)
            raw_slides = data.get("slides", data) if isinstance(data, dict) else data
            slides = []
            for s in raw_slides:
                title = re.sub(r"^\s*(slide\s*\d+\s*[:.\-–]\s*|\d+\.\s*)", "", str(s.get("title", "")), flags=re.I).strip()
                content = s.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(f"• {str(c).strip().lstrip('•-* ').strip()}" for c in content if str(c).strip())
                if title:
                    slides.append((title, str(content).strip()))
            if slides:
                return slides[:max_slides]
            last_err = ValueError("Model returned no slides")
        except Exception as e:
            last_err = e
    raise ValueError(f"Could not parse slides from the model reply: {last_err}")


# This function generates the model feedback based on the input prompt

def response_generator(ollama, model, prompt):
    response = ollama.chat.completions.create(
        model = model,
        messages = prompt
    )
    return response.choices[0].message.content


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


def summarize_conversation(ollama, file_path, summarizer_prompt, model_name="llama3.1"):
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
        response = ollama.chat.completions.create(
            model=model_name
            ,messages=[{"role": "system", "content": prompt}]
            # ,options={
            #     "temperature": 0.3,  # Lower temperature for more factual/focused summaries
            #     "num_ctx": 4096      # Adjust context window based on conversation length
            # }
        )
        return response.choices[0].message.content
        
    except Exception as e:
        return f"An error occurred while communicating with Ollama: {e}"


# # Create a unified theme object mapping all background parameters to a single shade
# unified_theme = gr.themes.Soft().set(
#     block_background_fill="*background_fill_primary", # Force blocks to match core background color
#     panel_background_fill="*background_fill_primary", # Force panels to match core background color
#     background_fill_secondary="*background_fill_primary" # Eliminate variance in groupings
# )

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