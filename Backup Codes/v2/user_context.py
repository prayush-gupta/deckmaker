# Model Setup step
### This is the user context code that requests the user to describe the presentation topic

import glob
import json
import os
import warnings

import gradio as gr
from openai import OpenAI

warnings.filterwarnings("ignore")

# Import relevant functions
from def_prompts import deck_outline_prompt
from imp_functions import (first_prompt, response_append, slide_outline, convo_backup,
                           summarize_conversation, slides_from_conversation, extract_json,
                           dark_panel_css, unified_theme)
from tools_dec import tool_outline, slide_creation_tool
from gemini_code_fixed import (build_slide_updates, on_thumbnail_select, save_user_session,
                               load_user_session, compile_presentation_file, image_path_for,
                               GALLERY_ITEMS, MAX_SLIDES, PPT_DIR)
from comfyui import comfyui_img_generator

os.makedirs(PPT_DIR, exist_ok=True)

# Model initialize
ollama_url = "http://localhost:11434/v1"
ollama = OpenAI(api_key="ollama", base_url=ollama_url)
model_list = ["gpt-oss", "llama3.1", "deepseek-r1:32b", "nemotron3:33b", "qwen3.5"]


# Define our system prompt for the first step of defining the outline of the presentation
system_prompt, user_prompt_prefix, outline_summarizer = deck_outline_prompt()
tools = tool_outline() + slide_creation_tool()
file_paths = ["slide_outline_summary.txt"]

# --- GLOBAL STATE ---
p_cnt = 0
global_prompt = []
deck_outline = {}
summary_stages = []
slide_titles = [""] * MAX_SLIDES
slide_contents = [""] * MAX_SLIDES


def _parse_outline(outline):
    parsed = {}
    for line in outline.split("\n"):
        if line.startswith("#") or ". " not in line:
            continue
        number, text = line.split(". ", 1)
        if number.strip().isdigit():
            parsed[int(number)] = text
    return parsed


def response_streamer_outline(model, user_input_message, slide_count):
    yield "⏳ Processing..."
    global p_cnt, global_prompt, deck_outline, summary_stages
    if p_cnt == 0:
        prompt = first_prompt(system_prompt, user_prompt_prefix, user_input_message, slide_count)
        p_cnt = 1
    else:
        prompt = response_append(global_prompt, user_input_message, "user")

    stream = ollama.chat.completions.create(
        model=model,
        messages=prompt,
        tools=tools,
        stream=True,
    )

    result = ""
    calls = {}  # tool call index -> accumulated pieces
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            result += delta.content
            yield result
        for tc in delta.tool_calls or []:
            c = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                c["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    c["name"] = tc.function.name
                if tc.function.arguments:
                    c["arguments"] += tc.function.arguments  # JSON arrives in fragments

    # store the assistant turn, including any tool calls
    assistant_msg = {"role": "assistant", "content": result or None}
    if calls:
        assistant_msg["tool_calls"] = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in calls.values()
        ]

    new_prompt = list(prompt) + [assistant_msg]
    global_prompt = new_prompt  # saved up-front so state is never lost if a tool step fails

    # run the tools
    for c in calls.values():
        if c["name"] in ("slide_outline", "slide_content"):
            yield "Generating local summary...\n\n" if c["name"] == "slide_outline" else "Generating content for the slide...\n\n"
            args = json.loads(c["arguments"])
            outline = slide_outline(**args)
            new_prompt.append({
                "role": "tool",
                "tool_call_id": c["id"],
                "content": str(outline),
            })
            deck_outline = _parse_outline(outline)
            global_prompt = new_prompt

            if c["name"] == "slide_outline":
                # back up the conversation INCLUDING this turn's reply
                convo_backup(global_prompt, file_paths[0])
                summary_stages.append(summarize_conversation(ollama, file_paths[0], outline_summarizer, model))
                yield "Outline finalized, click on 'Initialize Slides' to generate the slides."

    global_prompt = new_prompt


