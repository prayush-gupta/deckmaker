# Model Setup step
### This is the user context code that requests the user to describe the presentation topic

import json
from openai import OpenAI
import gradio as gr
import warnings
import os

warnings.filterwarnings("ignore")

# --- CONFIGURATION & CONSTANTS ---
MAX_SLIDES = 25
# COMFYUI_API_URL = "http://127.0.0.1:8188/prompt"
# SESSIONS_DIR = "presentation_sessions"
# OUTPUT_DIR = "generated_presentations"
PPT_DIR = "generated_presentations/ppt2"
ARCHIVE_DIR = "archive"

os.makedirs(PPT_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# A mapping dictionary linking template labels to thumbnail image assets
LAYOUT_TEMPLATES = {
    "Minimalist Title Centered": "https://images.unsplash.com/photo-1626785774573-4b799315345d?w=150&q=80",
    "Split Text & Image": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=150&q=80",
    "Three-Column Feature Grid": "https://images.unsplash.com/photo-1557683316-973673baf926?w=150&q=80",
    "Technical Diagram Grid": "https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=150&q=80",
    "Big Metric Callout": "https://images.unsplash.com/photo-1614850523459-c2f4c699c52e?w=150&q=80",
}
GALLERY_ITEMS = [(img, name) for name, img in LAYOUT_TEMPLATES.items()]


# Import relevant functions
from def_prompts import deck_outline_prompt
from imp_functions import (
    first_prompt,
    response_append,
    slide_outline,
    convo_backup,
    summarize_conversation,
    title_list,
    content_list,
    dark_panel_css,
    unified_theme,
)
from tools_dec import tool_outline, slide_creation_tool
from gemini_code_fixed import (
    process_outline_and_suggest_layouts,
    on_thumbnail_select,
    save_user_session,
    load_user_session,
    compile_presentation_file,
)
from comfyui import comfyui_img_generator

# Model initialize
ollama_url = "http://localhost:11434/v1"
ollama = OpenAI(api_key="ollama", base_url=ollama_url)
model_list = ["gpt-oss", "llama3.1", "deepseek-r1:32b", "nemotron3:33b", "qwen3.5"]


# Define our system prompt for the first step of defining the outline of the presentation
system_prompt, user_prompt_prefix, outline_summarizer = deck_outline_prompt()
tools = tool_outline() + slide_creation_tool()
file_paths = ["slide_outline_summary.txt"]

def response_streamer_outline(model, user_input_message, slide_count):
    yield "⏳ Processing..."
    global p_cnt, global_prompt, deck_outline, outline, result, summary_stages, prompt
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

    # run the tools
    for c in calls.values():
        if c["name"] == "slide_outline":
            yield "Generating local summary...\n\n"
            args = json.loads(c["arguments"])
            outline = slide_outline(**args)
            new_prompt.append({
                "role": "tool",
                "tool_call_id": c["id"],
                "content": str(outline),
            })

            outline_list = outline.split("\n")
            deck_outline = {}

            for line in outline_list:
                if line.startswith("#"):
                    continue
                number, text = line.split(". ", 1)
                deck_outline[int(number)] = text

            convo_backup(new_prompt, file_paths[0])

            summary_stages.append(summarize_conversation(ollama, file_paths[0], outline_summarizer, model))

            yield "Outline finalized, click on 'Initialize Slides' to generate the slides."

        if c["name"] == "slide_content":
            yield "Generating content for the slide...\n\n"
            args = json.loads(c["arguments"])
            outline = slide_outline(**args)
            new_prompt.append({
                "role": "tool",
                "tool_call_id": c["id"],
                "content": str(outline),
            })

            outline_list = outline.split("\n")
            deck_outline = {}

            for line in outline_list:
                if line.startswith("#"):
                    continue
                number, text = line.split(". ", 1)
                deck_outline[int(number)] = text


    global_prompt = new_prompt


def regenerate_single_slide(ollama, slide_index, current_title, current_content, user_feedback, model_selection):
    """Revise one slide's title/content using the selected local model."""
    current_title = current_title or ""
    current_content = current_content or ""
    user_feedback = (user_feedback or "").strip()
    if not user_feedback:
        return current_title, current_content

    target_model = "gpt-oss" if not model_selection or model_selection == "Default" else model_selection
    refine_prompt = [
        {
            "role": "system",
            "content": (
                "You are a professional presentation editor. Apply the user's feedback "
                "to the slide title and content. Return a JSON object with exactly "
                "two keys: title (string) and content (string)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Current title: {current_title}\\n"
                f"Current content: {current_content}\\n"
                f"Feedback: {user_feedback}"
            ),
        },
    ]

    try:
        response = ollama.chat.completions.create(
            model=target_model,
            messages=refine_prompt,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        new_title = str(data.get("title") or current_title)
        new_content = str(data.get("content") or current_content)

        slide_titles[slide_index] = new_title
        slide_contents[slide_index] = new_content
        return new_title, new_content
    except Exception as exc:
        # Keep the existing content intact if the model request fails.
        print(f"Slide {slide_index + 1} regeneration failed: {exc}")
        return current_title, current_content


# --- UPDATED SLIDES_SETUP FUNCTION ---
def slides_setup(count_input, message_input):
    """Populate the 25 fixed UI slots; only the requested number are visible."""
    global slide_titles, slide_contents

    count = max(1, min(MAX_SLIDES, int(count_input or 1)))
    layout_results = process_outline_and_suggest_layouts(count, message_input)
    workspace_update = layout_results[0]
    slot_updates = layout_results[1:]

    try:
        generated_titles = title_list(ollama, global_prompt) if global_prompt else []
    except Exception as exc:
        print(f"Could not extract slide titles from conversation: {exc}")
        generated_titles = []

    try:
        generated_contents = content_list(ollama, global_prompt) if global_prompt else []
    except Exception as exc:
        print(f"Could not extract slide content from conversation: {exc}")
        generated_contents = []

    outline_titles = [
        item.strip().lstrip("0123456789. )")
        for item in (message_input or "").splitlines()
        if item.strip()
    ]
    slide_titles = [""] * MAX_SLIDES
    slide_contents = [""] * MAX_SLIDES
    updates = []

    for i in range(MAX_SLIDES):
        base = i * 5
        slide_visible = i < count
        title = (
            generated_titles[i].strip()
            if i < len(generated_titles) and generated_titles[i].strip()
            else (outline_titles[i] if i < len(outline_titles) else f"Slide {i + 1} Title")
        )
        content = generated_contents[i].strip() if i < len(generated_contents) else ""
        slide_titles[i] = title
        slide_contents[i] = content

        # Preserve the visibility/layout updates returned by the layout helper.
        updates.extend([
            slot_updates[base],
            gr.update(value=title, label=f"Slide {i + 1} Title"),
            gr.update(value=content),
            slot_updates[base + 3],
            gr.update(value=""),
        ])

    return [workspace_update] + updates


message_input = gr.Textbox(label="Presentation Topic", info="Hi, please share a brief overview of the presentation topic: ", lines=7)
model_type_selector = gr.Dropdown(["ollama"], label="Select model type", value="ollama")
model_selector = gr.Dropdown(model_list, label="Select Model", value="gpt-oss")
message_output = gr.Markdown(label="Response:")

p_cnt=0
global_prompt = {}
deck_outline = {}
summary_stages = []
slide_titles = [""] * MAX_SLIDES
slide_contents = [""] * MAX_SLIDES

title_textboxes = []
content_textboxes = []

def reset_chat():
    global p_cnt, global_prompt, deck_outline, summary_stages, slide_titles, slide_contents, title_textboxes, content_textboxes
    p_cnt=0
    global_prompt = {}
    deck_outline = {}
    summary_stages = []
    slide_titles = [""] * MAX_SLIDES
    slide_contents = [""] * MAX_SLIDES

    title_textboxes = []
    content_textboxes = []
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


with gr.Blocks(theme=unified_theme, title="Local Deck Compiler", css=dark_panel_css) as demo: #gr.themes.Soft()
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
                    label="📁 Local Project Session Identifier Name"
                    ,placeholder="Enter workspace profiles target title name (e.g., Marketing-Q4-Deck)..."
                    ,scale=2
                )
                save_state_btn = gr.Button("💾 Save Current Session")#, variant="secondary")
                load_state_btn = gr.Button("📂 Resume Old Session")#, variant="secondary")
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
                    label="Slide Target Count", value=3, precision=0, minimum=0, maximum=MAX_SLIDES
                    , interactive=True, info="upto 25 slides"
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

        # gr.HTML("<div style='height: 25px;'></div>")
        # gr.Markdown("## 🛠️ Slides Content and Layout")
        # gr.Markdown("---")
        # gr.HTML("<div style='height: 1px;'></div>")

        # --- DYNAMIC GRID INTERACTIVE COMPONENT WORKSPACE ---
        slide_boxes = []
        state_components_to_persist = []
        ui_slots = []
        
        with gr.Column(visible=False) as workspace_section:

            gr.HTML("<div style='height: 25px;'></div>")
            gr.Markdown("## 🛠️ Slides Content and Layout")
            gr.Markdown("---")
            gr.HTML("<div style='height: 1px;'></div>")

            for i in range(MAX_SLIDES):
                # with gr.Group(visible=False) as slide_box:
                with gr.Accordion(label=f'Slide {i+1}: ', open=True) as slide_box:
                    # if i>0:
                    #     gr.Markdown("---")
                    gr.Markdown(f"## 🖼️ Slide {i+1}")
                    
                    with gr.Row():
                        # SLIDE CONTENTS
                        with gr.Column(scale=3):
                            title_textbox = gr.Textbox(
                                value=slide_titles[i],
                                label=f"Slide {i+1} Title"
                            )

                            content_textbox = gr.TextArea(
                                value=slide_contents[i],
                                label=f"Slide {i+1} Contents",
                                lines=10
                            )

                            title_textboxes.append(title_textbox)
                            content_textboxes.append(content_textbox)

                        # LLM FEEDBACK/SUGGESTIONS
                        with gr.Column(scale=5):
                            with gr.Row():
                                expected_image_path = f"{PPT_DIR}/slide_{i+1}_0.png"
                                if not os.path.exists(expected_image_path):
                                    expected_image_path = "ARCHIVE_DIR/slide_0.png"
                                
                                slide_image_component = gr.Image(
                                    value=expected_image_path, # <-- Loads the pre-existing auto-saved image instantly!
                                    label=f"Slide {i+1}", 
                                    type="filepath", 
                                    interactive=False
                                )

                                # llm_insights_box = gr.Markdown(value="Please click ", label="Model Response:")
                
                        gr.HTML("<div style='width: 2px;'></div>")

                    with gr.Row():
                        with gr.Column(scale = 2):
                            model_selector_slide = gr.Dropdown(["Default"]+model_list, label="Select model", value="Default", interactive=True)
                        with gr.Column(scale = 8):
                            user_feedback_box = gr.Textbox(
                                label="User Feedback"
                                ,placeholder="Please share your feedback here..."
                                # ,lines=3
                            )


                    with gr.Accordion(label=f'Layout for Slide {i+1}', open=False):
                        with gr.Column(scale=2):
                            layout_gallery = gr.Gallery(
                                value=GALLERY_ITEMS,
                                # label="Visual Design Template Selection Matrix Options",
                                columns=10,
                                height="auto",
                                allow_preview=False
                            )
                        with gr.Column(scale=1):
                            slide_layout = gr.Textbox(label="Selected Layout", interactive=False)
                                                                
                    with gr.Row():
                        render_btn = gr.Button(f"🎨 Update slide {i+1} content", variant="secondary")
                        approve_chk = gr.Button(f"✅ Generate Output Slide {i+1}", variant="primary")
                        
                    gr.HTML("<div style='height: 25px;'></div>")
                    
                    # Bind local scoped asset manipulation interactions per individual block unit loops
                    layout_gallery.select(fn=on_thumbnail_select, outputs=slide_layout)
                    

                    # --- THE FIX: Create a localized handler function inside the loop scope ---
                    def make_refresh_handler(slide_idx):
                        def handler(current_t, current_c, feedback, model):
                            # This safely uses the global 'ollama' variable and the locked 'slide_idx'
                            return regenerate_single_slide(
                                ollama, slide_idx, current_t, current_c, feedback, model
                            )
                        return handler

                    # Bind the click event WITHOUT using a lambda signature that confuses Gradio
                    render_btn.click(
                        fn=make_refresh_handler(i), # Creates a custom function pinned strictly to index 'i'
                        inputs=[title_textbox, content_textbox, user_feedback_box, model_selector_slide],
                        outputs=[title_textbox, content_textbox] 
                    )

                    # --- THE FIX: Create a localized handler function inside the loop scope ---
                    def make_slide_handler(slide_idx):
                        # Match the parameters exactly to the components passed in the 'inputs' array below
                        def handler(current_t, current_c):
                            # Construct the target path using your index state
                            target_path = f"{PPT_DIR}/slide_{slide_idx+1}"
                            
                            # Safely execute your core logic function 
                            # This returns the generated image file path string
                            generated_img_path = regenerate_single_slide(current_t, current_c, target_path)
                            
                            # Return the path so the target Gradio image component updates visually
                            return generated_img_path
                            
                        return handler  

                    
                    approve_chk.click(
                        fn=make_slide_handler(i),
                        inputs=[title_textbox, content_textbox], 
                        outputs=[slide_image_component] 
                    )

                    
                    # Cache references structures maps for Gradio block configurations update operations
                    slide_boxes.append(slide_box)
                    state_components_to_persist.extend([
                        title_textbox, content_textbox, slide_layout,
                        user_feedback_box
                    ])
                    ui_slots.extend([
                        slide_box, title_textbox, content_textbox, slide_layout,
                        user_feedback_box
                    ])
                    
            # --- COMPILATION CONTROL TERMINAL PANEL LAYER ---
            gr.Markdown("---")
            # gr.Markdown("## 🚀 Step 3: Global Production Compilation & Presentation Download Package Generation")

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

        # --- GLOBAL COMPONENT MATRIX SYSTEM EVENT EVENT LINK ROUTERS ---
        
        # Initialize workspace components mappings event routers
        step1_outputs = [workspace_section] + ui_slots
        generate_btn.click(initialize_lock, None, [submit_btn, reset_btn, generate_btn]).then(
            fn=slides_setup,
            inputs=[count_input, message_input],
            outputs=step1_outputs
        ).then(initialize_unlock, None, [submit_btn, reset_btn, generate_btn])

        # Local application configurations save tracking mechanisms
        save_state_btn.click(
            fn=save_user_session,
            inputs=[session_input, count_input, message_input] + state_components_to_persist,
            outputs=status_marquee
        )
        
        # Local application files state restoration system actions routing setups
        load_state_btn.click(
            fn=load_user_session,
            inputs=[session_input],
            outputs=[status_marquee, count_input, message_input, workspace_section] + ui_slots
        )
        
        # Global multi-component batch export compiler pipeline system triggers routing action mappings
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


demo.launch(inbrowser=True)





