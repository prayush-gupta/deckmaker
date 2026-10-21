import json
import os
import time
import urllib.request
import gradio as gr
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from def_prompts import slide_gen_prompt
from imp_functions import response_generator

# --- CONFIGURATION & CONSTANTS ---
MAX_SLIDES = 25
COMFYUI_API_URL = "http://127.0.0.1:8188/prompt"
SESSIONS_DIR = "presentation_sessions"
OUTPUT_DIR = "generated_presentations"
PPT_DIR = "generated_presentations/ppt1"

os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PPT_DIR, exist_ok=True)

# A mapping dictionary linking template labels to thumbnail image assets
LAYOUT_TEMPLATES = {
    "Minimalist Title Centered": "https://images.unsplash.com/photo-1626785774573-4b799315345d?w=150&q=80",
    "Split Text & Image": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=150&q=80",
    "Three-Column Feature Grid": "https://images.unsplash.com/photo-1557683316-973673baf926?w=150&q=80",
    "Technical Diagram Grid": "https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=150&q=80",
    "Big Metric Callout": "https://images.unsplash.com/photo-1614850523459-c2f4c699c52e?w=150&q=80",
}
GALLERY_ITEMS = [(img, name) for name, img in LAYOUT_TEMPLATES.items()]


# --- CORE PLATFORM EVENT HANDLERS ---


def process_outline_and_suggest_layouts(slide_count, outline_text):
    """Parses outline data and returns layout targets for exactly 25 slots."""
    count = int(slide_count)
    updates = [gr.update(visible=True)]  # Master workspace visibility
    
    # Split text outline entries cleanly by newline markers
    lines = [line.strip() for line in outline_text.split("\n") if line.strip()]
    
    for i in range(MAX_SLIDES):  # Loops exactly 25 times
        if i < count:
            slide_title = lines[i] if i < len(lines) else f"Slide {i+1} Title"
            suggested_layout = "Split Text & Image"
            llm_insights = "💡 Keep bullet points concise and clear."
            # llm_questions = "❓ Does this section match your slide requirements?"
            
            if "Architecture" in slide_title or "Technical" in slide_title:
                suggested_layout = "Technical Diagram Grid"
            elif "Introduction" in slide_title or "Conclusion" in slide_title:
                suggested_layout = "Minimalist Title Centered"
                
            updates.extend([
                gr.update(visible=True),                                # 1. Slide group container
                gr.update(value=slide_title),                           # 2. Slide Title Box
                gr.update(value=f"• Key bullet point draft for layout"), # 3. Content Area
                # gr.update(value=suggested_layout),                      # 4. Layout Name field
                gr.update(value=llm_insights),                          # 5. LLM Insights Box
                # gr.update(value=llm_questions),                         # 6. LLM Questions Box
                gr.update(value=""),                                    # 7. Reset continuous feedback box
                gr.update(value=None),                                  # 8. Reset ComfyUI asset canvas
                # gr.update(value=False)                                  # 9. Reset approval lock checkbox
            ])
        else:
            # Hide unused slide rows up to the 25 max slide limit threshold
            updates.extend([
                gr.update(visible=False),                              # 1. Hide group container box
                gr.update(), gr.update(), gr.update(), gr.update(),    # 2, 3, 4, 5
                gr.update(), #gr.update()#, gr.update(), gr.update()     # 6, 7, 8, 9
            ])
            
    return updates  # Returns exactly 1 + (25 * 9) = 226 items



def on_thumbnail_select(evt: gr.SelectData):
    """Captures individual gallery image clicks and populates the layout text container."""
    return evt.value


