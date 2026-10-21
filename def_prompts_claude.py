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



def comfyui_prompts(slide_title, slide_content, motif=None):
    """Descriptive prompt for a text-free 16:9 slide backdrop.

    Written as a plain scene description (not instructions): the image models used here run at
    cfg=1 with an empty/zeroed negative prompt, so "do not ..." lines have no effect and
    instruction-style prompts get drawn as content. The slide text is deliberately NOT included,
    because the PPTX adds the real text on top.
    """
    motif = motif or "interconnected network nodes, thin flowing data lines and a few simple geometric shapes"
    return (
        "A wide 16:9 minimalist corporate presentation background in deep navy blue with white and a single "
        "electric-blue accent colour. The left two-thirds of the frame is a calm, smooth, nearly flat dark navy "
        "surface with a very subtle soft gradient, left completely empty and uncluttered. "
        f"Along the right edge and in the upper-right corner, a refined abstract motif of {motif}, "
        "drawn with thin glowing electric-blue lines, small white dots and soft translucent geometric shapes. "
        "A few tiny white dots and one thin circle outline sit near the lower-left corner for balance. "
        "Flat vector illustration style with crisp clean edges, gentle depth and soft even ambient lighting. "
        "The image is purely abstract graphics with no text, no letters, no numbers and no logos."
    )
