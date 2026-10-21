import json
import warnings
import gradio as gr
warnings.filterwarnings("ignore")

# --- CONFIGURATION & CONSTANTS ---
MAX_SLIDES = 25

LAYOUT_TEMPLATES = {
    "Minimalist Title Centered": "https://images.unsplash.com/photo-1626785774573-4b799315345d?w=150&q=80",
    "Split Text & Image": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=150&q=80",
    "Three-Column Feature Grid": "https://images.unsplash.com/photo-1557683316-973673baf926?w=150&q=80",
    "Technical Diagram Grid": "https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=150&q=80",
    "Big Metric Callout": "https://images.unsplash.com/photo-1614850523459-c2f4c699c52e?w=150&q=80",
}
GALLERY_ITEMS = [(img, name) for name, img in LAYOUT_TEMPLATES.items()]

# Custom CSS targeting Gradio Tab HTML selectors to inject color-coded status states
custom_styles = """
button.slide-approved-tab {
    background-color: #DEF7EC !important; 
    border: 2px solid #31C48D !important;
    color: #03543F !important;
    font-weight: bold !important;
}
button.slide-pending-tab {
    background-color: #FEF08A !important;
    border: 1px dashed #EAB308 !important;
    color: #713F12 !important;
}
"""

# Import backends
from gemini_code_v2 import (
    process_outline_and_suggest_layouts, 
    on_thumbnail_select, 
    trigger_comfyui_generation, 
    save_user_session, 
    load_user_session, 
    compile_presentation_file
)

# Mock interface functions from your environment structure setups
def lock(): return gr.update(interactive=False, value="Generating..."), gr.update(interactive=False)
def unlock(): return gr.update(interactive=True, value="Submit"), gr.update(interactive=True)
def reset_chat(): return "", ""
def response_streamer_outline(model, user_input_message, slide_count):
    yield "Outline generation stream mock placeholder data..."

# Form setup components definitions
message_input = gr.Textbox(label="Presentation Topic:", info="Hi, please share a brief overview of the presentation topic: ", lines=4)
model_selector = gr.Dropdown(["llama3.1", "deepseek-r1"], label="Select model", value="llama3.1")
message_output = gr.Markdown(label="Response:")
inputs = [model_selector, message_input]