def regenerate_single_slide(ollama, slide_index, current_title, current_content, user_feedback, model_selection):
    """Refine one slide from user feedback. Returns exactly two updates: (title, content)."""
    if not (user_feedback or "").strip():
        gr.Warning("Please provide feedback before re-generating.")
        return gr.update(), gr.update()

    refine_prompt = [
        {"role": "system", "content": (
            "You are a professional deck layout editor. Modify the provided slide title and content "
            "based strictly on the user feedback. Return ONLY valid JSON with keys 'title' (string) and "
            "'content' (array of 3-6 short bullet strings, no bullet characters).")},
        {"role": "user", "content": f"Current Title: {current_title}\nCurrent Content: {current_content}\nUser Feedback: {user_feedback}"},
    ]

    try:
        target_model = "gpt-oss" if model_selection == "Default" else model_selection
        response = ollama.chat.completions.create(
            model=target_model,
            messages=refine_prompt,
            response_format={"type": "json_object"},
        )
        data = extract_json(response.choices[0].message.content)
        new_title = str(data.get("title", current_title)).strip() or current_title
        new_content = data.get("content", current_content)
        if isinstance(new_content, list):
            new_content = "\n".join(f"• {str(c).strip().lstrip('•-* ').strip()}" for c in new_content if str(c).strip())

        if 0 <= slide_index < len(slide_titles):
            slide_titles[slide_index] = new_title
            slide_contents[slide_index] = new_content

        gr.Info(f"Slide {slide_index + 1} updated using {target_model}")
        return gr.update(value=new_title), gr.update(value=new_content)

    except Exception as e:
        gr.Warning(f"Re-generation error: {e}")
        return gr.update(), gr.update()


def slides_setup(model):
    """Build slide text from the agreed conversation, render images, and fill the UI slots."""
    global slide_titles, slide_contents

    if not global_prompt:
        raise gr.Error("Please submit a topic and confirm the outline first.")

    try:
        slides = slides_from_conversation(ollama, global_prompt, model, MAX_SLIDES)
    except Exception as e:
        raise gr.Error(str(e))

    slide_titles = [t for t, _ in slides]
    slide_contents = [c for _, c in slides]

    # remove images from any previous deck so they can't show up on the wrong slides
    for old in glob.glob(os.path.join(PPT_DIR, "slide_*_0.png")):
        try:
            os.remove(old)
        except OSError:
            pass

    for i, (title, content) in enumerate(slides):
        try:
            comfyui_img_generator(title, content, os.path.join(PPT_DIR, f"slide_{i + 1}"))
        except Exception as e:
            gr.Warning(f"Image generation stopped at slide {i + 1} (is ComfyUI running?): {e}")
            break

    return build_slide_updates(slide_titles, slide_contents)


message_input = gr.Textbox(label="Presentation Topic", info="Hi, please share a brief overview of the presentation topic: ", lines=7)
model_selector = gr.Dropdown(model_list, label="Select Model", value="gpt-oss")
message_output = gr.Markdown(label="Response:")

title_textboxes = []
content_textboxes = []


def reset_chat():
    global p_cnt, global_prompt, deck_outline, summary_stages, slide_titles, slide_contents
    p_cnt = 0
    global_prompt = []
    deck_outline = {}
    summary_stages = []
    slide_titles = [""] * MAX_SLIDES
    slide_contents = [""] * MAX_SLIDES
    # Returns: message_input, message_output, workspace_section
    return "", "", gr.update(visible=False)


def submit_lock():
    return gr.update(interactive=False, value="Generating..."), gr.update(interactive=False), gr.update(interactive=False)

def submit_unlock():
    return gr.update(interactive=True, value="Submit"), gr.update(interactive=True), gr.update(interactive=True)

def initialize_lock():
    return gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False, value="Generating Slides...")

def initialize_unlock():
    return gr.update(interactive=True), gr.update(interactive=True), gr.update(interactive=True, value="✨ Initialize Slides")


def make_refresh_handler(slide_idx):
    def handler(current_t, current_c, feedback, model):
        return regenerate_single_slide(ollama, slide_idx, current_t, current_c, feedback, model)
    return handler


