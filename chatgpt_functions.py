
import copy
import json
import gradio as gr

# --------------------------------------------------
# 1. CONNECT THESE FOUR FUNCTIONS TO YOUR EXISTING CODE
# --------------------------------------------------

def generate_outline(topic, audience, slide_count):
    """
    Call your model with tool_outline().
    Return:
    {
        "title": "...",
        "slides": ["...", "..."]
    }
    """
    raise NotImplementedError("Connect your outline tool")


def generate_slide_content(
    presentation_title,
    slide_title,
    all_slide_titles,
    previous_content=None,
    feedback=""
):
    """
    Call slide_content_generator for ONE slide.

    Pass the previous content and feedback on revisions.
    Return:
    {
        "title": slide_title,
        "content": ["...", "..."]
    }
    """
    raise NotImplementedError("Connect your slide content tool")


def render_slide(slide, presentation_context):
    """
    1. Select a layout template.
    2. Generate artwork through ComfyUI if needed.
    3. Assemble and render the slide.
    4. Return the path to the rendered image.
    """
    raise NotImplementedError("Connect your rendering pipeline")


def generate_review_questions(slide, image_path, context):
    """
    Ask your model to review the slide's content and rendered image.
    Return a list of specific questions, e.g.:
    [
        "Is the illustration too prominent?",
        "Should this slide emphasize cost or performance?"
    ]
    """
    raise NotImplementedError("Connect your review-question generator")


# --------------------------------------------------
# 2. WORKFLOW HELPERS
# --------------------------------------------------

def prepare_slide(state, feedback=""):
    """Generate and render only the current slide."""
    state = copy.deepcopy(state)
    i = state["index"]

    title = state["outline"]["slides"][i]
    previous = state["slides"].get(str(i), {})

    slide = generate_slide_content(
        presentation_title=state["outline"]["title"],
        slide_title=title,
        all_slide_titles=state["outline"]["slides"],
        previous_content=previous.get("content"),
        feedback=feedback,
    )

    context = {
        "slide_number": i + 1,
        "total_slides": len(state["outline"]["slides"]),
        "all_slide_titles": state["outline"]["slides"],
    }

    image_path = render_slide(slide, context)
    questions = generate_review_questions(
        slide, image_path, context
    )

    state["slides"][str(i)] = {
        **slide,
        "image_path": image_path,
        "questions": questions,
        "approved": False,
    }

    state["status"] = "review"
    return state


def display_current(state):
    """Convert workflow state into UI updates."""
    if not state or not state.get("outline"):
        return (
            "Create a presentation outline to begin.",
            None,
            "",
            gr.update(visible=False),
            gr.update(visible=False),
        )

    i = state["index"]
    titles = state["outline"]["slides"]

    if i >= len(titles):
        return (
            "## Presentation complete\n\nAll slides have been approved.",
            None,
            "",
            gr.update(visible=False),
            gr.update(visible=False),
        )

    slide = state["slides"].get(str(i), {})
    if not slide:
        return (
            f"## Slide {i + 1}: {titles[i]}\n\n"
            "Generate this slide to begin reviewing it.",
            None,
            "",
            gr.update(visible=True),
            gr.update(visible=True),
        )

    questions = slide.get("questions", [])
    question_text = "\n".join(
        f"{n}. {q}" for n, q in enumerate(questions, 1)
    )

    content = "\n".join(
        f"- {p}" for p in slide.get("content", [])
    )

    markdown = (
        f"## Slide {i + 1} of {len(titles)}: {slide['title']}\n\n"
        f"{content}\n\n"
        f"### Questions about this slide\n\n"
        f"{question_text or 'No additional questions.'}"
    )

    return (
        markdown,
        slide.get("image_path"),
        "",
        gr.update(visible=True),
        gr.update(visible=True),
    )


# --------------------------------------------------
# 3. GRADIO EVENT HANDLERS
# --------------------------------------------------