with gr.Blocks(theme=gr.themes.Soft(), title="Presentation Maker", css=custom_styles) as demo:
    gr.Markdown("# 🎬 AI Presentation Studio & Design Engine Workspace")

    # --- PROFILES & TRACKING ENGINE CONTROLS ---
    with gr.Group():
        with gr.Row():
            session_input = gr.Textbox(
                label="📁 Local Project Session Identifier Name",
                placeholder="Enter workspace profiles target title name (e.g., Marketing-Q4-Deck)...",
                scale=2
            )
            save_state_btn = gr.Button("💾 Save Current Session")
            load_state_btn = gr.Button("📂 Resume Old Session")
        status_marquee = gr.Markdown("*Enter a profile identifier string to configure system snapshots.*")

        gr.Markdown("---")
        gr.Markdown("## Step 1: Define the Presentation Outline")

        with gr.Row():
            with gr.Column(scale=1):
                model_selector.render()
                message_input.render()
                count_input = gr.Number(
                    label="Slide Target Count", value=3, precision=0, minimum=1, maximum=MAX_SLIDES,
                    interactive=True, info="upto 25 slides"
                )
                with gr.Row():
                    reset_btn = gr.Button("Reset Chat")
                    submit_btn = gr.Button("Submit", variant="primary")
            with gr.Column(scale=2):
                message_output.render()
        
        inputs_list = [model_selector, message_input, count_input]

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("## Step 2: Initialize Dynamic Workspaces")
                generate_btn = gr.Button("✨ Step 2: Initialize Workspace Elements - Slides", variant="primary")

        gr.Markdown("---")

        # --- DYNAMIC HORIZONTAL TABBED COMPONENT WORKSPACE ---
        state_components_to_persist = []
        ui_slots = []
        
        with gr.Column(visible=False) as workspace_section:
            gr.Markdown("## 🛠 ## Step 3: Refine Elements, Selection Layouts & Render ComfyUI Assets")
            
            with gr.Tabs() as tabs_container:
                for i in range(MAX_SLIDES):
                    # We render individual workspaces inside discrete switchable Tab views
                    with gr.Tab(f"📄 Slide #{i+1}", visible=False, elem_classes=["slide-pending-tab"]) as slide_tab:
                        with gr.Group():
                            with gr.Row():
                                # LEFT WORKSPACE COLUMN: Text contents and template choices
                                with gr.Column(scale=3):
                                    slide_title = gr.Textbox(label="Slide Title/Header String Line")
                                    slide_content = gr.TextArea(label="Slide Window Content (Core Body Text Data)", lines=4)
                                    
                                    with gr.Row():
                                        with gr.Column(scale=2):
                                            layout_gallery = gr.Gallery(
                                                value=GALLERY_ITEMS,
                                                label="Visual Design Template Selection Matrix Options",
                                                columns=3,
                                                height="auto",
                                                allow_preview=False
                                            )
                                        with gr.Column(scale=1):
                                            slide_layout = gr.Textbox(label="Active Target Selected Layout", interactive=False)
                                            
                                # RIGHT WORKSPACE COLUMN: Feedback loops and AI tracking assets
                                with gr.Column(scale=2):
                                    with gr.Row():
                                        llm_insights_box = gr.Textbox(label="LLM Agent: Core Architectural Insights", interactive=False)
                                        llm_questions_box = gr.Textbox(label="LLM Agent: Open Structuring Questions", interactive=False)
                                        
                                    user_feedback_box = gr.Textbox(
                                        label="User Adjustment Input Panel (Continuous Feedback Channel)",
                                        placeholder="Type alternative styling descriptors, data metrics to emphasize, or updates...",
                                        lines=3
                                    )
                                    slide_preview = gr.Image(label="Generated ComfyUI Workspace Canvas Visual Element Asset", type="filepath")
                                    
                            with gr.Row():
                                render_btn = gr.Button("🎨 Render & Sync ComfyUI Visual Assets", variant="secondary")
                                approve_chk = gr.Checkbox(label="Lock & Approve Slide Setup Matrix Configurations")
                            
                            # Real-time reactive CSS color status update triggers
                            def update_tab_status_color(checked):
                                if checked:
                                    return gr.update(elem_classes=["slide-approved-tab"])
                                return gr.update(elem_classes=["slide-pending-tab"])
                                
                            approve_chk.change(fn=update_tab_status_color, inputs=approve_chk, outputs=slide_tab)
                            
                            layout_gallery.select(fn=on_thumbnail_select, outputs=slide_layout)
                            render_btn.click(
                                fn=trigger_comfyui_generation,
                                inputs=[slide_title, slide_content, slide_layout, user_feedback_box],
                                outputs=[slide_preview, render_btn]
                            )
                            
                            state_components_to_persist.extend([
                                slide_title, slide_content, slide_layout, 
                                llm_insights_box, llm_questions_box, 
                                user_feedback_box, slide_preview, approve_chk
                            ])
                            ui_slots.extend([
                                slide_tab, slide_title, slide_content, slide_layout, 
                                llm_insights_box, llm_questions_box, 
                                user_feedback_box, slide_preview, approve_chk
                            ])
                            
            # --- COMPILATION CONTROL TERMINAL PANEL LAYER ---
            gr.Markdown("---")
            gr.Markdown("## 🚀 Step 4: Global Production Compilation & Presentation Download")
            with gr.Row():
                compile_btn = gr.Button("📦 Compile Approved Presentation Decks & Build PowerPoint File Package", variant="primary")
            with gr.Row():
                with gr.Column(scale=2):
                    compilation_output_box = gr.Markdown()
                with gr.Column(scale=1):
                    download_file_widget = gr.File(label="Download Generated PowerPoint (.pptx) File Package Structure")

        # --- EVENT WIRES & APPARATUS ROUTERS ---
        step1_outputs = [workspace_section] + ui_slots
        generate_btn.click(
            fn=process_outline_and_suggest_layouts,
            inputs=[count_input, message_input],
            outputs=step1_outputs
        )
        
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

        submit_btn.click(lock, None, [submit_btn, reset_btn]).then(
            response_streamer_outline, inputs_list, message_output, show_progress="full"
        ).then(unlock, None, [submit_btn, reset_btn])

        reset_btn.click(reset_chat, None, [message_input, message_output])

demo.launch()