def make_image_handler(slide_idx):
    def handler(current_t, current_c):
        if not (current_t or "").strip():
            raise gr.Error("This slide has no title yet.")
        prefix = os.path.join(PPT_DIR, f"slide_{slide_idx + 1}")
        try:
            comfyui_img_generator(current_t, current_c, prefix)
        except Exception as e:
            raise gr.Error(f"Image generation failed (is ComfyUI running?): {e}")
        return image_path_for(slide_idx)
    return handler


with gr.Blocks(theme=unified_theme, title="Local Deck Compiler", css=dark_panel_css) as demo:
    gr.Markdown("# 🎬 AI Presentation Studio & Design Engine Workspace")

    # --- PROFILES & TRACKING ENGINE CONTROLS ---
    with gr.Group():
        gr.Markdown("---")
        with gr.Accordion(label="📁 Project Session Management Console", open=False):
            gr.Markdown("## Session Management")
            gr.Markdown("---")
            gr.HTML("<div style='height: 1px;'></div>")
            with gr.Row():
                session_input = gr.Textbox(
                    label="📁 Local Project Session Identifier Name",
                    placeholder="Enter workspace profiles target title name (e.g., Marketing-Q4-Deck)...",
                    scale=2
                )
                save_state_btn = gr.Button("💾 Save Current Session")
                load_state_btn = gr.Button("📂 Resume Old Session")
        status_marquee = gr.Markdown("---")

        gr.Markdown("---")
        gr.HTML("<div style='height: 25px;'></div>")
        gr.Markdown("## 🧑‍🏫 Describe the Presentation Topic")
        gr.Markdown("---")
        gr.HTML("<div style='height: 1px;'></div>")

        with gr.Row():
            with gr.Column(scale=1):
                model_selector.render()
                message_input.render()
                count_input = gr.Number(
                    label="Slide Target Count", value=3, precision=0, minimum=0, maximum=MAX_SLIDES,
                    interactive=True, info="upto 25 slides"
                )
                with gr.Row():
                    reset_btn = gr.Button("Reset Chat")
                    submit_btn = gr.Button("Submit", variant="primary")
            with gr.Column(scale=2):
                message_output.render()
        inputs = [model_selector, message_input, count_input]

        with gr.Row():
            gr.HTML("<div style='width: 1px;'></div>")
            with gr.Column(scale=5):
                gr.HTML("<div style='height: 25px;'></div>")
                generate_btn = gr.Button("✨ Initialize Slides", variant="primary")
            gr.HTML("<div style='width: 1px;'></div>")

        # --- DYNAMIC GRID INTERACTIVE COMPONENT WORKSPACE ---
        # ui_slots  : UI_STEP (6) per slide  -> slide_box, title, content, layout, image, feedback
        # state_components_to_persist : STATE_STEP (4) per slide -> title, content, layout, feedback
        # Keep these in sync with UI_STEP / STATE_STEP in gemini_code_fixed.py!
        state_components_to_persist = []
        ui_slots = []

        with gr.Column(visible=False) as workspace_section:

            gr.HTML("<div style='height: 25px;'></div>")
            gr.Markdown("## 🛠️ Slides Content and Layout")
            gr.Markdown("---")
            gr.HTML("<div style='height: 1px;'></div>")

            for i in range(MAX_SLIDES):
                with gr.Accordion(label=f'Slide {i+1}: ', open=True) as slide_box:
                    gr.Markdown(f"## 🖼️ Slide {i+1}")

                    with gr.Row():
                        # SLIDE CONTENTS
                        with gr.Column(scale=3):
                            title_textbox = gr.Textbox(value="", label=f"Slide {i+1} Title")
                            content_textbox = gr.TextArea(value="", label=f"Slide {i+1} Contents", lines=10)
                            title_textboxes.append(title_textbox)
                            content_textboxes.append(content_textbox)

                        # SLIDE IMAGE
                        with gr.Column(scale=5):
                            slide_image_component = gr.Image(
                                value=image_path_for(i),
                                label=f"Slide {i+1}",
                                type="filepath",
                                interactive=False,
                                height = 280
                            )

                    with gr.Row():
                        with gr.Column(scale=2):
                            model_selector_slide = gr.Dropdown(["Default"] + model_list, label="Select model", value="Default", interactive=True)
                        with gr.Column(scale=8):
                            user_feedback_box = gr.Textbox(
                                label="User Feedback",
                                placeholder="Please share your feedback here..."
                            )

                    with gr.Accordion(label=f'Layout for Slide {i+1}', open=False):
                        with gr.Column(scale=2):
                            layout_gallery = gr.Gallery(
                                value=GALLERY_ITEMS,
                                columns=10,
                                height="auto",
                                allow_preview=False
                            )
                        with gr.Column(scale=1):
                            slide_layout = gr.Textbox(label="Selected Layout", interactive=False)

                    with gr.Row():
                        render_btn = gr.Button(f"🎨 Update slide {i+1} content", variant="secondary")
                        image_btn = gr.Button(f"🖼️ Generate image for slide {i+1}", variant="primary")

                    gr.HTML("<div style='height: 25px;'></div>")

                    layout_gallery.select(fn=on_thumbnail_select, outputs=slide_layout)

                    render_btn.click(
                        fn=make_refresh_handler(i),
                        inputs=[title_textbox, content_textbox, user_feedback_box, model_selector_slide],
                        outputs=[title_textbox, content_textbox]
                    )

                    image_btn.click(
                        fn=make_image_handler(i),
                        inputs=[title_textbox, content_textbox],
                        outputs=[slide_image_component]
                    )

                    state_components_to_persist.extend([
                        title_textbox, content_textbox, slide_layout, user_feedback_box
                    ])
                    ui_slots.extend([
                        slide_box, title_textbox, content_textbox, slide_layout,
                        slide_image_component, user_feedback_box
                    ])

            # --- COMPILATION CONTROL TERMINAL PANEL LAYER ---
            gr.Markdown("---")

            with gr.Row():
                gr.HTML("<div style='width: 1px;'></div>")
                with gr.Column(scale=5):
                    gr.HTML("<div style='height: 25px;'></div>")
                    compile_btn = gr.Button("📦 Compile", variant="primary")
                gr.HTML("<div style='width: 1px;'></div>")

            with gr.Accordion(label='File Outputs', open=False):
                with gr.Column(scale=2):
                    compilation_output_box = gr.Markdown()
                with gr.Column(scale=1):
                    download_file_widget = gr.File(label="Download PowerPoint (.pptx)")

        # --- EVENT ROUTERS ---
        step1_outputs = [workspace_section] + ui_slots
        generate_btn.click(initialize_lock, None, [submit_btn, reset_btn, generate_btn]).then(
            fn=slides_setup,
            inputs=[model_selector],
            outputs=step1_outputs
        ).then(initialize_unlock, None, [submit_btn, reset_btn, generate_btn])

        save_state_btn.click(
            fn=save_user_session,
            inputs=[session_input, count_input, message_input] + state_components_to_persist,
            outputs=status_marquee
        )

        load_state_btn.click(
            fn=load_user_session,
            inputs=[session_input],
            outputs=[status_marquee, count_input, message_input, workspace_section] + ui_slots
        )

        compile_btn.click(
            fn=compile_presentation_file,
            inputs=[session_input] + state_components_to_persist,
            outputs=[download_file_widget, compilation_output_box]
        )

        submit_btn.click(submit_lock, None, [submit_btn, reset_btn, generate_btn]).then(
            response_streamer_outline, inputs, message_output, show_progress="full"
        ).then(submit_unlock, None, [submit_btn, reset_btn, generate_btn])

        message_input.submit(
            response_streamer_outline, inputs, message_output, show_progress="full"
        )

        reset_btn.click(reset_chat, None, [message_input, message_output, workspace_section])


if __name__ == "__main__":
    demo.launch(inbrowser=True)