def trigger_comfyui_generation(title, content, layout, feedback):
    """
    Packs slide parameters, pushes them to your local ComfyUI API backend,
    and returns the resulting pipeline asset generation canvas.
    """
    yield gr.update(value="⏳ Rendering via ComfyUI Pipeline..."), gr.update(interactive=False)
    
    style_guidance = f"Professional presentation asset, {layout} layout rules format."
    engineered_prompt = f"Title: {title}. Content: {content}. User request: {feedback}. Style: {style_guidance}"
    
    # Core API formatting template payload for ComfyUI execution
    comfy_workflow = {
        "3": {
            "inputs": {"seed": 42, "steps": 20, "cfg": 8, "sampler_name": "euler"},
            "class_type": "KSampler"
        },
        "6": {
            "inputs": {"text": engineered_prompt, "clip": ["4", 1]},
            "class_type": "CLIPTextEncode"
        }
        # Extend template variables with your exact local node configuration definitions...
    }
    
    try:
        # Mock request loop pipeline simulation
        time.sleep(1.5)
        placeholder_image = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=500"
        
        yield gr.update(interactive=True, value="🎨 Re-Generate Assets")
    except Exception as e:
        yield gr.update(interactive=True, value=f"❌ Engine Error: {str(e)}")


def slide_content_generator(slide_topic, deck_outline, slide_num, title, content, layout, feedback, ollama, model="llama3.1", conv_hist=[None]):

    if len(conv_hist)>1:
        conv_hist+=[{"role": "user", "content": feedback}]
    else:
        conv_hist=first_slide_gen(slide_topic, deck_outline, slide_num, title, content)

    response = response_generator(ollama, model, conv_hist)
    return response, conv_hist


def first_slide_gen(topic, slide_num, deck_outline, title, content):
    system_prompt, user_prompt = slide_gen_prompt(topic, slide_num, deck_outline, title, content)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

# --- SESSION MANAGEMENT & LOCAL PERSISTENCE ---