def create_outline(topic, audience, slide_count):
    if not topic.strip():
        raise gr.Error("Please enter a presentation topic.")

    outline = generate_outline(topic, audience, int(slide_count))

    state = {
        "outline": outline,
        "index": 0,
        "slides": {},
        "status": "outline_review",
        "topic": topic,
        "audience": audience,
    }

    text = "## Proposed outline\n\n"
    text += f"**{outline['title']}**\n\n"
    text += "\n".join(
        f"{i + 1}. {title}"
        for i, title in enumerate(outline["slides"])
    )

    return state, text


def start_review(state):
    if not state or not state.get("outline"):
        raise gr.Error("Generate an outline first.")

    state = copy.deepcopy(state)
    state = prepare_slide(state)
    return (state, *display_current(state))


def approve_slide(state):
    if not state or state.get("status") != "review":
        raise gr.Error("Generate a slide before approving it.")

    state = copy.deepcopy(state)
    i = state["index"]
    key = str(i)

    # Explicit approval is the only way to advance.
    state["slides"][key]["approved"] = True
    state["index"] += 1

    if state["index"] >= len(state["outline"]["slides"]):
        state["status"] = "complete"
        return (state, *display_current(state))

    # Generate the next slide only after approval.
    state = prepare_slide(state)
    return (state, *display_current(state))


def revise_slide(state, feedback, answers):
    if not state or state.get("status") != "review":
        raise gr.Error("There is no slide awaiting review.")

    feedback = (feedback or "").strip()
    answers = (answers or "").strip()

    if not feedback and not answers:
        raise gr.Error(
            "Please enter feedback or answers before requesting a revision."
        )

    combined_feedback = (
        f"User change requests:\n{feedback or 'None'}\n\n"
        f"Answers to AI-generated review questions:\n"
        f"{answers or 'None'}"
    )

    # Keep the index unchanged: revise the SAME slide.
    state = copy.deepcopy(state)
    state = prepare_slide(state, feedback=combined_feedback)

    return (state, *display_current(state))


# --------------------------------------------------
# 4. GRADIO UI
# --------------------------------------------------

with gr.Blocks(title="AI Presentation Builder") as demo:
    workflow = gr.State(None)

    gr.Markdown("# AI Presentation Builder")
    gr.Markdown(
        "Generate an outline, then review and approve each rendered slide."
    )

    with gr.Group():
        topic = gr.Textbox(
            label="Presentation topic",
            placeholder="e.g. AI adoption in healthcare",
        )
        audience = gr.Textbox(
            label="Target audience",
            value="Business professionals",
        )
        slide_count = gr.Number(
            label="Number of slides",
            value=8,
            precision=0,
        )
        outline_button = gr.Button("Generate outline", variant="primary")
        outline_display = gr.Markdown()
        start_button = gr.Button("Approve outline and start")

    gr.Markdown("---")

    slide_display = gr.Markdown()
    slide_image = gr.Image(
        label="Rendered slide preview",
        type="filepath",
    )

    answers = gr.Textbox(
        label="Answers to the questions above",
        placeholder=(
            "Answer any relevant questions, e.g. emphasize cost "
            "savings and make the illustration smaller."
        ),
        lines=4,
    )
    feedback = gr.Textbox(
        label="Additional revision instructions",
        placeholder="What else should change?",
        lines=3,
    )

    with gr.Row():
        revise_button = gr.Button("Revise this slide")
        approve_button = gr.Button(
            "Approve slide and continue",
            variant="primary",
        )

    outline_button.click(
        create_outline,
        inputs=[topic, audience, slide_count],
        outputs=[workflow, outline_display],
    )

    start_button.click(
        start_review,
        inputs=[workflow],
        outputs=[
            workflow, slide_display, slide_image, answers,
            revise_button, approve_button,
        ],
    )

    revise_button.click(
        revise_slide,
        inputs=[workflow, feedback, answers],
        outputs=[
            workflow, slide_display, slide_image, answers,
            revise_button, approve_button,
        ],
    )

    approve_button.click(
        approve_slide,
        inputs=[workflow],
        outputs=[
            workflow, slide_display, slide_image, answers,
            revise_button, approve_button,
        ],
    )

demo.queue().launch()
