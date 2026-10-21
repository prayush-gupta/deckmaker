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


def _response_text(response):
    return (response.choices[0].message.content or "").strip()


def title_list(ollama, global_prompt, model="gpt-oss"):
    """Extract one clean slide title per line from the approved conversation."""
    transcript = json.dumps(global_prompt, ensure_ascii=False, default=str)
    prompt = f"""
Extract the final approved slide titles from this presentation conversation.
Return ONLY a JSON array of strings, in slide order. Do not add numbering,
markdown, explanations, or headings. If no approved outline exists, return [].

Conversation:
{transcript}
"""
    raw = _response_text(ollama.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    ))
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            items = parsed
        else:
            items = []
    except json.JSONDecodeError:
        items = raw.splitlines()

    cleaned = []
    for item in items:
        item = re.sub(r"^\\s*\\d+\\s*[.)]\\s*", "", str(item)).strip(" \\t-*•")
        if item and len(item) >= 3:
            cleaned.append(item)
    return cleaned[:25]


def content_list(ollama, response, model="gpt-oss"):
    """Extract one content description per slide as a JSON list."""
    transcript = json.dumps(response, ensure_ascii=False, default=str)
    prompt = f"""
Create the detailed content draft for every slide in the approved presentation.
Return ONLY a JSON array of strings. Each array item must contain the content for
one slide, in slide order. Do not include slide titles or slide numbers. Keep the
story coherent, avoid repetition, and do not invent specific statistics; mark
missing data as something to verify.

Conversation transcript:
{transcript}
"""
    raw = _response_text(ollama.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    ))
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed[:25]]
    except json.JSONDecodeError:
        pass

    # Graceful fallback for models that ignore the JSON-only instruction.
    blocks = [part.strip() for part in re.split(r"\\n\\s*\\n|`+", raw) if part.strip()]
    return blocks[:25]


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