def save_user_session(session_name, count, outline, *slide_states):
    """Packs all 25 slide workspace layout matrix parameters into JSON."""
    if not session_name.strip():
        return "❌ Please specify a valid Session Identifier Name first!"
        
    slides_data = []
    step = 8  # properties to persist per slide row layout
    
    for i in range(MAX_SLIDES):
        idx = i * step
        slides_data.append({
            "title": slide_states[idx],
            "content": slide_states[idx + 1],
            "layout": slide_states[idx + 2],
            "insights": slide_states[idx + 3],
            "questions": slide_states[idx + 4],
            "feedback": slide_states[idx + 5],
            "preview": slide_states[idx + 6],
            "approved": slide_states[idx + 7]
        })
        
    session_payload = {
        "session_name": session_name,
        "slide_count": int(count),
        "outline": outline,
        "slides": slides_data
    }
    
    file_path = os.path.join(SESSIONS_DIR, f"{session_name.strip()}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(session_payload, f, indent=2)
        
    return f"💾 Session state saved safely to local storage: {file_path}"


def load_user_session(session_name):
    """Rehydrates the application window with values from saved files up to 25 slides."""
    file_path = os.path.join(SESSIONS_DIR, f"{session_name.strip()}.json")
    if not os.path.exists(file_path):
        return ["❌ Session target name not found!"] + [gr.update() for _ in range(3 + MAX_SLIDES * 9)]
        
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    count = data["slide_count"]
    updates = [
        f"📂 Successfully loaded session state profile: '{session_name}'",
        gr.update(value=count),
        gr.update(value=data["outline"]),
        gr.update(visible=True)
    ]
    
    for i in range(MAX_SLIDES):
        if i < count:
            s = data["slides"][i]
            updates.extend([
                gr.update(visible=True),
                gr.update(value=s["title"]),
                gr.update(value=s["content"]),
                gr.update(value=s["layout"]),
                gr.update(value=s["insights"]),
                gr.update(value=s["questions"]),
                gr.update(value=s["feedback"]),
                gr.update(value=s["preview"]),
                gr.update(value=s["approved"])
            ])
        else:
            updates.extend([gr.update(visible=False)] + [gr.update() for _ in range(8)])
            
    return updates


# --- POWERPOINT COMPILATION GENERATOR ENGINE ---

def compile_presentation_file(session_name, *slide_states):
    """Processes all active locked/approved slides using python-pptx and builds an output package file."""
    step = 8
    prs = Presentation()
    
    # Configure presentation dimensions for 16:9 widescreen format standard
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_slide_layout = prs.slide_layouts[6]
    
    approved_slides_count = 0
    
    for i in range(MAX_SLIDES):
        idx = i * step
        title_text = slide_states[idx]
        content_text = slide_states[idx + 1]
        layout_choice = slide_states[idx + 2]
        is_approved = slide_states[idx + 7]
        
        # Only compile items explicitly verified by the layout lock checkbox
        if is_approved:
            approved_slides_count += 1
            slide = prs.slides.add_slide(blank_slide_layout)
            
            # Core design color theme definitions
            dark_bg = RGBColor(0x1F, 0x29, 0x37)
            accent_blue = RGBColor(0x25, 0x63, 0xEB)
            text_color = RGBColor(0x37, 0x41, 0x51)
            
            if layout_choice == "Minimalist Title Centered":
                # Layout Variant A: Large centered hero headline typography blocks
                txBox = slide.shapes.add_textbox(Inches(2), Inches(2.5), Inches(9.333), Inches(2.5))
                tf = txBox.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = title_text
                p.font.size = Pt(48)
                p.font.bold = True
                p.font.color.rgb = dark_bg
                
                if content_text:
                    p2 = tf.add_paragraph()
                    p2.text = content_text
                    p2.font.size = Pt(20)
                    p2.font.color.rgb = accent_blue
                    
            elif layout_choice == "Split Text & Image":
                # Layout Variant B: Standard multi-column asymmetrical layout split blocks
                txBox = slide.shapes.add_textbox(Inches(0.8), Inches(1), Inches(6), Inches(5.5))
                tf = txBox.text_frame
                tf.word_wrap = True
                
                p = tf.paragraphs[0]
                p.text = title_text
                p.font.size = Pt(36)
                p.font.bold = True
                
                p2 = tf.add_paragraph()
                p2.text = content_text
                p2.font.size = Pt(18)
                p2.font.color.rgb = text_color
                
                # Image placeholder block structure indicators
                shape = slide.shapes.add_shape(
                    1, Inches(7.5), Inches(1.5), Inches(5), Inches(4.5)  # 1 = MSO_SHAPE.RECTANGLE
                )
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor(0xE5, 0xE7, 0xEB)
                shape.line.color.rgb = accent_blue
                
            else:
                # Layout Variant C: Standard text cascade listing presentation block fallback
                txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(11.333), Inches(5.5))
                tf = txBox.text_frame
                tf.word_wrap = True
                
                p = tf.paragraphs[0]
                p.text = title_text
                p.font.size = Pt(40)
                p.font.bold = True
                
                p2 = tf.add_paragraph()
                p2.text = f"[{layout_choice}]\n\n{content_text}"
                p2.font.size = Pt(20)
                
    if approved_slides_count == 0:
        return None, "⚠️ Compilation stalled: You must check 'Lock & Approve Slide Setup' on at least one slide workspace block."
        
    filename = f"{session_name.strip() if session_name.strip() else 'Presentation'}_compiled.pptx"
    output_path = os.path.join(OUTPUT_DIR, filename)
    prs.save(output_path)
    
    success_message = f"🚀 **Compilation successful!** Processed {approved_slides_count} slide configurations into design canvas outputs."
    return output_path, success_message


# --- GRADIO APPLICATION INTERFACE UI ASSEMBLY ---

