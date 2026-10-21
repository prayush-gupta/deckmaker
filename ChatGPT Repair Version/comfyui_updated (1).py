"""Minimal ComfyUI API client: load an API-format workflow, set prompt + seed,
queue it, wait for it to finish, and save the resulting image(s).
 
Needs only the standard library. Start ComfyUI first (default http://127.0.0.1:8188).
"""
import json
import random
import time
import urllib.parse
import urllib.request
import uuid
from def_prompts import comfyui_prompts
 
SERVER = "http://127.0.0.1:8188"
CLIENT_ID = str(uuid.uuid4())
 
# # Node ids come from your exported workflow_api.json -- open it and check them.
# PROMPT_NODE = "57:27"   # the text-encode node; its text lives in inputs["text"]
# SEED_NODE = "57:3"     # the sampler node; its seed lives in inputs["seed"]
 
 
def queue_prompt(SERVER, CLIENT_ID, workflow: dict) -> str:
    body = json.dumps({"prompt": workflow, "client_id": CLIENT_ID}).encode()
    req = urllib.request.Request(
        f"{SERVER}/prompt", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["prompt_id"]
 
 
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
 
 
def generate(model, SERVER, CLIENT_ID, workflow_path: str, prompt: str, PROMPT_NODE, SEED_NODE, out_prefix: str = "slide") -> list[str]:
    with open(workflow_path, encoding="utf-8") as f:
        workflow = json.load(f)
    
    if model == "qwen":
        col_name = "on_false"
    else:
        col_name = "text"
    
    workflow[PROMPT_NODE]["inputs"][col_name] = prompt
    workflow[SEED_NODE]["inputs"]["seed"] = random.randint(0, 2**32 - 1)
 
    prompt_id = queue_prompt(SERVER, CLIENT_ID, workflow)
    result = wait_for_result(SERVER, prompt_id)
 
    saved = []
    for node_output in result["outputs"].values():
        for i, img in enumerate(node_output.get("images", [])):
            dest = f"{out_prefix}_{len(saved)}.png"
            download_image(SERVER, img, dest)
            saved.append(dest)
    return saved


def comfyui_img_generator(slide_title, slide_content, file_name):#, file_name2):
    system_prompt = comfyui_prompts(slide_title, slide_content)
    SERVER = "http://127.0.0.1:8188"
    CLIENT_ID = str(uuid.uuid4())

    # Node ids come from your exported workflow_api.json -- open it and check them.
    PROMPT_NODE = "57:27"   # the text-encode node; its text lives in inputs["text"]
    SEED_NODE = "57:3"     # the sampler node; its seed lives in inputs["seed"]
    workflow_path = "workflow_api_z_image.json"
    # print(slide_content)
    files = generate("z_image", SERVER, CLIENT_ID, workflow_path, system_prompt, PROMPT_NODE, SEED_NODE, file_name)

    print()

    return file_name

