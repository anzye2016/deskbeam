"""Voice transcription: local WSL-based ASR or a remote API.

The local path shells out to a WSL python script that talks to a local
transcription server (127.0.0.1:8082). The online path posts the audio to a
configured OpenAI-style API. init() must be called once at startup with the
server config; transcription runs on a single-worker executor.
"""

import base64
import json
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_cfg = {}
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")

_asr_ready = False
_asr_last_check = 0
_asr_lock = threading.Lock()
_asr_cooldown = 10
WSL_ASR = ""
ASR_URL = ""


def init(cfg):
    """Bind the server config (single source of truth). Call once at startup."""
    global _cfg, _asr_cooldown, WSL_ASR, ASR_URL
    _cfg = cfg
    _asr_cooldown = _int_cfg("asr_cooldown", 10)
    # The local ASR path shells out through wsl.exe — Windows only. On Linux
    # only the online API path is available (docs/DEV-NOTES.md（Linux 移植）).
    WSL_ASR = cfg.get("wsl_asr_script", "") if sys.platform == "win32" else ""
    ASR_URL = cfg.get("asr_health_url", "")


def _int_cfg(key, default=0):
    try:
        return int(_cfg[key])
    except (KeyError, ValueError, TypeError):
        return default


def _wsl(cmd, timeout=120):
    full = ["wsl.exe"] + (cmd if isinstance(cmd, list) else cmd.split())
    try:
        r = subprocess.run(full, capture_output=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode, r.stdout.decode("utf-8", errors="replace").strip(), r.stderr.decode("utf-8", errors="replace").strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def _wav_to_wsl_path(p):
    p = str(p)
    if len(p) >= 2 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:].replace(chr(92), '/')}"
    return p


def _expand_wsl_path(p):
    p = str(p)
    if p.startswith("~"):
        rc, home, _ = _wsl("echo $HOME", timeout=5)
        if rc == 0 and home:
            p = home + p[1:]
    return p


def _ensure_asr():
    global _asr_ready, _asr_last_check
    now = time.time()
    if _asr_ready:
        return True
    if now - _asr_last_check < _asr_cooldown:
        return False
    with _asr_lock:
        if _asr_ready:
            return True
        _asr_last_check = now
    rc, out, _ = _wsl(f"curl -s {ASR_URL}", timeout=5)
    if "ok" in out:
        with _asr_lock:
            _asr_ready = True
        return True
    return False


def transcribe(wav_path):
    api_url = _cfg.get("asr_api_url", "").strip()
    api_key = _cfg.get("asr_api_key", "").strip()
    if api_url and api_key:
        return _transcribe_online(wav_path, api_url, api_key)
    return _transcribe_local(wav_path)


def _transcribe_online(wav_path, url, key):
    wav_data = wav_path.read_bytes()
    b64 = base64.b64encode(wav_data).decode()
    model = _cfg.get("asr_api_model", "").strip() or "mimo-v2.5-asr"
    auth = _cfg.get("asr_api_auth", "").strip()
    if auth == "api-key":
        hdr = ("api-key", key)
    else:
        hdr = ("Authorization", f"Bearer {key}")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": f"data:audio/wav;base64,{b64}"}}]}],
    }).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={
            hdr[0]: hdr[1].encode(),
            "Content-Type": "application/json",
        })
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
    except Exception as e:
        print(f"  ASR error: {e}")
        return ""
    path = (_cfg.get("asr_api_response_path", "") or "choices.0.message.content").split(".")
    if not path or path == [""]:
        return ""
    val = data
    for k in path:
        if not k:
            continue
        try:
            val = val[int(k)] if k.isdigit() or (k[0] == "-" and k[1:].isdigit()) else val.get(k, "")
        except Exception:
            val = ""
    return str(val).strip()


def _transcribe_local(wav_path):
    if not WSL_ASR or sys.platform != "win32":
        return "[ASR not available]"
    if not _ensure_asr():
        return "[ASR not available]"

    wsl_path = _wav_to_wsl_path(wav_path)
    script = _expand_wsl_path(WSL_ASR)
    rc, out, err = _wsl(["python3", script, wsl_path], timeout=60)
    if rc != 0:
        with _asr_lock:
            _asr_ready = False
            _asr_last_check = 0
        return ""

    if err:
        print(f"  WSL stderr: {err[:200]}")

    lines = []
    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in ("处理中", "编码", "音频:", "耗时:", "字幕", "处理音频")):
            continue
        lines.append(line)
    return " ".join(lines).strip()
