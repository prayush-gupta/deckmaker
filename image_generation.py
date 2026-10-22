"""Minimal ComfyUI API client: load an API-format workflow, set prompt + seed + 16:9 size,
queue it, wait for it to finish, and save the resulting image(s).

Needs only the standard library (plus `openai`, already used elsewhere, for the
"design brief" call to your local Ollama).

SERVER LIFECYCLE (to flush VRAM): wrap a batch of images in `with comfyui_session():` - ComfyUI is
started once, used for every image inside the block, then shut down. A lone comfyui_img_generator()
call outside a block does the same for itself. To let this module start ComfyUI, set (PowerShell):
    $env:COMFYUI_DIR    = "C:\\path\\to\\ComfyUI"            # folder that contains main.py
    $env:COMFYUI_PYTHON = "C:\\path\\to\\ComfyUI\\venv\\Scripts\\python.exe"   # optional, default = this python
    $env:COMFYUI_ARGS   = "--listen 127.0.0.1 --port 8188"      # optional extra args
or set COMFYUI_CMD to the complete launch command instead. With none of these set, nothing is started
or stopped: the module just uses a ComfyUI that you started yourself.

Switch image model by changing DEFAULT_MODEL ("z_image" or "qwen") or passing model=... to
comfyui_img_generator().
"""
import contextlib
import json
import os
import platform
import random
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "gpt-oss")

from prompts import comfyui_prompts

SERVER = "http://127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")

# Node ids come from the exported *_api.json workflows.
MODEL_CONFIGS = {
    "z_image": {
        "workflow": str(APP_DIR / "z_image_turbo_workflow.json"),
        "prompt_node": "57:27",        # CLIPTextEncode
        "prompt_input": "text",
        "seed_node": "57:3",           # KSampler
        "size_node": "57:13",          # EmptySD3LatentImage (was hard-coded 1024x1024 -> square images)
        "size": (1536, 864),           # exact 16:9, multiples of 16
        "set": {
            "57:28": {"unet_name": os.getenv("COMFYUI_ZIMAGE_DIFFUSION_MODEL", "z_image_turbo_int8_convrot.safetensors")},
            "57:30": {"clip_name": os.getenv("COMFYUI_ZIMAGE_TEXT_ENCODER", "qwen_3_4b_fp8_mixed.safetensors")},
        },
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

DIRECTIONS = [
    "warm and earthy", "cool and techy", "bold and high-contrast", "soft and elegant", "futuristic neon accents",
    "natural and organic", "luxury gold accents", "playful but professional", "monochrome with one vivid accent",
    "sunset gradient palette", "ocean and teal palette", "forest and amber palette",
]
SHAPE_PLACEMENTS = [
    "along the right edge and in the upper-right corner",
    "in the lower-right corner and along the top-right",
    "as a tall band down the far right side",
    "in the upper-right and lower-right corners",
]
BRIEF_KEYS = ("background", "accent", "secondary", "shapes", "placement", "style", "mood")


# --- SERVER LIFECYCLE ---------------------------------------------------------------------------

COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "")
COMFYUI_PYTHON = os.environ.get("COMFYUI_PYTHON", sys.executable)
COMFYUI_ARGS = os.environ.get("COMFYUI_ARGS", "--listen 127.0.0.1 --port 8188")
COMFYUI_CMD = os.environ.get("COMFYUI_CMD", "")
STARTUP_TIMEOUT = 300       # seconds to wait for the server (first start loads Python, torch, nodes)
LOG_FILE = "comfyui_server.log"

_lock = threading.RLock()
_users = 0                  # how many `comfyui_session()` blocks are currently open
_proc = None                # the ComfyUI process WE started (None if the server was already running)
_warned_manual = False


def server_is_up(timeout=2) -> bool:
    try:
        with urllib.request.urlopen(f"{SERVER}/system_stats", timeout=timeout):
            return True
    except Exception:
        return False


def _split_args(text):
    """Split a command line into arguments, dropping the quotes around quoted parts.

    shlex.split(posix=False) keeps the quote characters inside each token on Windows, so a path
    like "C:\\Program Files\\x.yaml" would reach the program with literal quotes in it.
    """
    parts = shlex.split(text, posix=(os.name != "nt"))
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def _launch_command():
    if COMFYUI_CMD:
        return _split_args(COMFYUI_CMD), (COMFYUI_DIR or None)
    if COMFYUI_DIR and os.path.exists(os.path.join(COMFYUI_DIR, "main.py")):
        return [COMFYUI_PYTHON, "main.py"] + _split_args(COMFYUI_ARGS), COMFYUI_DIR
    return None, None


def start_server():
    """Start ComfyUI if it is not running. Returns True if THIS call started it."""
    global _proc, _warned_manual
    if server_is_up():
        return False
    cmd, cwd = _launch_command()
    if cmd is None:
        if not _warned_manual:
            print("[comfyui] No COMFYUI_DIR / COMFYUI_CMD set and no server running on "
                  f"{SERVER}: start ComfyUI yourself (it will not be shut down automatically).")
            _warned_manual = True
        return False

    print(f"[comfyui] starting server: {' '.join(cmd)}")
    log = open(LOG_FILE, "ab")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    _proc = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, **kwargs)

    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if _proc.poll() is not None:
            code, _proc = _proc.returncode, None
            raise RuntimeError(f"ComfyUI exited during startup (code {code}). See {LOG_FILE}.")
        if server_is_up():
            print("[comfyui] server ready")
            return True
        time.sleep(1)
    stop_server()
    raise TimeoutError(f"ComfyUI did not come up within {STARTUP_TIMEOUT}s. See {LOG_FILE}.")


