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
                               generate_slide, GALLERY_ITEMS, MAX_SLIDES, PPT_DIR,
                               LAYOUT_NAMES, slide_preview_file, SLIDE_PREVIEW_DIR,
                               SLIDE_STRUCTURED, SLIDE_TEMPLATES)
from layout_catalogue import LAYOUT_LABELS, TEMPLATES, get_template
from layout_templates import (build_template_deck, coerce_content, find_background,
                              recommend_layouts, structure_for_layout, flatten_content,
                              write_catalogue_markdown, PREVIEW_DIR, TEMPLATE_DECK)
from comfyui import comfyui_img_generator, deck_design_brief, comfyui_session

os.makedirs(PPT_DIR, exist_ok=True)

# Height (px) of the slide preview. Set it equal to the height of the title + contents boxes on the
# left (title box + 10-line contents box measured ~368px). Nudge it, or change `lines=10` on the
# contents box, if you change the theme/zoom.
SLIDE_PANEL_HEIGHT = 368

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
deck_brief = None   # ONE colour/shape/style brief shared by every slide of the current deck
layout_recommendations = {}   # slide number (1-based) -> {"layout_id": ..., "reason": ...}


def _outline_text():
    """Readable outline text handed to the layout planner."""
    if isinstance(deck_outline, dict):
        return "\n".join(f"{n}. {t}" for n, t in sorted(deck_outline.items()))
    return str(deck_outline or "")


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
    """Build slide text from the agreed conversation, render images, pick layouts and fill the UI slots."""
    global slide_titles, slide_contents, deck_brief, layout_recommendations

    if not global_prompt:
        raise gr.Error("Please submit a topic and confirm the outline first.")

    try:
        slides = slides_from_conversation(ollama, global_prompt, model, MAX_SLIDES)
    except Exception as e:
        raise gr.Error(str(e))

    slide_titles = [t for t, _ in slides]
    slide_contents = [c for _, c in slides]

    # a new deck starts clean: no screenshots and no structured content from the last one
    from gemini_code_fixed import clear_slide_previews, SLIDE_STRUCTURED, SLIDE_TEMPLATES
    clear_slide_previews()
    SLIDE_STRUCTURED.clear()
    SLIDE_TEMPLATES.clear()

    # one design brief for the whole deck -> every slide gets the same palette / shapes / style
    deck_brief = deck_design_brief(slide_titles, model) or None

    # remove images from any previous deck so they can't show up on the wrong slides
    for old in glob.glob(os.path.join(PPT_DIR, "slide_*_0.png")):
        try:
            os.remove(old)
        except OSError:
            pass

    # ComfyUI is started ONCE for the whole deck and shut down afterwards, which frees its VRAM
    try:
        with comfyui_session(model):
            for i, (title, content) in enumerate(slides):
                try:
                    comfyui_img_generator(title, content, os.path.join(PPT_DIR, f"slide_{i + 1}"), brief=deck_brief)
                except Exception as e:
                    gr.Warning(f"Image generation stopped at slide {i + 1}: {e}")
                    break
    except Exception as e:
        gr.Warning(f"Could not start ComfyUI: {e}")

    # the LLM recommends a layout per slide - the user can still change any of them
    try:
        picks = recommend_layouts(
            ollama, model, _outline_text(),
            [{"title": t, "content": c} for t, c in slides],
        )
    except Exception as e:
        gr.Warning(f"Layout recommendation failed ({e}); a heuristic layout was used instead.")
        picks = []

    layout_recommendations = {int(p.get("number", i + 1)): p for i, p in enumerate(picks)}
    layout_ids = [p.get("layout_id") for p in picks]

    return build_slide_updates(slide_titles, slide_contents, layout_ids)


message_input = gr.Textbox(label="Presentation Topic", info="Hi, please share a brief overview of the presentation topic: ", lines=7)
model_selector = gr.Dropdown(model_list, label="Select Model", value="gpt-oss")
message_output = gr.Markdown(label="Response:")

title_textboxes = []
content_textboxes = []
slide_image_components = []


def reset_chat():
    global p_cnt, global_prompt, deck_outline, summary_stages, slide_titles, slide_contents, deck_brief
    deck_brief = None
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


def title_values():
    return list(slide_titles)


