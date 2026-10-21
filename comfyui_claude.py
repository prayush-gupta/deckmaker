"""Minimal ComfyUI API client: load an API-format workflow, set prompt + seed + 16:9 size,
queue it, wait for it to finish, and save the resulting image(s).

Needs only the standard library (plus `openai`, already used elsewhere, for the optional
"visual motif" call to your local Ollama). Start ComfyUI first (default http://127.0.0.1:8188).

Switch image model by changing DEFAULT_MODEL ("z_image" or "qwen") or passing model=... to
comfyui_img_generator().
"""
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from def_prompts import comfyui_prompts

SERVER = "http://127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())
OLLAMA_URL = "http://localhost:11434/v1"

# Node ids come from the exported *_api.json workflows.
MODEL_CONFIGS = {
    "z_image": {
        "workflow": "workflow_api_z_image.json",
        "prompt_node": "57:27",        # CLIPTextEncode
        "prompt_input": "text",
        "seed_node": "57:3",           # KSampler
        "size_node": "57:13",          # EmptySD3LatentImage (was hard-coded 1024x1024 -> square images)
        "size": (1536, 864),           # exact 16:9, multiples of 16
        "set": {},
    },
    "qwen": {
        "workflow": "workflow_api_qwen2_1.json",
        "prompt_node": "459:474",      # If/Else switch: with switch=False it passes "on_false" straight through
        "prompt_input": "on_false",
        "seed_node": "459:458",        # KSampler
        "size_node": "459:456",        # EmptyLatentImage (replaces the 1:1 ResolutionSelector link)
        "size": (1664, 928),           # Qwen-Image native 16:9 bucket
        "set": {"459:474": {"switch": False}},   # skip the built-in LLM prompt rewriter
    },
}
DEFAULT_MODEL = "z_image"

FALLBACK_MOTIF = "interconnected network nodes, thin flowing data lines and a few simple geometric shapes"


def queue_prompt(SERVER, CLIENT_ID, workflow: dict) -> str:
    body = json.dumps({"prompt": workflow, "client_id": CLIENT_ID}).encode()
    req = urllib.request.Request(
        f"{SERVER}/prompt", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)["prompt_id"]
    except urllib.error.HTTPError as e:
        # ComfyUI explains bad node ids / missing models in the response body - surface it
        detail = e.read().decode("utf-8", "ignore")[:800]
        raise RuntimeError(f"ComfyUI rejected the workflow ({e.code}): {detail}") from e


def wait_for_result(SERVER, prompt_id: str, timeout: float = 900) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(f"{SERVER}/history/{prompt_id}") as r:
            history = json.load(r)
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(1)
    raise TimeoutError(f"ComfyUI did not finish prompt {prompt_id} in {timeout}s")


def download_image(SERVER, info: dict, dest: str) -> None:
    # info has: filename, subfolder, type
    query = urllib.parse.urlencode(info)
    with urllib.request.urlopen(f"{SERVER}/view?{query}") as r, open(dest, "wb") as f:
        f.write(r.read())


def generate(cfg: dict, prompt: str, out_prefix: str = "slide") -> list[str]:
    with open(cfg["workflow"], encoding="utf-8") as f:
        workflow = json.load(f)

    for node, values in cfg.get("set", {}).items():
        workflow[node]["inputs"].update(values)

    workflow[cfg["prompt_node"]]["inputs"][cfg["prompt_input"]] = prompt
    workflow[cfg["seed_node"]]["inputs"]["seed"] = random.randint(0, 2**32 - 1)

    width, height = cfg["size"]
    workflow[cfg["size_node"]]["inputs"]["width"] = width
    workflow[cfg["size_node"]]["inputs"]["height"] = height

    prompt_id = queue_prompt(SERVER, CLIENT_ID, workflow)
    result = wait_for_result(SERVER, prompt_id)

    saved = []
    for node_output in result.get("outputs", {}).values():
        for img in node_output.get("images", []):
            dest = f"{out_prefix}_{len(saved)}.png"
            download_image(SERVER, img, dest)
            saved.append(dest)

    if not saved:
        status = result.get("status", {})
        raise RuntimeError(f"ComfyUI finished but returned no images. Status: {json.dumps(status)[:600]}")
    return saved


def visual_motif(slide_title, slide_content, llm_model="gpt-oss"):
    """Ask the local LLM for a short abstract-motif phrase for this slide (falls back safely)."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key="ollama", base_url=OLLAMA_URL, timeout=60)
        resp = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": (
                    "You choose a simple abstract visual motif for a presentation slide background. "
                    "Reply with ONE short noun phrase (max 15 words) naming abstract shapes or simple icons, "
                    "for example: rising bar charts, connected network nodes and a shield outline. "
                    "No sentences, no quotes, no text, letters, numbers, names or logos.")},
                {"role": "user", "content": f"Slide title: {slide_title}\nSlide content: {slide_content}"},
            ],
        )
        text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S).strip()
        text = text.splitlines()[0].strip(" \"'.") if text else ""
        return text[:160] or FALLBACK_MOTIF
    except Exception:
        return FALLBACK_MOTIF


def comfyui_img_generator(slide_title, slide_content, file_name, model=DEFAULT_MODEL, llm_model="gpt-oss"):
    """Render a text-free 16:9 backdrop for one slide. Returns the path prefix (files are <prefix>_0.png).

    The slide text is NOT sent to the image model: image models garble small text, and the
    PPTX compiler overlays the real, editable text on top of the backdrop instead.
    """
    cfg = MODEL_CONFIGS[model]
    motif = visual_motif(slide_title, slide_content, llm_model)
    prompt = comfyui_prompts(slide_title, slide_content, motif)

    out_dir = os.path.dirname(file_name)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    generate(cfg, prompt, file_name)
    return file_name
