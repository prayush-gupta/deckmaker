# This is a model loader but it failed miserably

def model_load(load_def = "LOCAL"):

    ollama_url = "http://localhost:11434/v1"
    ollama = OpenAI(api_key="ollama", base_url=ollama_url)

    if load_def != "LOCAL":
        load_dotenv(override=True)

        global openai, anthropic, gemini, deepseek, groq, grok, openrouter

        openai_api_key = os.getenv('OPENAI_API_KEY')
        anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
        google_api_key = os.getenv('GOOGLE_API_KEY')
        deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        groq_api_key = os.getenv('GROQ_API_KEY')
        grok_api_key = os.getenv('GROK_API_KEY')
        openrouter_api_key = os.getenv('OPENROUTER_API_KEY')

        anthropic_url = "https://api.anthropic.com/v1/"
        gemini_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        deepseek_url = "https://api.deepseek.com"
        groq_url = "https://api.groq.com/openai/v1"
        grok_url = "https://api.x.ai/v1"
        openrouter_url = "https://openrouter.ai/api/v1"

        openai = OpenAI()
        anthropic = OpenAI(api_key=anthropic_api_key, base_url=anthropic_url)
        gemini = OpenAI(api_key=google_api_key, base_url=gemini_url)
        deepseek = OpenAI(api_key=deepseek_api_key, base_url=deepseek_url)
        groq = OpenAI(api_key=groq_api_key, base_url=groq_url)
        grok = OpenAI(api_key=grok_api_key, base_url=grok_url)
        openrouter = OpenAI(base_url=openrouter_url, api_key=openrouter_api_key)




comfyui_system_prompt = """
Create a professional 16:9 widescreen PowerPoint slide BACKGROUND IMAGE.
This is a visual-only slide layout, NOT a finished slide.

ABSOLUTE REQUIREMENT: ZERO TEXT IN THE IMAGE.

Do not generate or draw any text, letters, words, numbers, typography,
headings, captions, labels, logos, watermarks, pseudo-writing, or symbols
that resemble written characters.

Treat all supplied slide information as semantic guidance only.
Translate its meaning into visual storytelling, not written language.

SLIDE DESIGN:
Theme: Market gaps and opportunities in the small-business lending ecosystem.
Style: Premium corporate consulting presentation, polished financial-services
visuals, sophisticated composition, clean geometry, subtle depth, professional
lighting, consistent visual language, restrained navy blue, teal, white,
and muted gold accents.

LAYOUT — 16:9 LANDSCAPE:

TOP HEADER AREA:
Reserve the upper 18% of the canvas as clean, empty, unobstructed space
for a title to be added later.
Use a simple, understated background with no objects or decorative marks
behind the reserved title area.

MAIN CONTENT AREA:
Use the central 62% of the canvas for three distinct visual zones,
arranged horizontally with generous spacing and clear visual separation.

LEFT ZONE — SMALL-BUSINESS LENDING CHALLENGES:
Illustrate a small business owner facing barriers to finance.
Show a small business storefront, financial documents without writing,
and a closed or restricted financial access metaphor.
Use visual cues for expensive borrowing and demanding collateral.
No currency symbols, numerals, or written markings.

CENTER ZONE — UNDERSERVED MARKETS:
Illustrate remote communities and rural businesses separated from
financial infrastructure.
Include a subtle landscape, small businesses, and a distant financial
service location or disconnected network nodes.
Also suggest emerging industries that lack adequate lending support.
Use visuals only, without maps containing labels or textual markings.

RIGHT ZONE — COMPLEXITY AND UNMET NEEDS:
Illustrate a business owner navigating a confusing maze-like process,
multiple document sheets with completely blank surfaces, and fragmented
financial service connections.
Suggest the need for flexible, tailored financial solutions through
visual metaphors such as a key fitting a unique lock or interconnected
modular shapes.

Keep the three zones balanced, visually coherent, and easy to distinguish.
Use realistic or refined semi-realistic illustrations rather than cartoon
characters. Avoid excessive detail and visual clutter.

BOTTOM TAKEAWAY AREA:
Reserve the bottom 20% as a clean, mostly empty band for a takeaway
statement to be added later.
Keep all important objects above this reserved area.

BACKGROUND AND NEGATIVE SPACE:
Use a light neutral background with subtle navy and teal gradients.
Maintain generous whitespace between all elements.
Do not place visual objects inside the reserved header or footer areas.
Ensure all visual elements have comfortable margins from the canvas edges.

STRICT TEXT EXCLUSION:
Every document, sign, screen, paper, storefront, building, and object
must be completely free of writing.
No text-like lines, fake handwriting, random glyphs, labels, numbers,
or decorative typography.
Do not write the slide title or any of its bullet points.
Do not include any letters or words anywhere in the image.

OUTPUT:
One clean, polished, text-free visual composition suitable for use as
a 16:9 PowerPoint slide background.
The final image must contain no visible text whatsoever.
"""