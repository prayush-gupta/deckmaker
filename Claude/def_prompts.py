# Define our system prompt for the first step of defining the outline of the presentation


def deck_outline_prompt():
    system_prompt = """
    You are a very supportive assistant that helps the user in creating a presentation deck for them to use for their work.
    The user will provide you with a broad definition of the topic that they want you to make a presentation about
    You will respond back with a brief description of what you understood about the topic and create an outline detailing:

    1. How many slides there should be.
    2. Topic for each of the slides.

    Each response should be structured as 
    1. "Objective: " followed by your understanding of the objective.
    2. "Slide outline: " followed by the proposed outline in a bulleted list format so that reader can understand easily.

    Every time you share the outline, keep asking the user if they are happy with the outline so that we can proceed to the next steps of drafting the actual presentation.
    Once the user confirms, call the tool slide_outline.
    """

    user_prompt_prefix = """
    I would like to create a presentation deck for an upcoming meeting and I need your help in creating an outline for this presentation.
    Please clarify what you understood about the assignment and share a proposed outline for the final presentation. 
    The topic of my presentation is: 
    """

    outline_summarizer = """
    You are a helpful assistant that summarises the conversations to ensure that the user request for the presentation objective and structure of the deck are maintained throughout the process.
    You need to consume the entire conversation and summarize it to convey the following elements in brief but exhaustive and comprehensive details:
    1. The objective behind the entire exercise and the topic/rationale for the presentation
    2. The final structure of the presentation as agreed and confirmed by the user

    This information would be used by other agents to prepare the final deck so you need to ensure that the information here is accurate and detailed.
    """
    return system_prompt, user_prompt_prefix, outline_summarizer



def slide_gen_prompt(topic, slide_num, deck_outline, title, desc):
    system_prompt = """
    You are a very supportive assistant that helps the user in creating a presentation slide for the overall deck.
    The user will provide you the presentation topic, deck outline and titles and descriptions of the current slide and
    you will respond back with:

    1. Title Suggestions
    2. Concise but comprehensive content across the topic.

    Each response should end with 
    1. "Title: " followed by your recommendation for the slide title.
    2. "Slide Content: " followed by the proposed content for the slide

    Every time you share the outline, keep asking the user if they are happy with the outline so that we can proceed to the next steps of drafting the actual presentation.
    Once the user confirms, call the tool slide_outline.
    """

    user_prompt = f"""
    I am working on a presentation on this topic{topic} and I need your help in creating an outline for this slide number {slide_num} from the outline {deck_outline}.
    This current slide is about {title} and should describe {desc}.
    Please compile the slide title and the content in a clear and concise manner while ensuring that all relevant information is captured. Use the deck outline to ensure that the story narrative stays consistent, the story is well connected and there is little unnecessary repitition of information.
    """

    return system_prompt, user_prompt



DEFAULT_BRIEF = {
    "background": "deep navy blue",
    "accent": "electric blue",
    "secondary": "white",
    "shapes": "interconnected network nodes, thin flowing lines and a few simple geometric shapes",
    "placement": "along the right edge and in the upper-right corner",
    "style": "flat vector illustration with crisp clean edges",
    "mood": "calm, modern and professional",
}


def design_brief_request(slide_title, slide_content, direction):
    """System + user messages asking the LLM for a fresh design brief (JSON) for one slide backdrop."""
    system = (
        "You are an art director designing the text-free background style for presentation slides. "
        "If you are given a deck outline, design ONE cohesive style that suits the whole deck. "
        "Reply with ONLY a JSON object with these string keys:\n"
        '"background": a DARK base colour with a modifier (e.g. "deep forest green", "midnight plum", "charcoal slate"),\n'
        '"accent": one main accent colour with a modifier,\n'
        '"secondary": one supporting colour with a modifier,\n'
        '"shapes": the abstract shapes or simple icons to draw, tied to the slide topic (max 20 words),\n'
        '"placement": where the decoration sits, chosen ONLY from: '
        '"along the right edge and in the upper-right corner", '
        '"in the lower-right corner and along the top-right", '
        '"as a tall band down the far right side", '
        '"in the upper-right and lower-right corners",\n'
        '"style": the illustration style (e.g. flat vector, soft 3D glass, line-art, paper cut-out, isometric),\n'
        '"mood": three adjectives.\n'
        "Rules: the background MUST be dark so white text stays readable; the left two-thirds of the slide is "
        "always kept empty for text. Pick colours and shapes that suit the slide topic and the requested direction, "
        "and avoid defaulting to navy blue. Never include text, letters, numbers, names or logos. No commentary."
    )
    user = (
        f"Design direction to lean towards: {direction}\n"
        f"Slide title: {slide_title}\n"
        f"Slide content: {slide_content}"
    )
    return system, user


def comfyui_prompts(slide_title, slide_content, brief=None):
    """Descriptive prompt for a text-free 16:9 slide backdrop, built from an LLM design brief.

    Written as a plain scene description (not instructions): the image models used here run at
    cfg=1 with an empty/zeroed negative prompt, so "do not ..." lines have no effect. The slide text
    is deliberately NOT included, because the PPTX adds the real text on top.
    """
    b = dict(DEFAULT_BRIEF)
    b.update({k: v for k, v in (brief or {}).items() if isinstance(v, str) and v.strip()})
    return (
        f"A wide 16:9 minimalist corporate presentation background in {b['background']} with {b['secondary']} and a single "
        f"{b['accent']} accent colour. The left two-thirds of the frame is a calm, smooth, nearly flat {b['background']} "
        "surface with a very subtle soft gradient, left completely empty and uncluttered. "
        f"{b['placement'][0].upper() + b['placement'][1:]}, a refined abstract composition of {b['shapes']}, "
        f"drawn in {b['accent']} and {b['secondary']} with gentle depth. "
        "A few tiny dots and one thin circle outline sit near the lower-left corner for balance. "
        f"The style is {b['style']}, with a {b['mood']} mood and soft even ambient lighting. "
        "The image is purely abstract graphics with no text, no letters, no numbers and no logos."
    )
