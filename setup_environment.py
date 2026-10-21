#!/usr/bin/env python3
"""Cross-platform first-run installer and launcher for AI Presentation Studio.

The first run installs the app's Python environment, Ollama, one local LLM,
ComfyUI, and the Z-Image model files. Model downloads are large; see README.md.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
APP_VENV = ROOT / ".venv"
RUNTIME_DIR = ROOT / "runtime"
DEFAULT_OLLAMA_MODEL = "gpt-oss"
COMFYUI_REPO = "https://github.com/Comfy-Org/ComfyUI.git"
HF_BASE = "https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files"


def app_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def load_env_file() -> None:
    """Small .env reader for the setup script itself; no third-party dependency needed."""
    path = ROOT / ".env"
    if not path.exists():
        example = ROOT / ".env.example"
        if example.exists():
            shutil.copyfile(example, path)
            print("[setup] Created local .env from .env.example")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def update_env(values: dict[str, str]) -> None:
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replaced = set()
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                output.append(f"{key}={values[key]}")
                replaced.add(key)
                continue
        output.append(line)
    for key, value in values.items():
        if key not in replaced:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    for key, value in values.items():
        os.environ[key] = value


def run(command: list[str], *, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    print("\n[run] " + subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=str(cwd or ROOT), check=check)


def ensure_app_venv(args: list[str]) -> int:
    """Create app venv, install app requirements, then re-execute inside it."""
    if os.environ.get("PRESENTATION_STUDIO_IN_VENV") == "1":
        return 0
    current = sys.version_info
    if not ((3, 11) <= (current.major, current.minor) <= (3, 13)):
        print(f"[error] Python 3.11–3.13 is required. Found {platform.python_version()}.")
        print("Install Python 3.12, then run start_windows.bat or ./start.sh again.")
        return 2

    py = app_python(APP_VENV)
    if not py.exists():
        print(f"[setup] Creating application virtual environment at {APP_VENV}")
        venv.EnvBuilder(with_pip=True, clear=False).create(APP_VENV)
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    env = os.environ.copy()
    env["PRESENTATION_STUDIO_IN_VENV"] = "1"
    result = subprocess.run([str(py), str(ROOT / "setup_environment.py"), *args], cwd=str(ROOT), env=env)
    return result.returncode


def find_ollama() -> Optional[str]:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = []
    if os.name == "nt":
        candidates += [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Ollama" / "ollama.exe",
        ]
    elif platform.system() == "Darwin":
        candidates += [Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama")]
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def ensure_git() -> str:
    git = shutil.which("git")
    if git:
        return git
    system = platform.system()
    print("[setup] Git was not found; attempting to install it.")
    if system == "Windows" and shutil.which("winget"):
        run(["winget", "install", "--id", "Git.Git", "-e", "--source", "winget",
             "--accept-package-agreements", "--accept-source-agreements"])
        git = shutil.which("git")
        if not git:
            for candidate in [Path("C:/Program Files/Git/cmd/git.exe"), Path("C:/Program Files/Git/bin/git.exe")]:
                if candidate.exists():
                    git = str(candidate)
                    os.environ["PATH"] = str(candidate.parent) + os.pathsep + os.environ.get("PATH", "")
                    break
    elif system == "Darwin" and shutil.which("brew"):
        run(["brew", "install", "git"])
        git = shutil.which("git") or "/usr/bin/git"
    elif system == "Linux" and shutil.which("apt-get") and shutil.which("sudo"):
        run(["sudo", "apt-get", "update"])
        run(["sudo", "apt-get", "install", "-y", "git"])
        git = shutil.which("git") or "/usr/bin/git"
    if not git or not Path(git).exists():
        raise RuntimeError("Git is required to download ComfyUI. Install Git and rerun the launcher.")
    return git


def install_ollama() -> str:
    ollama = find_ollama()
    if ollama:
        return ollama
    print("[setup] Ollama not found; attempting the official platform installation.")
    system = platform.system()
    if system == "Windows":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            raise RuntimeError("PowerShell is required to install Ollama. Install Ollama from https://ollama.com/download and rerun.")
        run([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://ollama.com/install.ps1 | iex"])
    elif system == "Linux":
        run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"])
    elif system == "Darwin":
        if shutil.which("brew"):
            run(["brew", "install", "ollama"])
        else:
            raise RuntimeError("Install Homebrew, then rerun, or install Ollama from https://ollama.com/download.")
    else:
        raise RuntimeError(f"Unsupported operating system: {system}")
    ollama = find_ollama()
    if not ollama:
        raise RuntimeError("Ollama installation ran but its CLI was not found. Restart the terminal and rerun this launcher.")
    return ollama


def ollama_base() -> str:
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def ollama_tags() -> list[str]:
    try:
        with urllib.request.urlopen(ollama_base() + "/api/tags", timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        return sorted({str(item.get("name") or item.get("model")) for item in data.get("models", [])
                       if item.get("name") or item.get("model")})
    except Exception:
        return []


def wait_for_ollama(timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ollama_tags() or api_is_responding():
            return
        time.sleep(2)
    raise TimeoutError("Ollama API did not become ready at " + ollama_base() + ". Check Ollama and its logs.")


def api_is_responding() -> bool:
    try:
        with urllib.request.urlopen(ollama_base() + "/api/tags", timeout=2):
            return True
    except Exception:
        return False


def ensure_ollama_running(ollama: str) -> None:
    if api_is_responding():
        return
    print("[setup] Starting Ollama service...")
    log_path = ROOT / "ollama_server.log"
    log = open(log_path, "ab")
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([ollama, "serve"], cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, **kwargs)
    except Exception as exc:
        log.close()
        raise RuntimeError(f"Could not start Ollama. See {log_path}: {exc}") from exc
    wait_for_ollama()


def pull_ollama_model(model: str) -> None:
    if model in ollama_tags():
        print(f"[ollama] Model already installed: {model}")
        return
    print(f"[ollama] Downloading model {model}. This may take a while.")
    payload = json.dumps({"name": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(ollama_base() + "/api/pull", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    last_status = None
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            for raw in response:
                if not raw.strip():
                    continue
                item = json.loads(raw.decode("utf-8"))
                status = item.get("status", "")
                if status and status != last_status:
                    print(f"[ollama] {status}")
                    last_status = status
                if item.get("error"):
                    raise RuntimeError(item["error"])
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not pull Ollama model {model}: {exc}") from exc
    print(f"[ollama] Model ready: {model}")


def nvidia_vram_gb() -> Optional[float]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        result = subprocess.run([nvidia_smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10, check=True)
        values = [float(line.strip()) / 1024 for line in result.stdout.splitlines() if line.strip()]
        return max(values) if values else None
    except Exception:
        return None


def nvidia_compute_capability() -> Optional[float]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        result = subprocess.run([nvidia_smi, "--query-gpu=compute_cap", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=10, check=True)
        values = [float(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        return min(values) if values else None
    except Exception:
        return None


def select_image_models() -> tuple[str, str, bool]:
    vram = nvidia_vram_gb()
    if vram is not None and vram >= 24:
        return "z_image_turbo_bf16.safetensors", "qwen_3_4b.safetensors", False
    # INT8 + FP8 uses significantly less disk/VRAM than the full BF16 workflow.
    # It requires a recent ComfyUI build; the setup script clones the current official branch.
    return "z_image_turbo_int8_convrot.safetensors", "qwen_3_4b_fp8_mixed.safetensors", vram is None or vram < 16


def ensure_comfyui(git: str) -> tuple[Path, Path, str, str, bool]:
    configured = os.getenv("COMFYUI_DIR", "").strip()
    if configured and (Path(configured) / "main.py").is_file():
        comfy_dir = Path(configured).resolve()
    else:
        comfy_dir = RUNTIME_DIR / "ComfyUI"
    if not (comfy_dir / "main.py").is_file():
        comfy_dir.parent.mkdir(parents=True, exist_ok=True)
        if comfy_dir.exists() and any(comfy_dir.iterdir()):
            raise RuntimeError(f"ComfyUI directory exists but is incomplete: {comfy_dir}. Rename it and rerun setup.")
        print(f"[setup] Cloning ComfyUI into {comfy_dir}")
        run([git, "clone", "--depth", "1", COMFYUI_REPO, str(comfy_dir)])
    comfy_venv = comfy_dir / ".venv"
    comfy_py = app_python(comfy_venv)
    if not comfy_py.exists():
        print(f"[setup] Creating ComfyUI environment at {comfy_venv}")
        venv.EnvBuilder(with_pip=True, clear=False).create(comfy_venv)
    model_name, text_name, low_vram = select_image_models()
    marker = comfy_dir / ".presentation_studio_setup.json"
    torch_kind = ""
    if shutil.which("nvidia-smi"):
        capability = nvidia_compute_capability()
        cuda_wheel = "cu126" if capability is not None and capability < 7.0 else "cu130"
        torch_kind = "nvidia-" + cuda_wheel
        torch_cmd = [str(comfy_py), "-m", "pip", "install", "torch", "torchvision", "torchaudio",
                     "--extra-index-url", f"https://download.pytorch.org/whl/{cuda_wheel}"]
    elif platform.system() == "Linux" and shutil.which("rocminfo"):
        torch_kind = "amd-rocm72"
        torch_cmd = [str(comfy_py), "-m", "pip", "install", "torch", "torchvision", "torchaudio",
                     "--index-url", "https://download.pytorch.org/whl/rocm7.2"]
    else:
        torch_kind = "default-mps-or-cpu"
        torch_cmd = [str(comfy_py), "-m", "pip", "install", "torch", "torchvision", "torchaudio"]
    override_index = os.getenv("COMFYUI_TORCH_INDEX_URL", "").strip()
    if override_index:
        torch_kind = "custom:" + override_index
        torch_cmd = [str(comfy_py), "-m", "pip", "install", "torch", "torchvision", "torchaudio",
                     "--index-url", override_index]
    prior = {}
    if marker.exists():
        try:
            prior = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not prior.get("dependencies_installed") or prior.get("torch_kind") != torch_kind:
        run([str(comfy_py), "-m", "pip", "install", "--upgrade", "pip"])
        run(torch_cmd)
        run([str(comfy_py), "-m", "pip", "install", "-r", str(comfy_dir / "requirements.txt")])
        marker.write_text(json.dumps({"dependencies_installed": True, "torch_kind": torch_kind}, indent=2), encoding="utf-8")
    else:
        print("[setup] ComfyUI Python dependencies already installed.")
    return comfy_dir, comfy_py, model_name, text_name, low_vram


def download_file(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 100_000_000:
        print(f"[models] Already downloaded: {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "AI-Presentation-Studio-setup/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    print(f"[models] Downloading {dest.name} (large file; partial downloads can resume)...")
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except Exception as exc:
        raise RuntimeError(f"Could not download {dest.name} from {url}: {exc}") from exc
    status = getattr(response, "status", response.getcode())
    if offset and status != 206:
        offset = 0
    mode = "ab" if offset and status == 206 else "wb"
    total = int(response.headers.get("Content-Length", "0") or 0) + (offset if mode == "ab" else 0)
    written = offset if mode == "ab" else 0
    last_report = written
    with response, open(part, mode) as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            written += len(chunk)
            if written - last_report >= 256 * 1024 * 1024:
                if total:
                    print(f"[models] {dest.name}: {written / 1024**3:.2f}/{total / 1024**3:.2f} GiB")
                else:
                    print(f"[models] {dest.name}: {written / 1024**3:.2f} GiB downloaded")
                last_report = written
    if part.stat().st_size < 100_000_000:
        raise RuntimeError(f"Download for {dest.name} looks incomplete ({part.stat().st_size} bytes).")
    part.replace(dest)
    print(f"[models] Finished {dest.name} ({dest.stat().st_size / 1024**3:.2f} GiB)")


def download_comfyui_models(comfy_dir: Path, diffusion_name: str, text_name: str) -> None:
    files = [
        (f"{HF_BASE}/diffusion_models/{diffusion_name}", comfy_dir / "models" / "diffusion_models" / diffusion_name),
        (f"{HF_BASE}/text_encoders/{text_name}", comfy_dir / "models" / "text_encoders" / text_name),
        (f"{HF_BASE}/vae/ae.safetensors", comfy_dir / "models" / "vae" / "ae.safetensors"),
    ]
    for url, dest in files:
        download_file(url, dest)



def system_ram_gb() -> Optional[float]:
    """Best-effort physical RAM detection across supported operating systems."""
    try:
        system = platform.system()
        if system == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys / (1024 ** 3)
        elif system == "Darwin":
            value = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5, check=True)
            return int(value.stdout.strip()) / (1024 ** 3)
        else:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 ** 2)
    except Exception:
        return None
    return None


def ensure_runtime(args: argparse.Namespace) -> None:
    load_env_file()
    git = ensure_git() if not args.skip_comfyui else ""

    if not args.skip_ollama:
        ollama = install_ollama()
        ensure_ollama_running(ollama)
        if not args.skip_ollama_model:
            default_model = os.getenv("OLLAMA_DEFAULT_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
            configured_models = [m.strip() for m in os.getenv("OLLAMA_MODELS_TO_PULL", default_model).split(",") if m.strip()]
            ram_gb = system_ram_gb()
            auto_select = os.getenv("OLLAMA_AUTO_SELECT_MODEL", "true").strip().lower() not in {"0", "false", "no", "off"}
            if auto_select and ram_gb is not None and ram_gb < 24 and default_model == DEFAULT_OLLAMA_MODEL:
                smaller_model = "llama3.2:3b"
                print(f"[setup] Detected {ram_gb:.1f} GB system RAM; selecting {smaller_model} instead of {DEFAULT_OLLAMA_MODEL}.")
                configured_models = [smaller_model if m == DEFAULT_OLLAMA_MODEL else m for m in configured_models]
                default_model = smaller_model
                update_env({"OLLAMA_DEFAULT_MODEL": default_model,
                            "OLLAMA_MODELS_TO_PULL": ",".join(dict.fromkeys(configured_models or [default_model]))})
            if default_model not in configured_models:
                configured_models.insert(0, default_model)
            for model in dict.fromkeys(configured_models):
                pull_ollama_model(model)
            installed_models = ollama_tags()
            if default_model not in installed_models and installed_models:
                default_model = installed_models[0]
                update_env({"OLLAMA_DEFAULT_MODEL": default_model})

    if not args.skip_comfyui:
        comfy_dir, comfy_py, diffusion_name, text_name, low_vram = ensure_comfyui(git)
        if not args.skip_model_download:
            download_comfyui_models(comfy_dir, diffusion_name, text_name)
        comfy_args = "--listen 127.0.0.1 --port 8188" + (" --lowvram" if low_vram else "")
        update_env({
            "COMFYUI_DIR": str(comfy_dir.resolve()).replace("\\", "/"),
            "COMFYUI_PYTHON": str(comfy_py.resolve()).replace("\\", "/"),
            "COMFYUI_ARGS": comfy_args,
            "COMFYUI_ZIMAGE_DIFFUSION_MODEL": diffusion_name,
            "COMFYUI_ZIMAGE_TEXT_ENCODER": text_name,
        })
        if low_vram:
            print("[setup] Low-VRAM mode enabled for ComfyUI.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install dependencies and launch AI Presentation Studio.")
    parser.add_argument("--skip-ollama", action="store_true", help="Use an already-installed/running Ollama; do not install or start it.")
    parser.add_argument("--skip-ollama-model", action="store_true", help="Do not download Ollama models.")
    parser.add_argument("--skip-comfyui", action="store_true", help="Skip ComfyUI installation and model setup.")
    parser.add_argument("--skip-model-download", action="store_true", help="Set up ComfyUI but skip the large Z-Image weight downloads.")
    parser.add_argument("--no-launch", action="store_true", help="Set up dependencies but do not launch the Gradio app.")
    return parser.parse_args()


def main() -> int:
    # Help must be side-effect free; don't create environments just to print usage.
    if "--help" in sys.argv or "-h" in sys.argv:
        parse_args()
        return 0
    # The first invocation can be from the system Python; create/re-enter app venv.
    if os.environ.get("PRESENTATION_STUDIO_IN_VENV") != "1":
        return ensure_app_venv(sys.argv[1:])

    args = parse_args()
    load_env_file()
    try:
        ensure_runtime(args)
    except Exception as exc:
        print(f"\n[setup error] {exc}")
        print("You can rerun the same launcher; completed downloads and setup steps are reused.")
        return 1

    if args.no_launch:
        print("[setup] Environment setup completed. Run start_windows.bat or ./start.sh to launch later.")
        return 0

    print("\n[launch] Starting AI Presentation Studio. The app should open in your default browser.")
    print("[launch] Keep this terminal open while using the app. Press Ctrl+C to stop it.")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        return subprocess.run([sys.executable, str(ROOT / "app.py")], cwd=str(ROOT), env=env).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