def make_image_handler(slide_idx):
    def handler(current_t, current_c):
        global deck_brief
        if not (current_t or "").strip():
            raise gr.Error("This slide has no title yet.")
        prefix = os.path.join(PPT_DIR, f"slide_{slide_idx + 1}")
        try:
            if deck_brief is None:   # e.g. after loading a saved session: create one and keep it for the rest of the deck
                deck_brief = deck_design_brief([t for t in title_values() if t] or [current_t]) or None
            comfyui_img_generator(current_t, current_c, prefix, brief=deck_brief)
        except Exception as e:
            raise gr.Error(f"Image generation failed (is ComfyUI running?): {e}")

        # a new backdrop means the slide has to be re-rendered on top of it
        data = SLIDE_STRUCTURED.get(slide_idx)
        if data:
            from gemini_code_fixed import _resolve_template, build_slide
            template = _resolve_template(
                get_template(SLIDE_TEMPLATES.get(slide_idx, "")), current_t, current_c)
            try:
                build_slide(template, data, slide_idx)
            except Exception as e:
                gr.Warning(f"Could not re-render the slide: {e}")
        return image_path_for(slide_idx)
    return handler


# --------------------------------------------------------------------------------------
# LAYOUT TEMPLATE LIBRARY HELPERS
# --------------------------------------------------------------------------------------

def _template_info(layout_label):
    """Markdown describing a template (used by the library panel)."""
    tpl = get_template(layout_label)
    if tpl is None:
        return "Pick a template in the gallery to see what it is for."
    return (
        f"### {tpl.id} · {tpl.name}\n"
        f"**Family:** {tpl.family}\n\n"
        f"**Use it when:** {tpl.best_for}\n\n"
        f"**Content pattern:** {tpl.content_pattern}\n\n"
        f"**Look:** {tpl.implementation}\n\n"
        f"**Density:** {tpl.density}"
    )


def _layout_info_for(layout_label):
    """Template information only (used when the user changes the dropdown)."""
    tpl = get_template(layout_label)
    if tpl is None:
        return "⚠️ Unknown layout - pick one from the list."
    return (f"**{tpl.id} · {tpl.name}** ({tpl.family})\n\n"
            f"{tpl.best_for}\n\n"
            f"*Content pattern:* {tpl.content_pattern}")


def _layout_note(slide_index, layout_label):
    """Per slide note: what the LLM recommended and what is currently selected."""
    rec = layout_recommendations.get(slide_index + 1, {})
    lines = []
    if rec:
        lines.append(f"🤖 **LLM recommendation:** `{rec.get('layout_id', '')}` — {rec.get('reason', '')}")
    lines.append(_layout_info_for(layout_label))
    return "\n\n".join(lines)


def make_layout_note_handler(slide_idx):
    """Rebuild the per-slide layout note whenever the dropdown changes."""
    def handler(layout_label):
        return _layout_note(slide_idx, layout_label)
    return handler


def _apply_pick(picked_label):
    """Apply a template that was picked in a gallery to a slide."""
    if not picked_label:
        raise gr.Error("Select a template in the gallery first.")
    return gr.update(value=picked_label)


def make_generate_slide_handler(slide_idx):
    """Builds the per-slide 'Generate slide' handler."""
    def handler(title, content, layout, model_selection):
        target_model = "gpt-oss" if model_selection in ("Default", None, "") else model_selection
        return generate_slide(ollama, target_model, slide_idx, title, content, layout, _outline_text())
    return handler


