# Tool Call Slide_outline: finalize slide outline



def tool_outline():
    return [{
        "type": "function",
        "function": {
            "name": "slide_outline",
            "description": "Create an outline for a presentation",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Presentation title"},
                    "slides": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Slide titles in order",
                    },
                },
                "required": ["title", "slides"],
            },
        },
    }]



def slide_creation_tool():
    return [{
        "type": "function",
        "function": {
            "name": "slide_content_generator",
            "description": "Create the content for an individual slide of a presentation",
            "parameters": {
                "type": "object",
                "properties": {
                    "presentation_title": {
                        "type": "string",
                        "description": "Overall presentation title"
                    },
                    "slide_title": {
                        "type": "string",
                        "description": "Title of the slide to generate"
                    },
                    "all_slide_titles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "All slide titles in presentation order, for narrative context"
                    },
                    "content": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key points to highlight on this slide"
                    }
                },
                "required": [
                    "presentation_title",
                    "slide_title",
                    "all_slide_titles",
                    "content"
                ]
            }
        }
    }]