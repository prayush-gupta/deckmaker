# Model Setup step
### This is the user context code that requests the user to describe the presentation topic

import json
from openai import OpenAI
import gradio as gr
import warnings
warnings.filterwarnings("ignore")

# --- CONFIGURATION & CONSTANTS ---
MAX_SLIDES = 25
# COMFYUI_API_URL = "http://127.0.0.1:8188/prompt"
# SESSIONS_DIR = "presentation_sessions"
# OUTPUT_DIR = "generated_presentations"
# PPT_DIR = "generated_presentations/ppt1"

# os.makedirs(SESSIONS_DIR, exist_ok=True)
# os.makedirs(OUTPUT_DIR, exist_ok=True)
# os.makedirs(PPT_DIR, exist_ok=True)

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
from imp_functions import (first_prompt, response_append, slide_outline, convo_backup, 
                            summarize_conversation, title_list, content_list)
from tools_dec import tool_outline, slide_creation_tool
from gemini_code_fixed import process_outline_and_suggest_layouts, on_thumbnail_select, trigger_comfyui_generation, save_user_session, load_user_session, compile_presentation_file


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

            convo_backup(global_prompt, file_paths[0])

            summary_stages.append(summarize_conversation(ollama, file_paths[0], outline_summarizer, model))

            yield "Outline finalized, data saved..."

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
    """
    Accepts data for a single slide, updates it via your LLM engine based on user feedback,
    and returns a gr.update() block back to the frontend.
    """
    if not user_feedback.strip():
        # Avoid call overhead if the feedback container is empty
        return current_title, current_content, "⚠️ Please provide feedback before re-generating."
        
    # Construct a refining prompt for your model setup
    refine_prompt = [
        {"role": "system", "content": "You are a professional deck layout editor. Modify the provided slide title and content based strictly on the user feedback. Return valid JSON containing keys 'title' and 'content' only."},
        {"role": "user", "content": f"Current Title: {current_title}\nCurrent Content: {current_content}\nUser Feedback: {user_feedback}"}
    ]
    
    try:
        # Fall back to default model if specified
        target_model = "gpt-oss" if model_selection == "Default" else model_selection
        
        # Execute prompt streaming/generation (non-streaming helper used here for cleanliness)
        response = ollama.chat.completions.create(
            model=target_model,
            messages=refine_prompt,
            response_format={"type": "json_object"} # Ensure clean structures
        )
        
        result_json = json.loads(response.choices[0].message.content)
        new_title = result_json.get("title", current_title)
        new_content = result_json.get("content", current_content)
        
        # Keep global arrays aligned with manual modifications
        global slide_titles, slide_contents
        slide_titles[slide_index] = new_title
        slide_contents[slide_index] = new_content
        
        # Return updates mapping value strings and the title's UI layout label
        return (
            gr.update(value=new_title, label=new_title), 
            gr.update(value=new_content), 
            f"✅ Slide updated successfully using model: {target_model}"
        )
        
    except Exception as e:
        return current_title, current_content, f"❌ Re-generation error: {str(e)}"


# --- UPDATED SLIDES_SETUP FUNCTION ---
def slides_setup(count_input, message_input):
    global slide_titles, slide_contents
    
    # 1. Generate the underlying data
    slide_titles = title_list(ollama, global_prompt)
    slide_contents = content_list(ollama, global_prompt)

    # 2. Get the layout configuration outputs from your original function
    layout_results = process_outline_and_suggest_layouts(count_input, message_input)
    
    workspace_visible = layout_results[0]
    remaining_slots = layout_results[1:]
    
    updated_slots = []
    slot_idx = 0
    
    # 3. Explicitly pair the new text values with your layout slots
    for i in range(MAX_SLIDES):
        # Every slide block has 6 corresponding UI elements in ui_slots:
        slide_box = remaining_slots[slot_idx]
        title_box_state = remaining_slots[slot_idx + 1]
        content_box_state = remaining_slots[slot_idx + 2]
        slide_layout = remaining_slots[slot_idx + 3]
        llm_insights = remaining_slots[slot_idx + 4]
        user_feedback = remaining_slots[slot_idx + 5]
        
        # Overwrite values and labels dynamically using gr.update()
        if i < len(slide_titles):
            new_title = slide_titles[i]
            new_content = slide_contents[i]
            
            title_box_state = gr.update(value=new_title, label=new_title or f"Slide {i+1} Title")
            content_box_state = gr.update(value=new_content)
        
        updated_slots.extend([slide_box, title_box_state, content_box_state, slide_layout, llm_insights, user_feedback])
        slot_idx += 6

    # Return everything back as event outputs to refresh the browser UI
    return [workspace_visible] + updated_slots