def _generate_all_slides(session_name, model, *slide_states):
    """Structure, render and compile every slide that has a title."""
    from gemini_code_fixed import _resolve_template, build_slide
    from layout_templates import structure_for_layout, flatten_content

    outline = _outline_text()
    content_updates = []
    image_updates = []
    built = 0
    errors = []

    for i in range(MAX_SLIDES):
        idx = i * 4
        title = (slide_states[idx] or "").strip()
        content = slide_states[idx + 1] or ""
        layout = slide_states[idx + 2] or ""
        if not title:
            content_updates.append(gr.update(value=content))
            image_updates.append(gr.update(value=image_path_for(i)))
            continue
        template = _resolve_template(layout, title, content)
        try:
            data = structure_for_layout(ollama, model, template, title, content, outline)
        except Exception as e:
            errors.append(f"slide {i + 1}: {e}")
            data = coerce_content(template, title, content)
        SLIDE_STRUCTURED[i] = data
        SLIDE_TEMPLATES[i] = template.id
        try:
            _, png = build_slide(template, data, i)
            image_updates.append(gr.update(value=png))
            content_updates.append(gr.update(value=flatten_content(data) or content))
            built += 1
        except Exception as e:
            errors.append(f"slide {i + 1} render: {e}")
            image_updates.append(gr.update(value=image_path_for(i)))
            content_updates.append(gr.update(value=content))

    path, status = compile_presentation_file(session_name, *slide_states)
    if errors:
        status += "\n\n⚠️ " + "; ".join(errors[:6])
    else:
        status += f"\n\n🎬 {built} slide(s) were re-structured to fit their template."
    return [path, status] + content_updates + image_updates


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

                    with gr.Row(equal_height=True):
                        # SLIDE CONTENTS
                        with gr.Column(scale=3):
                            title_textbox = gr.Textbox(value="", label=f"Slide {i+1} Title")
                            content_textbox = gr.TextArea(value="", label=f"Slide {i+1} Contents", lines=10)
                            title_textboxes.append(title_textbox)
                            content_textboxes.append(content_textbox)

                        # SLIDE IMAGE - stays EMPTY until this slide has been generated
                        with gr.Column(scale=3):
                            slide_image_component = gr.Image(
                                value=image_path_for(i),
                                label=f"Slide {i+1} preview",
                                type="filepath",
                                interactive=False,
                                height=SLIDE_PANEL_HEIGHT,
                                elem_classes=["slide-image"],
                            )
                            slide_image_components.append(slide_image_component)

                    with gr.Row():
                        with gr.Column(scale=2):
                            model_selector_slide = gr.Dropdown(["Default"] + model_list, label="Select model", value="Default", interactive=True)
                        with gr.Column(scale=8):
                            user_feedback_box = gr.Textbox(
                                label="User Feedback",
                                placeholder="Please share your feedback here..."
                            )

                    # --- LAYOUT SELECTOR - one per slide ---
                    with gr.Accordion(label=f'🎨 Layout for Slide {i+1}', open=False):
                        with gr.Row():
                            with gr.Column(scale=2):
                                slide_layout = gr.Dropdown(
                                    LAYOUT_LABELS,
                                    label="Selected Layout (LLM recommended - change it any time)",
                                    value=LAYOUT_LABELS[1],
                                    interactive=True,
                                )
                            with gr.Column(scale=3):
                                layout_note = gr.Markdown(_layout_note(i, LAYOUT_LABELS[1]))

                        gr.Markdown("**Template gallery** — click a layout to use it for this slide:")
                        layout_gallery = gr.Gallery(
                            value=GALLERY_ITEMS,
                            columns=6,
                            height=300,
                            allow_preview=True,
                            show_label=True,
                            elem_classes=["template-gallery"],
                            label=f"Layout templates for slide {i+1}",
                        )
                        slide_status = gr.Markdown("")

                    with gr.Row():
                        generate_slide_btn = gr.Button(f"🎬 Generate slide {i+1}", variant="primary")
                        render_btn = gr.Button(f"🎨 Update slide {i+1} content", variant="secondary")
                        image_btn = gr.Button(f"🖼️ Generate image for slide {i+1}", variant="secondary")

                    gr.HTML("<div style='height: 25px;'></div>")

                    # clicking a template in THIS slide's gallery selects it for THIS slide
                    layout_gallery.select(
                        fn=on_thumbnail_select,
                        outputs=[slide_layout],
                    )

                    slide_layout.change(
                        fn=make_layout_note_handler(i),
                        inputs=[slide_layout],
                        outputs=[layout_note],
                    )

                    generate_slide_btn.click(
                        fn=make_generate_slide_handler(i),
                        inputs=[title_textbox, content_textbox, slide_layout, model_selector_slide],
                        outputs=[title_textbox, content_textbox, slide_layout,
                                 slide_image_component, slide_status],
                    )

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
                    with gr.Row():
                        generate_all_btn = gr.Button("🎬 Generate all slides", variant="primary")
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

        generate_all_btn.click(
            fn=_generate_all_slides,
            inputs=[session_input, model_selector] + state_components_to_persist,
            outputs=[download_file_widget, compilation_output_box] + content_textboxes + [c for c in slide_image_components],
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
