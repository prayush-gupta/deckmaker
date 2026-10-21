# Reviewed presentation-maker code

## Files
- `user_context.py`: Gradio application and event wiring
- `gemini_code_fixed.py`: slide-slot visibility, session persistence, and PowerPoint compilation
- `comfyui.py`: ComfyUI API client and image-generation entry point
- `def_prompts.py`: outline, slide, and text-free artwork prompts
- `imp_functions.py`: prompt helpers and slide title/content extraction

## Installation
1. Back up the existing five files.
2. Copy these files into the project directory, replacing the matching files.
3. Keep your existing `tools_dec.py`, `workflow_api_z_image.json`, and local Ollama/ComfyUI setup in place.
4. Run `python user_context.py`.

## Important notes
- All five Python files pass Python syntax compilation.
- This does not verify your local Ollama models, ComfyUI workflow node IDs, `tools_dec.py` tool schema, or the installed Gradio/Python package versions.
- The ComfyUI workflow is expected at `workflow_api_z_image.json` relative to the working directory. Its prompt node is `57:27` and seed node is `57:3`, matching the values in your uploaded code.
- The slide workspace uses five UI updates per slide (group, title, content, layout, feedback). Session save/load and PowerPoint compilation each use four data values per slide (title, content, layout, feedback), so their indices stay aligned.