message_input = gr.Textbox(label="Presentation Topic", info="Hi, please share a brief overview of the presentation topic: ", lines=7)
model_type_selector = gr.Dropdown(["ollama"], label="Select model type", value="ollama")
model_selector = gr.Dropdown(model_list, label="Select model", value="gpt-oss")
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
    global p_cnt, global_prompt
    p_cnt = 0
    global_prompt = {}
    return "", ""

def lock():
    return gr.update(interactive=False, value="Generating..."), gr.update(interactive=False)

def unlock():
    # button_message = "Submit"
    # if deck_outline:
    #     button_message = "Create Slides Content"
    return gr.update(interactive=True, value="Submit"), gr.update(interactive=True)


with gr.Blocks(theme=gr.themes.Soft(), title="Presentation Maker") as demo:
    gr.Markdown("# 🎬 AI Presentation Studio & Design Engine Workspace")

    # --- PROFILES & TRACKING ENGINE CONTROLS ---
    with gr.Group():
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
        gr.Markdown("## Describe the Presentation Topic")
        gr.Markdown("---")
        gr.HTML("<div style='height: 1px;'></div>")

        with gr.Row():
            with gr.Column(scale=1):
                model_selector.render()
                message_input.render()
                count_input = gr.Number(
                    label="Slide Target Count", value=3, precision=0, minimum=1, maximum=MAX_SLIDES
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

        # gr.Markdown("---")
        gr.HTML("<div style='height: 25px;'></div>")
        gr.Markdown("## 🛠️ Slides Content and Layout")
        gr.Markdown("---")
        gr.HTML("<div style='height: 1px;'></div>")

        # --- DYNAMIC GRID INTERACTIVE COMPONENT WORKSPACE ---
        slide_boxes = []
        state_components_to_persist = []
        ui_slots = []
        
        with gr.Column(visible=False) as workspace_section:

            for i in range(MAX_SLIDES):
                # with gr.Group(visible=False) as slide_box:
                with gr.Accordion(label=f'Slide {i+1}: ', open=True) as slide_box:
                    # if i>0:
                    #     gr.Markdown("---")
                    gr.Markdown(f"## 🖼️ Slide {i+1}")
                    
                    with gr.Row():
                        # LLM FEEDBACK/SUGGESTIONS
                        with gr.Column(scale=3):
                            with gr.Row():
                                llm_insights_box = gr.Markdown(label="Model Response:")
                
                        gr.HTML("<div style='width: 2px;'></div>")

                        # SLIDE CONTENTS
                        with gr.Column(scale=5):
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
                        render_btn = gr.Button(f"🎨 Re-generate slide {i+1}", variant="secondary")
                        approve_chk = gr.Button(f"✅ Confirm Slide {i+1} content", variant="primary")
                        
                    gr.HTML("<div style='height: 25px;'></div>")
                    
                    # Bind local scoped asset manipulation interactions per individual block unit loops
                    layout_gallery.select(fn=on_thumbnail_select, outputs=slide_layout)
                    
                    # render_btn.click(
                    #     fn=trigger_comfyui_generation,
                    #     inputs=[title_textbox, content_textbox, slide_layout, user_feedback_box],
                    #     outputs=[render_btn]
                    # )

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
                        outputs=[title_textbox, content_textbox, llm_insights_box] 
                    )

                    
                    # Cache references structures maps for Gradio block configurations update operations
                    slide_boxes.append(slide_box)
                    state_components_to_persist.extend([
                        title_textbox, content_textbox, slide_layout,
                        llm_insights_box, user_feedback_box
                    ])
                    ui_slots.extend([
                        slide_box, title_textbox, content_textbox, slide_layout,
                        llm_insights_box, user_feedback_box
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
        generate_btn.click(
            fn=slides_setup,
            inputs=[count_input, message_input],
            outputs=step1_outputs
        )
        
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

        submit_btn.click(lock, None, [submit_btn, reset_btn]).then(
        response_streamer_outline, inputs, message_output, show_progress="full"
        ).then(unlock, None, [submit_btn, reset_btn])

        message_input.submit(
            response_streamer_outline, inputs, message_output, show_progress="full"
        )

        reset_btn.click(reset_chat, None, [message_input, message_output])


demo.launch()#inbrowser=True)