def stop_server():
    """Shut down the ComfyUI process we started (and its children) so its VRAM is released."""
    global _proc
    proc, _proc = _proc, None
    if proc is None:
        return
    print("[comfyui] stopping server to free VRAM")
    try:
        if proc.poll() is None:
            if os.name == "nt":   # kill the whole process tree
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
    except Exception as e:
        print(f"[comfyui] problem while stopping server: {e}")
    time.sleep(2)   # let the driver release the GPU memory


def unload_ollama(model):
    """Best effort: ask Ollama to drop its model from VRAM before ComfyUI loads its own."""
    try:
        body = json.dumps({"model": model, "keep_alive": 0}).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


@contextlib.contextmanager
def comfyui_session(llm_model=None):
    """Start ComfyUI once, keep it for everything inside the block, then shut it down.
    Nested / concurrent blocks share one server; the last one out stops it."""
    global _users
    started_here = False
    with _lock:
        if _users == 0:
            if llm_model:
                unload_ollama(llm_model)
            started_here = start_server()
        _users += 1
    try:
        yield
    finally:
        with _lock:
            _users -= 1
            if _users == 0:
                stop_server()      # no-op if the server was already running before we got here



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
    # Some workflows expose more than one image output. Never write every returned
    # image to the same path: the last download would silently replace the earlier
    # image(s). Keep the first image at the expected <prefix>.png path and suffix
    # any additional outputs so each file remains available for inspection.
    for node_output in result.get("outputs", {}).values():
        for img in node_output.get("images", []):
            image_number = len(saved) + 1
            dest = f"{out_prefix}.png" if image_number == 1 else f"{out_prefix}_{image_number}.png"
            download_image(SERVER, img, dest)
            saved.append(dest)

    if not saved:
        status = result.get("status", {})
        raise RuntimeError(f"ComfyUI finished but returned no images. Status: {json.dumps(status)[:600]}")
    return saved


def _parse_brief(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    s, e = text.find("{"), text.rfind("}")
    data = json.loads(text[s:e + 1])
    brief = {}
    for k in BRIEF_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            brief[k] = re.sub(r"\s+", " ", v).strip(" .\"'")[:160]
    if brief.get("placement") not in SHAPE_PLACEMENTS:   # keep the left side free for text
        brief["placement"] = random.choice(SHAPE_PLACEMENTS)
    return brief


def design_brief(slide_title, slide_content, llm_model=DEFAULT_OLLAMA_MODEL, direction=None):
    """Ask the local LLM for a fresh colour / shape / style brief for this slide.
    Returns {} on any failure, in which case prompts falls back to its defaults."""
    try:
        from openai import OpenAI
        from prompts import design_brief_request
        client = OpenAI(api_key="ollama", base_url=OLLAMA_URL, timeout=90)
        system, user = design_brief_request(slide_title, slide_content, direction or random.choice(DIRECTIONS))
        from llm_helpers import robust_chat_completion
        resp = robust_chat_completion(
            client, llm_model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.7, max_tokens=2048,
        )
        return _parse_brief(resp.choices[0].message.content)
    except Exception as e:
        print(f"[comfyui] design brief failed, using defaults: {e}")
        return {}


def deck_design_brief(slide_titles, llm_model=DEFAULT_OLLAMA_MODEL, direction=None):
    """ONE design brief for the whole deck, so every slide shares the same palette, shapes and style."""
    titles = [t for t in slide_titles if t and t.strip()]
    outline = "; ".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return design_brief("Whole presentation (design one cohesive style for the deck)",
                        f"Deck outline: {outline}", llm_model, direction)


def comfyui_img_generator(slide_title, slide_content, file_name, model=DEFAULT_MODEL, llm_model=DEFAULT_OLLAMA_MODEL, direction=None, brief=None):
    """Render a text-free 16:9 backdrop for one slide, using the shared deck `brief` when given. Returns the path prefix (files are <prefix>_0.png).

    The slide text is NOT sent to the image model: image models garble small text, and the
    PPTX compiler overlays the real, editable text on top of the backdrop instead.
    """
    cfg = MODEL_CONFIGS[model]
    if brief is None:   # no deck-level brief supplied -> make a one-off one for this slide
        brief = design_brief(slide_title, slide_content, llm_model, direction)
    prompt = comfyui_prompts(slide_title, slide_content, brief)
    # print(f"[comfyui] prompt: {prompt}")

    out_dir = os.path.dirname(file_name)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # The brief (LLM) is done; now start ComfyUI, render, and shut it down again (unless a surrounding
    # `with comfyui_session():` keeps it alive for a whole batch).
    with comfyui_session(llm_model):
        generate(cfg, prompt, file_name)
    return file_name