with gr.Blocks(theme=gr.themes.Soft(), title="AI Presentation Studio Workspace") as demo:
    gr.Markdown("# 🎬 AI Presentation Studio & Design Engine Workspace")
    
    # --- PROFILES & TRACKING ENGINE CONTROLS ---
    with gr.Group():
        with gr.Row():
            session_input = gr.Textbox(
                label="📁 Local Project Session Identifier Name",
                placeholder="Enter workspace profiles target title name (e.g., Marketing-Q4-Deck)...",
                scale=3
            )
            save_state_btn = gr.Button("💾 Save Current Session State", variant="secondary")
            load_state_btn = gr.Button("📂 Resume Old Session Profile", variant="secondary")
        status_marquee = gr.Markdown("*Enter a profile identifier string to configure system snapshots.*")
        
    # --- CONTEXT SETUP STAGE LAYER ---
    with gr.Row():
        with gr.Column(scale=3):
            outline_input = gr.Textbox(
                label="Slide Outline Structure Context",
                lines=4,
                value="Introduction to Smart Automation Systems\nTechnical Workflow Architecture Blueprint\nFuture Development Milestones & Summary",
                placeholder="Enter titles or topic markers for each separate slide slice split by line break entries..."
            )
        with gr.Column(scale=1):
            count_input = gr.Number(
                label="Slide Target Count", value=3, precision=0, minimum=1, maximum=MAX_SLIDES
            )
            generate_btn = gr.Button("✨ Step 1: Initialize Workspace Canvas Elements", variant="primary")
            
    gr.Markdown("---")
    
    # --- DYNAMIC GRID INTERACTIVE COMPONENT WORKSPACE ---
    slide_boxes = []
    state_components_to_persist = []
    ui_slots = []
    
    with gr.Column(visible=False) as workspace_section:
        gr.Markdown("## 🛠️ Step 2: Refine Elements, Selection Layouts & Render ComfyUI Assets")
        
        for i in range(MAX_SLIDES):
            with gr.Group(visible=False) as slide_box:
                gr.Markdown(f"### 🖼️ Slide Workspace Canvas Unit Slot #{i+1}")
                
                with gr.Row():
                    # LEFT COLUMN CONFIGURATIONS PANEL
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
                                
                    # RIGHT COLUMN AI INSIGHTS & INTERACTION FEEDBACK CHANNELS
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
                    
                # Bind local scoped asset manipulation interactions per individual block unit loops
                layout_gallery.select(fn=on_thumbnail_select, outputs=slide_layout)
                render_btn.click(
                    fn=trigger_comfyui_generation,
                    inputs=[slide_title, slide_content, slide_layout, user_feedback_box],
                    outputs=[slide_preview, render_btn]
                )
                
                # Cache references structures maps for Gradio block configurations update operations
                slide_boxes.append(slide_box)
                state_components_to_persist.extend([
                    slide_title, slide_content, slide_layout, 
                    llm_insights_box, llm_questions_box, 
                    user_feedback_box, slide_preview, approve_chk
                ])
                ui_slots.extend([
                    slide_box, slide_title, slide_content, slide_layout, 
                    llm_insights_box, llm_questions_box, 
                    user_feedback_box, slide_preview, approve_chk
                ])
                
        # --- COMPILATION CONTROL TERMINAL PANEL LAYER ---
        gr.Markdown("---")
        gr.Markdown("## 🚀 Step 3: Global Production Compilation & Presentation Download Package Generation")
        with gr.Row():
            compile_btn = gr.Button("📦 Compile Approved Presentation Decks & Build PowerPoint File Package", variant="primary")
        with gr.Row():
            with gr.Column(scale=2):
                compilation_output_box = gr.Markdown()
            with gr.Column(scale=1):
                download_file_widget = gr.File(label="Download Generated PowerPoint (.pptx) File Package Structure")

    # --- GLOBAL COMPONENT MATRIX SYSTEM EVENT EVENT LINK ROUTERS ---
    
    # Initialize workspace components mappings event routers
    step1_outputs = [workspace_section] + ui_slots
    generate_btn.click(
        fn=process_outline_and_suggest_layouts,
        inputs=[count_input, outline_input],
        outputs=step1_outputs
    )
    
    # Local application configurations save tracking mechanisms
    save_state_btn.click(
        fn=save_user_session,
        inputs=[session_input, count_input, outline_input] + state_components_to_persist,
        outputs=status_marquee
    )
    
    # Local application files state restoration system actions routing setups
    load_state_btn.click(
        fn=load_user_session,
        inputs=[session_input],
        outputs=[status_marquee, count_input, outline_input, workspace_section] + ui_slots
    )
    
    # Global multi-component batch export compiler pipeline system triggers routing action mappings
    compile_btn.click(
        fn=compile_presentation_file,
        inputs=[session_input] + state_components_to_persist,
        outputs=[download_file_widget, compilation_output_box]
    )

if __name__ == "__main__":
    demo.queue().launch()
