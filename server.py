"""DeskBeam — desktop streaming and remote control (Windows / X11 Linux)."""

import asyncio
import base64
import ctypes
import hashlib
import hmac
import io
import json
import os
import queue
import secrets
import socket
import ssl
import struct as _struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import wave
if sys.platform == "win32":
    import ctypes.wintypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import capture
except ImportError:
    capture = None

try:
    import speech
except ImportError:
    speech = None

try:
    from encoder import H264Encoder, has_idr
except ImportError:
    H264Encoder = None
    has_idr = None

try:
    from webrtc_streamer import WebRTCSession
except ImportError:
    WebRTCSession = None

try:
    from rtp_stream import RTPVideoTransport
except ImportError:
    RTPVideoTransport = None

try:
    from gpu_stream import GPUStreamer, FFMPEG_EXISTS as _HAS_FFMPEG, native_screen_size as _native_screen_size
    from gpu_stream import ffmpeg_ready as _ffmpeg_ready, ensure_ffmpeg as _ensure_ffmpeg
except ImportError:
    GPUStreamer = None
    _HAS_FFMPEG = False
    _native_screen_size = None
    _ffmpeg_ready = lambda: False
    _ensure_ffmpeg = lambda url=None, timeout=900: False

try:
    from gpu_stream import _dbg as _gpu_dbg
except ImportError:
    def _gpu_dbg(msg):
        pass

import websockets
from websockets.http11 import Response
from websockets.datastructures import Headers

if sys.platform == "win32":
    from sendinput import (press, combo, type_text, mouse_event,
                           mouse_move_to, key_down, key_up)
else:
    # X11/XTest implementation, same API (docs/DEV-NOTES.md（Linux 移植）)
    from sendinput_linux import (press, combo, type_text, mouse_event,
                                 mouse_move_to, key_down, key_up)

from platform_api import (get_cursor_pos, set_cursor_pos, screen_size,
                          set_process_priority, is_secure_desktop, is_wayland)

# ── Config ──
if getattr(sys, "frozen", False):
    SCRIPT_DIR = Path(sys.executable).parent.resolve()
else:
    SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "config.json"

DEFAULT_CONFIG = {
    "port": 8769,
    "ssl_cert": "cert.pem",
    "ssl_key": "key.pem",
    "web_dir": "web",
    "token": "",
    "lan_access": True,
    "max_fps": 15,
    "max_fps_lan": 60,
    "gop": 10,
    "gop_lan": 1,
    "cq": 26,
    "cq_lan": 18,
    "preset": "p4",
    "preset_lan": "p1",
    "maxrate": "6M",
    "maxrate_lan": "40M",
    "bufsize": "12M",
    "bufsize_lan": "80M",
    "wan_downscale": False,
    "streaming": True,
    "ffmpeg_url": "",
    "wsl_asr_script": "~/scripts/asr.py",
    "asr_health_url": "http://127.0.0.1:8082/healthz",
    "asr_cooldown": 10,
    "asr_api_url": "",
    "asr_api_key": "",
    "asr_api_model": "mimo-v2.5-asr",
    "asr_api_auth": "",
    "asr_api_response_path": "choices.0.message.content",
}

_cfg = {}
try:
    if CONFIG_FILE.is_file():
        _cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
except Exception as _e:
    print(f"WARNING: {CONFIG_FILE} is invalid ({_e}). Using defaults.")
for k, v in DEFAULT_CONFIG.items():
    _cfg.setdefault(k, v)


def _save_config():
    """把内存里的配置原子写回 config.json（临时文件 + os.replace）。格式与手写
    版一致：2 空格缩进、无 BOM、无尾随换行。调用方自带异常处理。"""
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)


def _get_int(key, default=0):
    try:
        return int(_cfg[key])
    except (KeyError, ValueError, TypeError):
        return default


def _pick_int(lan, key, key_lan, default, default_lan=None):
    if lan:
        return max(_get_int(key_lan, default_lan if default_lan is not None else default), 1)
    return max(_get_int(key, default), 1)


def _pick(lan, key, key_lan, default, default_lan=None):
    if lan:
        return _cfg.get(key_lan, default_lan if default_lan is not None else default)
    return _cfg.get(key, default)


HOST = "0.0.0.0"
PORT = _get_int("port", 8769)
if getattr(sys, "frozen", False):
    _bundled = Path(sys._MEIPASS) / "deskbeam_web"
    WEB_DIR = _bundled if _bundled.is_dir() else (SCRIPT_DIR / _cfg["web_dir"]).resolve()
else:
    WEB_DIR = (SCRIPT_DIR / _cfg["web_dir"]).resolve()
SSL_CERT = SCRIPT_DIR / _cfg["ssl_cert"]
SSL_KEY = SCRIPT_DIR / _cfg["ssl_key"]
PID_FILE = SCRIPT_DIR / "server.pid"
LOG_FILE = SCRIPT_DIR / "server.log"
TEMP_DIR = Path(tempfile.gettempdir()) / "deskbeam"
try:
    TEMP_DIR.mkdir(exist_ok=True)
except Exception:
    TEMP_DIR = SCRIPT_DIR / "temp"
    TEMP_DIR.mkdir(exist_ok=True)
AUTH_TOKEN = _cfg.get("token", "").strip()
COOKIE_NAME = "deskbeam_session"
TOTP_SECRET = _cfg.get("totp_secret", "").strip()
# 拒绝来自局域网的直连（默认关闭该限制）。只认显式的 false/0/no/off/空。
LAN_ACCESS = str(_cfg.get("lan_access", True)).strip().lower() not in ("false", "0", "no", "off", "")
MAX_FPS = max(_get_int("max_fps", 15), 1)
GOP_SIZE = max(_get_int("gop", 10), 1)
AUDIT_LOG = SCRIPT_DIR / "audit.log"

executor = ThreadPoolExecutor(max_workers=4)
# Hold strong references to fire-and-forget asyncio tasks so the GC cannot
# cancel them mid-flight (e.g. ASR transcription after voice_end).
_BACKGROUND_TASKS = set()
# 活着的 WS 连接，元素为 (websocket, 对端 IP)。用于关闭 LAN 访问时立刻踢掉
# 已经建立的局域网会话（守卫只拦新握手，拦不住已连上的）。
_CONNS = set()


def _is_lan(ip):
    # Tailscale（CGNAT 100.64.0.0/10）刻意不在此列：它跨公网，按 WAN 配置
    # 走低码率/大 GOP 参数，避免上行被拉满。
    return ip.startswith(("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                          "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                          "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                          "172.30.", "172.31."))


def _lan_peer_blocked(connection):
    """True when this connection itself comes from the LAN and LAN access is off.
    判据是 socket peer 而非 _real_ip()：隧道进来的 WAN 客户端 peer 是
    127.0.0.1、Tailscale 是 100.64/10（_is_lan 已排除），两者都要放行；
    直连的局域网客户端也无法靠伪造 X-Real-IP 绕过。"""
    if LAN_ACCESS:
        return False
    peer = connection.remote_address[0] if connection.remote_address else ""
    return bool(peer) and _is_lan(peer)


def _real_ip(headers, fallback):
    """Client IP for rate-limiting/audit/LAN detection.

    WAN clients arrive via a reverse proxy (SSH tunnel with nginx, or Tailscale
    Serve), so the socket peer is always 127.0.0.1. Only then is a forwarding
    header trusted: nginx sets X-Real-IP, Tailscale Serve sets
    X-Forwarded-For. Direct connections keep their socket peer address, so a
    spoofed header cannot bypass the login rate limit or fake LAN status
    (the LAN-access gate uses the socket peer, not this). Without this, every
    Tailscale client would be logged as 127.0.0.1 and share one rate-limit
    bucket."""
    if fallback.startswith(("127.0.0.1", "::1", "::ffff:127.0.0.1")):
        ip = (headers.get("X-Real-IP", "") or "").strip()
        if not ip:
            xff = headers.get("X-Forwarded-For", "") or ""
            ip = xff.split(",")[0].strip()
        if ip:
            return ip
    return fallback


# ── Auth helpers ──
_LOGIN_FAILS = {}
MAX_LOGIN_FAILS = 5
LOGIN_BLOCK_SEC = 86400
_SESSION_MAX_AGE = 86400
# sid -> expiry timestamp. The session id is a random value independent of the
# login token, so leaking the token does not forge a cookie (token is only a
# login credential; TOTP still protects the login flow).
_SESSIONS = {}
_LOGIN_HTML = ""
try:
    p = WEB_DIR / "login.html"
    if p.is_file():
        _LOGIN_HTML = p.read_text(encoding="utf-8")
except Exception:
    pass
if not _LOGIN_HTML:
    _LOGIN_HTML = '<!DOCTYPE html><meta charset=utf-8><title>Login</title><form id=f><input type=password id=t placeholder=Token><button>Login</button><p id=e></p></form><script>f.onsubmit=async e=>{e.preventDefault();let r=await fetch("/login",{headers:{"X-Auth-Token":t.value}});r.redirected&&r.url.endsWith("/")?location.href="/":e.textContent=r.status==429?"Blocked 24h":"Invalid token"}</script>'


def _audit_write(line):
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _audit(event, ip=""):
    """Append to the audit log. File I/O runs on the executor so the event
    loop never blocks on disk (or antivirus scanning the log file)."""
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {event} {ip}\n"
    try:
        executor.submit(_audit_write, line)
    except Exception:
        pass


_LAN_BLOCK_LOGGED = {}


def _audit_lan_block(ip):
    """同一个 IP 每 60s 最多记一条：被挡的客户端（前端的自动重连、被冻住的
    旧标签页）会以秒级频率重试，逐条写会把 audit.log 撑爆。"""
    now = time.time()
    if now - _LAN_BLOCK_LOGGED.get(ip, 0) >= 60:
        _LAN_BLOCK_LOGGED[ip] = now
        _audit("LAN BLOCKED", ip)


def _get_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


LAN_IP = _get_lan_ip()


def _parse_cookies(headers):
    cookies = {}
    cookie_header = headers.get("Cookie", "")
    if not cookie_header:
        return cookies
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def _check_auth(request):
    if not AUTH_TOKEN:
        return True
    cookies = _parse_cookies(request.headers)
    sid = cookies.get(COOKIE_NAME)
    if not sid:
        return False
    exp = _SESSIONS.get(sid)
    if exp is None:
        return False
    if time.time() > exp:
        _SESSIONS.pop(sid, None)
        return False
    return True


def _login_allowed(ip):
    now = time.time()
    if ip in _LOGIN_FAILS:
        count, first, blocked = _LOGIN_FAILS[ip]
        if blocked and now < blocked:
            return False
        if now - first > LOGIN_BLOCK_SEC:
            del _LOGIN_FAILS[ip]
    if len(_LOGIN_FAILS) > 1000:
        _LOGIN_FAILS.clear()
    return True


def _login_fail(ip):
    now = time.time()
    if ip in _LOGIN_FAILS:
        count, first, blocked = _LOGIN_FAILS[ip]
        if blocked and now < blocked:
            return
        count += 1
    else:
        count, first = 1, now
    blocked = now + LOGIN_BLOCK_SEC if count >= MAX_LOGIN_FAILS else 0
    _LOGIN_FAILS[ip] = (count, first, blocked)


def _login_ok(ip):
    _LOGIN_FAILS.pop(ip, None)


def _pem_fingerprint(pem_path):
    """从 PEM 证书文件计算 SHA-256 指纹（hex）。用于前端 MITM 校验。"""
    try:
        with open(pem_path, "r", encoding="utf-8") as f:
            text = f.read()
        b64 = ""
        in_cert = False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("-----BEGIN CERTIFICATE-----"):
                in_cert = True
                continue
            if line.startswith("-----END CERTIFICATE-----"):
                break
            if in_cert:
                b64 += line
        der = base64.b64decode(b64)
        return hashlib.sha256(der).hexdigest()
    except Exception:
        return ""


_CERT_FINGERPRINT = ""


# ── TOTP (RFC 6238) two-factor auth ─────────────────────────────────────────
# Pure Python, no external deps. Enabled only when config "totp_secret" is set
# (base32 secret, e.g. the kind you scan into Google/Microsoft Authenticator).


def _totp_verify(secret_b32, code, window=1):
    """Verify a 6-digit TOTP code against a base32 secret (RFC 6238, HMAC-SHA1).
    Allows ±`window` time-steps of clock drift."""
    try:
        key = base64.b32decode(secret_b32.replace(" ", "").upper())
    except Exception:
        return False
    if not code or not code.isdigit() or len(code) != 6:
        return False
    n = int(code)
    t0 = int(time.time()) // 30
    for offset in range(-window, window + 1):
        counter = t0 + offset
        msg = _struct.pack(">Q", counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        pos = digest[-1] & 0x0F
        value = (_struct.unpack(">I", digest[pos:pos + 4])[0] & 0x7FFFFFFF) % 1000000
        if value == n:
            return True
    return False


# ── Key / mouse mapping ──
_KEY_MAP = {
    "enter": (press, "enter"),
    "esc": (press, "esc"),
    "ctrl_c": (combo, "ctrl_c"),
    "ctrl_v": (combo, "ctrl_v"),
    "backspace": (press, "backspace"),
    "ctrl_j": (combo, "ctrl_j"),
    "shift_enter": (combo, "shift_enter"),
    "tab": (press, "tab"),
    "alt_tab": (combo, "alt_tab"),
    "win": (press, "win"),
    "f5": (press, "f5"),
    "f12": (press, "f12"),
    "ctrl_s": (combo, "ctrl_s"),
    "ctrl_z": (combo, "ctrl_z"),
    "ctrl_x": (combo, "ctrl_x"),
    "ctrl_a": (combo, "ctrl_a"),
    "ctrl_f5": (combo, "ctrl_f5"),
}


def do_combo(name):
    entry = _KEY_MAP.get(name)
    if entry:
        fn, arg = entry
        try:
            fn(arg)
        except Exception:
            traceback.print_exc()


def _mouse_flags(*flags):
    """Send a sequence of MOUSEEVENTF_* flags (down+up pairs for clicks)."""
    for flag in flags:
        mouse_event(flag)


def do_mouse(cmd, dx=0, dy=0):
    global _GVX, _GVY
    if cmd == "move":
        _GVX += dx
        _GVY += dy
        if _GYRO_ON:
            set_cursor_pos(int(_GVX), int(_GVY))
        else:
            mouse_event(0x0001, dx, dy)
        return
    if cmd == "move_to":
        if _GYRO_ON:
            _GVX, _GVY = float(dx), float(dy)
        mouse_move_to(dx, dy)
        return
    if cmd == "scroll":
        mouse_event(0x0800, data=120 if dy > 0 else -120)


def _mouse_accumulate(dx, dy):
    """Accumulate a move delta; flushed on the mouse tick. Never blocks."""
    if dx == 0 and dy == 0:
        return
    with _MOVE_LOCK:
        _MOVE_ACC[0] += dx
        _MOVE_ACC[1] += dy


def _mouse_flush():
    """Pop accumulated deltas and apply them. Call on the mouse tick only."""
    with _MOVE_LOCK:
        dx, dy = _MOVE_ACC[0], _MOVE_ACC[1]
        _MOVE_ACC[0] = _MOVE_ACC[1] = 0.0
    if dx or dy:
        do_mouse("move", int(dx), int(dy))


async def _mouse_flush_task():
    while True:
        await asyncio.sleep(0.008)
        try:
            _mouse_flush()
        except Exception:
            traceback.print_exc()


# ── Startup helpers ──
def _write_pid():
    try:
        PID_FILE.write_text(str(os.getpid()))
    except Exception:
        pass


def _unlink_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _kill_old_instances():
    try:
        _my_pid = os.getpid()
        _script_dir = str(SCRIPT_DIR).replace("\\", "\\\\")
        # 只杀本目录的 DeskBeam 实例（按 exe 路径匹配），避免与别处同名
        # DeskBeam.exe 误杀（例如 DeskBeam 目录）。exe 场景下命令行里含
        # exe 完整路径，pythonw 场景下含 server.py 路径，两者都覆盖。
        # 端口兜底仅杀 DeskBeam/python 进程，不误伤碰巧占用端口的其它服务。
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-CimInstance Win32_Process | "
             f"Where-Object {{ $_.CommandLine -like '*{_script_dir}*' -and "
             f"($_.Name -like 'DeskBeam*' -or $_.Name -in @('python.exe','pythonw.exe')) -and "
             f"$_.ProcessId -ne {_my_pid} }} | "
             f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}; "
             f"$c=Get-NetTCPConnection -LocalPort {PORT} -ErrorAction SilentlyContinue; "
             f"if($c){{$c|Where-Object{{$_.OwningProcess -ne {_my_pid}}}|ForEach-Object{{"
             f"$pp=Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue;"
             f"if($pp -and ($pp.ProcessName -like 'DeskBeam*' -or $pp.ProcessName -in @('python','pythonw')))"
             f"{{Stop-Process -Id $_.OwningProcess -Force}}}}}}"],
            capture_output=True, creationflags=0x08000000, timeout=15,
        )
    except Exception:
        pass


def _truncate_log(max_bytes=256 * 1024):
    try:
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > max_bytes:
            lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
            LOG_FILE.write_text("\n".join(lines[-len(lines) // 2:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _redirect_log():
    try:
        log_fh = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log_fh
        return log_fh
    except Exception:
        return None


# ── Gyro virtual cursor ──
# In gyro mode the virtual position accumulates every delta even past screen
# edges; the real cursor is SetCursorPos-clamped to the edge. Returning the
# phone to its origin brings the accumulated offset to zero, so the cursor
# returns to its start instead of losing the off-screen movement.
_GYRO_ON = False
_gyro_owner = None  # the cmd connection that last enabled gyro mode
_GVX = 0.0
_GVY = 0.0

# Mouse-move accumulator: gyro/touchpad send up to 60-120 Hz moves; rather than
# awaiting each on the command loop (which stalls all other keys), deltas are
# accumulated here and flushed on a fixed tick by _mouse_flush_task.
_MOVE_ACC = [0.0, 0.0]
_MOVE_LOCK = threading.Lock()

# H.264 levels as (level_idc, MaxFS MBs/frame, MaxMBPS MBs/s), ascending.
# Verified against the levels ffmpeg itself picks at 360p/720p/1080p/1440p/4K.
_AVC_LEVELS = (
    (0x1E, 1620, 40500),       # 3.0
    (0x1F, 3600, 108000),      # 3.1
    (0x20, 5120, 216000),      # 3.2
    (0x28, 8192, 245760),      # 4.0
    (0x2A, 8704, 522240),      # 4.2
    (0x32, 22080, 589824),     # 5.0
    (0x33, 36864, 983040),     # 5.1
    (0x34, 36864, 2073600),    # 5.2
    (0x3C, 139264, 4177920),   # 6.0
    (0x3D, 139264, 8355840),   # 6.1
    (0x3E, 139264, 16711680),  # 6.2
)


def _avc1_codec(width, height, fps, enc=""):
    """WebCodecs codec string matching the bitstream we actually send.

    This used to be hardcoded "avc1.42001F" = Baseline 3.1: wrong profile
    (the ffmpeg pipelines sign Main) and a level far below what the frame
    needs (Level 3.1 caps at 3600 macroblocks/frame, 2560x1440 is 14400).
    Lenient decoders ignore the field; strict ones may reject the config
    outright, and the viewer has no fallback - it just goes black. Derive
    profile+level instead, with the constraint byte the encoders actually
    write (0x40 for Main, 0xC0 for Baseline)."""
    try:
        w, h, f = int(width), int(height), max(1, int(fps or 30))
    except (TypeError, ValueError):
        return "avc1.4D4032"
    if w <= 0 or h <= 0:
        return "avc1.4D4032"
    mbs = ((w + 15) // 16) * ((h + 15) // 16)
    mbps = mbs * f
    level = next((lvl for lvl, fs, ps in _AVC_LEVELS if mbs <= fs and mbps <= ps),
                 _AVC_LEVELS[-1][0])
    profile, constraint = (0x42, 0xC0) if enc == "libx264" else (0x4D, 0x40)
    return "avc1.%02X%02X%02X" % (profile, constraint, level)


_GPU_READY = _HAS_FFMPEG and GPUStreamer is not None
_STREAMING = _cfg.get("streaming", True) and (_GPU_READY or (capture is not None and capture.HAS_DXCAM and capture.HAS_AV))
_GPU_START_RETRIES = 2
_GPU_START_RETRY_DELAY = 1.5
# In-place respawns after a running streamer dies (DXGI access loss). Well
# under this count covers lock screen / UAC / driver state churn; hitting it
# hands the connection back to the client's frame-stall watchdog.
_GPU_DEATH_RETRIES = 10

if _native_screen_size:
    _NATIVE_W, _NATIVE_H = _native_screen_size()
else:
    _NATIVE_W, _NATIVE_H = 1920, 1080

_SOFT_WIDTH = max(_get_int("soft_width", 1920), 320)
_SOFT_HEIGHT = max(_get_int("soft_height", 1080), 240)
_SOFT_FPS = max(_get_int("soft_fps", 15), 5)
_WAN_W = _get_int("wan_width", 0)
_WAN_H = _get_int("wan_height", 0)


# ── HTTP handler ──
async def http_handler(connection, request):
    path = request.path

    # lan_access=false：在服务任何内容之前先挡住局域网直连（含 /login、/cert
    # 与 WS 升级）。静态文件、登录页、串流对 LAN 客户端一律不可达。
    if _lan_peer_blocked(connection):
        _audit_lan_block(connection.remote_address[0])
        return Response(403, "Forbidden", Headers({}), b"LAN access disabled")

    if path.split("?", 1)[0] == "/lan_access":
        # 设置卡片里的运行期开关：GET 读状态，GET ?on=1|0 改状态。改状态会原子
        # 写回 config.json（重启后保持），并立刻断开已连着的局域网会话。
        if not _check_auth(request):
            return Response(403, "Forbidden", Headers({}), b"Forbidden")
        global LAN_ACCESS
        args = {}
        if "?" in path:
            for part in path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    args[k] = v
        words = []
        if "on" in args:
            want = args["on"].strip().lower() in ("1", "true", "on", "yes")
            ip = _real_ip(request.headers, connection.remote_address[0] if connection.remote_address else "")
            LAN_ACCESS = want
            _cfg["lan_access"] = want
            saved = True
            try:
                await asyncio.get_running_loop().run_in_executor(executor, _save_config)
            except Exception:
                traceback.print_exc()
                saved = False
            _audit("LAN ACCESS " + ("on" if want else "off"), ip)
            if not want:
                await _close_lan_conns()
            words = ["on" if want else "off"] + ([] if saved else ["unsaved"])
        else:
            words = ["on" if LAN_ACCESS else "off"]
        return Response(200, "OK", Headers({
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "no-store",
        }), ":".join(words).encode("utf-8"))

    if path == "/fingerprint":
        # 返回自身证书指纹（SHA-256 hex）。前端登录后记录，每次访问校验；
        # MITM 伪服务器返回它自己的指纹，与记录的指纹比对即可识别劫持。
        return Response(200, "OK", Headers({"Content-Type": "text/plain; charset=utf-8"}), _CERT_FINGERPRINT.encode("utf-8"))

    if path == "/cert":
        # 下载自身证书供手机等设备安装为受信 CA（application/x-x509-ca-cert
        # 让 Android 直接弹出证书安装），免去每次访问的证书警告。
        if not SSL_CERT.is_file():
            return Response(404, "Not Found", Headers({}), b"Not Found")
        return Response(200, "OK", Headers({
            "Content-Type": "application/x-x509-ca-cert",
            "Content-Disposition": 'attachment; filename="cert.crt"',
            "Cache-Control": "no-store",
        }), SSL_CERT.read_bytes())

    if path == "/ws":
        if not _check_auth(request):
            return Response(403, "Forbidden", Headers({}), b"Forbidden")
        return None

    if path == "/ws_cmd":
        if not _check_auth(request):
            return Response(403, "Forbidden", Headers({}), b"Forbidden")
        connection.is_cmd = True
        return None

    if path.startswith("/login"):
        ip = _real_ip(request.headers, connection.remote_address[0] if connection.remote_address else "0.0.0.0")
        token_param = request.headers.get("X-Auth-Token", "")
        totp_code = request.headers.get("X-Totp-Code", "").strip()
        if token_param:
            if not _login_allowed(ip):
                return Response(429, "Too Many Requests", Headers({"Content-Type": "text/html; charset=utf-8"}), b"<h1>Blocked for 24h</h1>")
            if not hmac.compare_digest(token_param, AUTH_TOKEN):
                _login_fail(ip)
                error = _LOGIN_HTML.replace("</body>", '<p style="color:#E61919;text-align:center">Invalid token</p></body>')
                return Response(200, "OK", Headers({"Content-Type": "text/html; charset=utf-8"}), error.encode("utf-8"))
            # Token OK. If TOTP is enabled, require the 6-digit code too.
            if TOTP_SECRET:
                if not totp_code:
                    _audit("LOGIN TOTP NEEDED", ip)
                    return Response(426, "Upgrade Required", Headers({"Content-Type": "text/html; charset=utf-8"}), b"totp_required")
                if not _totp_verify(TOTP_SECRET, totp_code):
                    _login_fail(ip)
                    _audit("LOGIN TOTP FAIL", ip)
                    error = _LOGIN_HTML.replace("</body>", '<p style="color:#E61919;text-align:center">Invalid code</p></body>')
                    return Response(200, "OK", Headers({"Content-Type": "text/html; charset=utf-8"}), error.encode("utf-8"))
            _login_ok(ip)
            sid = secrets.token_urlsafe(32)
            now = time.time()
            _SESSIONS[sid] = now + _SESSION_MAX_AGE
            for s, e in list(_SESSIONS.items()):
                if e <= now:
                    del _SESSIONS[s]
            _audit("LOGIN OK", ip)
            cookie = f"{COOKIE_NAME}={sid}; Path=/; Max-Age={_SESSION_MAX_AGE}; HttpOnly; SameSite=Strict"
            return Response(302, "Found", Headers({"Location": "/", "Set-Cookie": cookie}), b"")
        return Response(200, "OK", Headers({"Content-Type": "text/html; charset=utf-8"}), _LOGIN_HTML.replace("__TOTP__", "1" if TOTP_SECRET else "0").encode("utf-8"))

    if path == "/logout":
        ip = _real_ip(request.headers, connection.remote_address[0] if connection.remote_address else "0.0.0.0")
        _audit("LOGOUT", ip)
        _SESSIONS.pop(_parse_cookies(request.headers).get(COOKIE_NAME, ""), None)
        cookie = f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
        return Response(302, "Found", Headers({"Location": "/login", "Set-Cookie": cookie}), b"")

    if path == "/shutdown":
        if not _check_auth(request):
            return Response(403, "Forbidden", Headers({}), b"Forbidden")
        _audit("SHUTDOWN", _real_ip(request.headers, connection.remote_address[0] if connection.remote_address else ""))
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        _server.close()
        return Response(200, "OK", Headers({"Content-Type": "text/plain"}), b"Server shutting down...")

    if AUTH_TOKEN and not _check_auth(request):
        return Response(302, "Found", Headers({"Location": "/login"}), b"")

    if path == "/" or path == "":
        path = "/index.html"
    # Path traversal guard: relative_to() rejects any real "../" escape.
    # URL-encoded forms (..%2f, %2e%2e) are NOT a bypass because websockets
    # does not URL-decode request.path (verified in its docs), so "%2f" is
    # treated as a literal filename character, not a path separator.
    file_path = (WEB_DIR / path.lstrip("/")).resolve()
    if file_path.is_file():
        try:
            file_path.relative_to(WEB_DIR.resolve())
        except ValueError:
            return Response(404, "Not Found", Headers({}), b"Not Found")
        suffix_map = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".css": "text/css",
            ".jpg": "image/jpeg",
            ".png": "image/png",
        }
        content_type = suffix_map.get(file_path.suffix, "application/octet-stream")
        body = file_path.read_bytes()
        headers = Headers({
            "Content-Type": content_type,
            "Cache-Control": "no-cache",
        })
        return Response(200, "OK", headers, body)
    return Response(404, "Not Found", Headers({}), b"Not Found")


# ── WebSocket handlers ──
def _frame_packet(is_idr, seq, data):
    """Wrap one encoded frame as: 1 byte IDR flag + 4 byte monotonic frame
    sequence (big-endian) + H.264 data. The client uses the sequence number
    with its own local clock to measure end-to-end latency accumulation
    (comparing two machines' clocks directly would drift over time)."""
    return (b"\x01" if is_idr else b"\x00") + (seq & 0xFFFFFFFF).to_bytes(4, "big") + data


# Simple mouse commands from the frontend -> action. Most map to a fixed
# MOUSEEVENTF_* flag sequence; scroll entries carry the direction in dy.
_MOUSE_CMDS = {
    "mouse_click": lambda: _mouse_flags(0x0002, 0x0004),
    "mouse_double_click": lambda: _mouse_flags(0x0002, 0x0004, 0x0002, 0x0004),
    "mouse_down": lambda: _mouse_flags(0x0002),
    "mouse_up": lambda: _mouse_flags(0x0004),
    "mouse_right": lambda: _mouse_flags(0x0008, 0x0010),
    "mouse_right_down": lambda: _mouse_flags(0x0008),
    "mouse_right_up": lambda: _mouse_flags(0x0010),
    "mouse_middle": lambda: _mouse_flags(0x0020, 0x0040),
    "mouse_middle_down": lambda: _mouse_flags(0x0020),
    "mouse_middle_up": lambda: _mouse_flags(0x0040),
    "scroll_up": lambda: do_mouse("scroll", 0, 1),
    "scroll_down": lambda: do_mouse("scroll", 0, -1),
}


async def _exec_cmd(msg):
    cmd = msg.get("type", "")
    try:
        if cmd == "type_text":
            text = msg.get("text", "")[:2000]
            if text:
                print(f"  type: {text}")
                await asyncio.get_running_loop().run_in_executor(executor, type_text, text)
        elif cmd in _KEY_MAP:
            do_combo(cmd)
        elif cmd == "key_press":
            k = msg.get("key", "")
            if k:
                press(k)
        elif cmd == "key_down":
            k = msg.get("key", "")
            if k:
                key_down(k)
        elif cmd == "key_up":
            k = msg.get("key", "")
            if k:
                key_up(k)
        elif cmd == "set_gyro":
            global _GYRO_ON, _GVX, _GVY, _gyro_owner
            on = bool(msg.get("on", False))
            if on:
                gx, gy = get_cursor_pos()
                _GVX, _GVY = float(gx), float(gy)
            _GYRO_ON = on
            _gyro_owner = websocket if on else None
        elif cmd == "gyro_calib":
            w, h = screen_size()
            cx, cy = w // 2, h // 2
            if _GYRO_ON:
                _GVX, _GVY = float(cx), float(cy)
            set_cursor_pos(cx, cy)
        elif cmd == "mouse_move":
            dx, dy = msg.get("dx", 0), msg.get("dy", 0)
            _mouse_accumulate(dx, dy)
        elif cmd == "mouse_click_at":
            x, y = msg.get("x", 0), msg.get("y", 0)
            do_mouse("move_to", x, y)
            _mouse_flags(0x0002, 0x0004)
        elif cmd == "mouse_move_to":
            x, y = msg.get("x", 0), msg.get("y", 0)
            do_mouse("move_to", x, y)
        elif cmd in _MOUSE_CMDS:
            _MOUSE_CMDS[cmd]()
    except Exception:
        traceback.print_exc()



async def _close_lan_conns():
    """踢掉已建立的局域网连接。守卫只拦新握手，已连上的视频/命令通道不受
    影响——关闭 LAN 访问时若不断开，手机上的旧页面会继续串流到它自己重连。"""
    victims = [ws for ws, ip in list(_CONNS) if ip and _is_lan(ip)]
    for ws in victims:
        try:
            await ws.close(1008, "LAN access disabled")
        except Exception:
            pass
    if victims:
        print(f"  lan_access off: closed {len(victims)} LAN connection(s)")


async def ws_dispatch(websocket):
    peer = websocket.remote_address[0] if websocket.remote_address else ""
    entry = (websocket, peer)
    _CONNS.add(entry)
    try:
        if getattr(websocket, "is_cmd", False):
            await ws_cmd_handler(websocket)
        else:
            await ws_handler(websocket)
    finally:
        _CONNS.discard(entry)


def _set_nodelay(websocket):
    """Disable Nagle on a connection. websockets' asyncio implementation leaves
    TCP_NODELAY at the OS default (Nagle on) - only its sync implementation
    sets it (verified default=0 against websockets 16.1.1). Large video writes
    are unaffected either way, but small command frames (mouse/key/ping) can
    otherwise sit until an ACK arrives, which is felt as laggy input on
    high-RTT links."""
    try:
        sock = websocket.transport.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except Exception:
        pass


async def ws_cmd_handler(websocket):
    """Command channel: control commands + voice. Separated from video so
    control messages are never queued behind video frames."""
    _set_nodelay(websocket)
    ip = _real_ip(websocket.request.headers, websocket.remote_address[0] if websocket.remote_address else "")
    _audit("WS CMD CONNECT", ip)
    esp_cfg = {
        "relayUrl": _cfg.get("esp_relay_url", ""),
        "token": _cfg.get("esp_token", ""),
        "device": _cfg.get("esp_device", ""),
    }
    lan = _is_lan(ip)
    # 经 SSH 反向隧道访问时 socket peer 是 127.0.0.1 且带 nginx 的 X-Real-IP,
    # 此时只有 TCP 能穿过隧道,客户端应走 TCP 而非默认的 UDP(RTP)。
    tunneled = bool(websocket.request.headers.get("X-Real-IP", "").strip()) and \
        (websocket.remote_address[0] if websocket.remote_address else "").startswith(("127.0.0.1", "::1"))
    await websocket.send(json.dumps({
        "type": "hello",
        "streaming": _STREAMING,
        "iceServers": _cfg.get("ice_servers", []),
        "espConfig": esp_cfg,
        "lan": lan,
        "tunnel": tunneled,
    }))
    loop = asyncio.get_running_loop()
    voice_pcm = None

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                if len(message) > 44:
                    if voice_pcm is None:
                        voice_pcm = io.BytesIO()
                    voice_pcm.write(message[44:])
                continue

            if isinstance(message, str):
                try:
                    msg = json.loads(message)
                except json.JSONDecodeError:
                    continue

                if msg.get("type") == "voice_end":
                    if voice_pcm:
                        pcm = voice_pcm.getvalue()
                        voice_pcm = None
                        if pcm:
                            # Unique file per recording (concurrent sessions no
                            # longer clobber each other; exe dir stays read-only
                            # safe). Removed after successful transcription.
                            wav_path = None
                            try:
                                fd, name = tempfile.mkstemp(suffix=".wav", dir=TEMP_DIR)
                                wav_path = Path(name)
                                with os.fdopen(fd, "wb") as fh:
                                    with wave.open(fh, "wb") as w:
                                        w.setnchannels(1)
                                        w.setsampwidth(2)
                                        w.setframerate(16000)
                                        w.writeframes(pcm)
                            except Exception:
                                wav_path = None
                            if wav_path is None:
                                continue
                            async def _transcribe_full(path):
                                done = False
                                try:
                                    t = await loop.run_in_executor(speech.EXECUTOR, speech.transcribe, path)
                                    if t:
                                        await loop.run_in_executor(executor, type_text, t[:2000])
                                        done = True
                                    else:
                                        print(f"  ASR failed, audio saved: {path}")
                                finally:
                                    if done:
                                        try:
                                            path.unlink(missing_ok=True)
                                        except Exception:
                                            pass
                            _task = asyncio.create_task(_transcribe_full(wav_path))
                            _BACKGROUND_TASKS.add(_task)
                            _task.add_done_callback(_BACKGROUND_TASKS.discard)
                    continue
                if msg.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong", "t": msg.get("t")}))
                    continue
                await _exec_cmd(msg)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _audit("WS CMD DISCONNECT", ip)
        print(f"WS cmd disconnected: {websocket.remote_address}")
        # Only the connection that owns gyro mode resets it; a second
        # client disconnecting must not kill the active gyro session.
        global _GYRO_ON, _gyro_owner
        if _gyro_owner is websocket:
            _GYRO_ON = False
            _gyro_owner = None


class _FrameDropper:
    """Reduces send bandwidth by dropping frames - never restarts the encoder.

    A frame is only dropped when nothing sent later depends on it:
      * gop == 1 -> every frame is an IDR (independent) -> drop by ratio.
      * gop  > 1 -> send the first N frames of each GOP and drop the tail;
                    the next GOP opens with a fresh IDR, so the decode chain
                    never breaks and no artifacts appear.

    Staleness guard: dropping the tail means the picture freezes on the last
    sent frame until the next IDR.  A long GOP would make that freeze far
    worse than the bandwidth it saves, so the dropper keeps enough frames to
    bound the freeze to _STALE_BUDGET seconds.
    """

    _KEEP = (1.0, 0.65, 0.35)
    _STALE_BUDGET = 0.5

    def __init__(self, gop, fps):
        self.gop = max(1, int(gop))
        self.fps = max(1, int(fps))
        self.pos = 0          # frames since the last IDR (0 = that IDR)
        self.cnt = 0
        self.seen_idr = False

    def keep(self, is_idr, tier):
        self.cnt += 1
        if is_idr:
            self.pos = 0
            self.seen_idr = True
        else:
            self.pos += 1
        if tier <= 0 or not self.seen_idr:
            return True
        if self.gop <= 1:
            # Every frame stands alone: drop a fixed fraction of them.
            if tier == 1:
                return self.cnt % 3 != 2
            return self.cnt % 3 == 0
        if is_idr:
            return True
        k = int(self.gop * self._KEEP[tier] + 0.5)
        k = max(k, self.gop - int(self._STALE_BUDGET * self.fps))
        return self.pos <= max(1, min(self.gop, k))


def _scale_rate(s, factor):
    """Scale a rate string like '40M' by a numeric factor, rounding to int."""
    s = str(s).strip().upper()
    if s.endswith('M'):
        return str(max(1, int(int(s[:-1]) * factor))) + "M"
    if s.endswith('K'):
        return str(max(1, int(int(s[:-1]) * factor))) + "K"
    return str(max(1, int(int(s) * factor)))


class _VideoSession:
    """Per-connection video-channel state shared by the sender pipelines."""

    def __init__(self, websocket, lan, fps, gop, cq, preset, maxrate, bufsize, ice_servers):
        self.ws = websocket
        self.loop = asyncio.get_running_loop()
        self.lan = lan
        self.fps = fps
        self.gop = gop
        self.cq = cq
        self.preset = preset
        self.maxrate = maxrate
        self.bufsize = bufsize
        self.ice_servers = ice_servers
        self.running = True
        self.streaming = False
        self.webrtc = None
        self.rtp = None
        self.rtp_pending = False
        self.rtp_ref = None
        # 非 RTP 路径当前占用的 GPUStreamer,由 _gpu_sender 维护。set_mode 切
        # RTP 时先等它让位(见 ws_handler),避免两套 ffmpeg 并抢 NVENC/DXGI。
        self.tcp_streamer = None
        # RTP: 对端 PLI/FIR 请求关键帧的事件 + 重建编码器的串行锁(码率与关键帧
        # 两条路径都可能重建编码器,必须互斥,否则会并发起两个 ffmpeg)。
        self.rtp_keyframe = None
        self.rtp_lock = asyncio.Lock()
        self.nw = 0
        self.nh = 0
        self.frame_seq = 0
        # Bandwidth adaptation: tier 0 = full speed, 1 = congested, 2 = severe.
        # The sender loops apply the tier as frame dropping (_FrameDropper);
        # the encoder is never restarted for bandwidth.
        self._bitrate_tier = 0
        # Client asks for a fresh keyframe (decode backlog under long GOP).
        self._keyframe_request = asyncio.Event()
        self._base_cq = cq
        self._base_maxrate = maxrate
        self._base_bufsize = bufsize

    def effective_params(self):
        """Encoder parameters. Bandwidth adaptation happens at the send side
        by dropping frames (no encoder restart), so the encoder always runs at
        the configured base quality."""
        return self._base_cq, self._base_maxrate, self._base_bufsize

    def rtp_params(self):
        """Encoder parameters for the RTP/UDP path. The RTP track ships every
        access unit intact (no frame dropping — a dropped P-frame breaks the
        decode chain), so congestion is handled by rebuilding the encoder at a
        lower rate/cq instead."""
        t = self._bitrate_tier
        if t <= 0:
            return self._base_cq, self._base_maxrate, self._base_bufsize
        f = 0.6 if t == 1 else 0.3
        return (min(self._base_cq + (3 if t == 1 else 6), 51),
                _scale_rate(self._base_maxrate, f),
                _scale_rate(self._base_bufsize, f))

    async def send_config(self, width, height, raw_w, raw_h, fps, enc=""):
        await self.ws.send(json.dumps({
            "type": "screen_config",
            "codec": _avc1_codec(width, height, fps, enc),
            "width": width,
            "height": height,
            "raw_width": raw_w,
            "raw_height": raw_h,
            "fps": fps,
            "enc": enc,
        }))


def _soft_clamp(fps, gop):
    """Clamp fps/gop for CPU-bound software pipelines (PyAV soft encode,
    WebRTC software track). Identity when a hardware encoder is available.
    The ffmpeg GPU pipeline is never clamped here — capture.IS_SOFT only
    reflects PyAV's capability, not ffmpeg's, and GPUStreamer downscales
    itself when it ends up on libx264."""
    if capture is not None and capture.IS_SOFT:
        fps = min(fps, _SOFT_FPS)
        gop = min(gop, fps)
    return fps, gop


async def _webrtc_timeout(sess):
    await asyncio.sleep(30)
    if sess.webrtc:
        state = sess.webrtc._pc.iceConnectionState
        if state not in ("connected", "completed"):
            await sess.webrtc.close()
            sess.webrtc = None
            print(f"  WebRTC timeout (state={state})")


async def _rtp_start_streamer(sess):
    """Create a GPUStreamer sized for the RTP/UDP path. Returns it, or None
    when capture is unavailable."""
    nw, nh = (_native_screen_size() if _native_screen_size else (1920, 1080))
    sess.nw, sess.nh = nw, nh
    # Same resolution policy as the TCP GPU path: 0 = native desktop.
    if sess.lan:
        ew = _get_int("lan_width", 0) or nw
        eh = _get_int("lan_height", 0) or nh
    else:
        ew = _get_int("wan_width", 0) or nw
        eh = _get_int("wan_height", 0) or nh
    ew, eh = min(ew, nw), min(eh, nh)
    cap = (nw, nh) if (ew != nw or eh != nh) else None
    cq, maxrate, bufsize = sess.rtp_params()

    def _mk():
        s = GPUStreamer(ew, eh, fps=sess.fps, gop=sess.gop, cq=cq,
                        preset=sess.preset, maxrate=maxrate, bufsize=bufsize,
                        capture_w=cap[0] if cap else ew,
                        capture_h=cap[1] if cap else eh,
                        slices=_get_int("slices", 4))
        if not s.first_frame(timeout=2.0):
            s.close()
            return None
        return s

    return await sess.loop.run_in_executor(executor, _mk)


async def _start_rtp(sess):
    """Build the GPUStreamer + RTPVideoTransport for the UDP path and push the
    screen_config + offer to the client. Stores the transport on sess.rtp and
    the (swappable) streamer ref on sess.rtp_ref; returns None if capture
    could not be started."""
    streamer = await _rtp_start_streamer(sess)
    if streamer is None:
        return None

    ref = [streamer]

    async def _rtp_send(data):
        try:
            await sess.ws.send(data)
        except Exception:
            pass

    if sess.rtp_keyframe is None:
        sess.rtp_keyframe = asyncio.Event()

    # 发送端 pacer(可选,config rtp_pacer_mbps):平滑一帧 ~90+ 包的突发。
    # 必须高于编码器实际产出速率,否则会饿死发送端并增加延迟;故默认 0=关闭,
    # 待真机测量后再决定是否开启与取值。
    try:
        _pm = float(_cfg.get("rtp_pacer_mbps", 0) or 0)
    except (TypeError, ValueError):
        _pm = 0.0
    pacer_bps = int(_pm * 1_000_000) if _pm > 0 else 0

    try:
        transport = RTPVideoTransport(_rtp_send, ref, streamer.fps, sess.ice_servers,
                                      on_keyframe=sess.rtp_keyframe.set,
                                      pacer_bps=pacer_bps)
        offer = await transport.create_offer()
    except Exception:
        # 协商都起不来就没必要留着占 DXGI/NVENC 的采集进程。
        try:
            streamer.close()
        except Exception:
            pass
        raise
    # 只有 offer 真正建好后再挂到 sess:期间 sess.rtp_pending 让 TCP sender 保持空闲,
    # 失败时 sess.rtp 仍为 None,不会把 _gpu_sender 永久挡在门外。
    sess.rtp_ref = ref
    sess.rtp = transport
    _gpu_dbg(f"RTP offer sent ({len(offer.sdp)} bytes)")
    await sess.ws.send(json.dumps({
        "type": "screen_config",
        "codec": _avc1_codec(streamer.width, streamer.height, streamer.fps, streamer._encoder),
        "width": streamer.width,
        "height": streamer.height,
        "raw_width": sess.nw,
        "raw_height": sess.nh,
        "enc": streamer._encoder,
        "fps": streamer.fps,
    }))
    await sess.ws.send(json.dumps({
        "type": "rtp_offer",
        "sdp": offer.sdp,
        "sdp_type": offer.type,
    }))
    return transport


async def _rtp_restart_streamer(sess):
    """Rebuild the RTP streamer at the current bitrate tier and swap it into
    the live transport (the track reads sess.rtp_ref[0] each recv). Serialised
    by sess.rtp_lock: the bitrate loop and the keyframe loop both call this."""
    ref = getattr(sess, "rtp_ref", None)
    if not sess.rtp or not ref:
        return
    async with sess.rtp_lock:
        new_s = await _rtp_start_streamer(sess)
        if new_s is None:
            return
        old, ref[0] = ref[0], new_s
        _gpu_dbg(f"RTP restart streamer (tier {sess._bitrate_tier})")
        try:
            old.close()
        except Exception:
            pass


_RTP_KEY_COOLDOWN = 1.5  # 两次按需关键帧之间的最小间隔(秒)
# 只有"距下一个自然 IDR 还很久"时,重建编码器才划算:重建要 ~0.5-2s 且有帧空窗,
# 而 gop/fps 就是自然 IDR 间隔(当前 gop=15 @32fps ≈ 0.47s,等自然 IDR 更快)。
# 所以 GOP 短时直接忽略 PLI,只对长 GOP(如弱网大 GOP)启用。
_RTP_KEY_MIN_GOP_S = 1.0


async def _rtp_keyframe_loop(sess):
    """PLI/FIR 驱动的按需关键帧。RTP 模式没有业务通道,客户端无法发
    request_keyframe(RTCP PLI 是唯一途径)。重建编码器强制出 IDR 需要
    ~0.5-2s 且有帧空窗,必须限流并按 GOP 长度判断是否值得做:不限流会变成
    "PLI→重启→IDR 突发→更多丢包"的风暴;GOP 短时等自然 IDR 反而更快。"""
    ev = sess.rtp_keyframe
    if ev is None:
        return
    gop_s = (sess.gop / max(1, sess.fps)) if sess.fps else 99.0
    force = gop_s >= _RTP_KEY_MIN_GOP_S
    last = 0.0
    while sess.running and sess.rtp is not None:
        try:
            await asyncio.wait_for(ev.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        ev.clear()
        if not force:
            continue
        now = time.monotonic()
        if now - last < _RTP_KEY_COOLDOWN:
            await asyncio.sleep(_RTP_KEY_COOLDOWN - (now - last))
            ev.clear()  # 合并等待期间到达的新请求
        last = time.monotonic()
        if sess.rtp is None:
            break
        _gpu_dbg("RTP keyframe request -> restarting encoder")
        await _rtp_restart_streamer(sess)


async def _rtp_bitrate_loop(sess):
    """RTP 拥塞判断:RTCP RR 的丢包率 + RTT(相对历史最低基线的排队量)。
    丢包驱动"真丢包"型拥塞;RTT 驱动"只加延迟不丢包"型瓶颈(如 Tailscale DERP
    中继/整形队列——包没丢、只在排队,丢包判据对此永远失明)。TCP 档由客户端
    _bitrateAdapt 按 RTT 分档,RTP 档此前只看丢包、遇到后者永不退让,这里补上
    同一能力,阈值与 TCP 档对齐:>80ms 持续 ~5s 升一档、>200ms 直达 tier2;
    回档需 RTT 回到基线 <30ms 且丢包未达拥塞线(<4%)持续 ~20s。档位变化经
    _rtp_restart_streamer 换流。"""
    prev_lost = prev_sent = 0
    bad = 0                 # 连续"丢包>4%" tick 数(升档判据一)
    rtt_bad = 0             # 连续"超基线>80ms" tick 数(升档判据二)
    clean = 0               # "RTT<基线+30ms 且丢包<4%" 累计 tick(回档判据)
    rtt_base = None
    while sess.running and sess.rtp is not None and sess.streaming:
        try:
            report = await sess.rtp._pc.getStats()
            lost = sent = None
            rtt = None
            loss_val = None
            for s in report.values():
                if s.type == "remote-inbound-rtp":
                    lost = getattr(s, "packetsLost", None)
                    # aiortc 由 RTCP RR 的 LSR/DLSR 算出 RTT 再 EMA 平滑,首个 RR 前为 None。
                    r = getattr(s, "roundTripTime", None)
                    if r is not None and r > 0:
                        rtt = float(r) * 1000.0   # 秒 → ms
                elif s.type == "outbound-rtp":
                    sent = getattr(s, "packetsSent", None)

            escalated = False

            # ── 升档信号一:RTT 超历史最低基线(=排队量),阈值对齐 TCP 档 _bitrateAdapt ──
            if rtt is not None:
                if rtt_base is None or rtt < rtt_base:
                    rtt_base = rtt
                over = rtt - rtt_base
                if over > 80:
                    rtt_bad += 1
                    clean = 0
                else:
                    rtt_bad = 0
                if rtt_bad >= 3 and sess._bitrate_tier < 2:
                    step = 2 if over > 200 else 1   # >200ms 的深排队直达 tier2
                    sess._bitrate_tier = min(2, sess._bitrate_tier + step)
                    rtt_bad = 0
                    clean = 0
                    escalated = True
                    print(f"  RTP bitrate escalate: tier {sess._bitrate_tier} "
                          f"(rtt {rtt:.0f}ms, base {rtt_base:.0f}ms, over {over:.0f}ms)")
                    await _rtp_restart_streamer(sess)

            # ── 升档信号二:丢包(原有判据,阈值不变) ──
            if lost is not None and sent is not None and sent > prev_sent:
                if prev_sent == 0:
                    # 首次采样:只初始化基线,避免把连接建立前的历史累计丢包
                    # 误判为当前周期丢包。
                    prev_lost, prev_sent = lost, sent
                else:
                    loss_val = max(0.0, lost - prev_lost) / (sent - prev_sent)
                    prev_lost, prev_sent = lost, sent
                    # 移动网络基线丢包约 3%(射频导致,降码率无用),升档阈值
                    # 给足余量(>4% 才算真恶化)。
                    if loss_val > 0.04:
                        bad += 1
                        clean = 0
                        if bad >= 3 and sess._bitrate_tier < 2:
                            sess._bitrate_tier += 1
                            bad = 0
                            escalated = True
                            print(f"  RTP bitrate escalate: tier {sess._bitrate_tier} (loss {loss_val:.1%})")
                            await _rtp_restart_streamer(sess)
                    elif loss_val < 0.01:
                        bad = 0

            # ── 回档:两信号都干净才降。RTT 回到基线 <30ms 且丢包 <4% 才累计;
            #    中间地带(丢 1~4% 或 RTT 超基线 30~80ms)不累计不清零,任一明确恶化即清零。 ──
            if not escalated:
                congested = ((loss_val is not None and loss_val >= 0.04) or
                             (rtt is not None and rtt_base is not None and rtt - rtt_base > 80))
                if congested:
                    clean = 0
                elif rtt is None or (rtt_base is not None and rtt - rtt_base < 30):
                    clean += 1
                if sess._bitrate_tier > 0 and clean >= 10:
                    sess._bitrate_tier -= 1
                    clean = 0
                    print(f"  RTP bitrate recover: tier {sess._bitrate_tier}")
                    await _rtp_restart_streamer(sess)
        except Exception as e:
            print(f"  RTP stats error: {e!r}")
        await asyncio.sleep(2.0)


async def _legacy_sender(sess):
    """Pipeline: capture thread -> encode thread -> sender paced by absolute schedule."""
    fps, gop = _soft_clamp(sess.fps, sess.gop)
    interval = 1.0 / fps
    lan = sess.lan
    stop = threading.Event()
    raw_q = queue.Queue(maxsize=2)
    out_q = queue.Queue(maxsize=2)
    encoder = None

    def _drop_oldest(q):
        try:
            q.get_nowait()
        except queue.Empty:
            pass

    def capture_worker():
        cap_dt = interval * 0.95
        last_cap = 0.0
        last_pos = None
        while not stop.is_set():
            if sess.streaming and _STREAMING and not sess.webrtc and not sess.rtp and not sess.rtp_pending:
                try:
                    _pos = get_cursor_pos()
                    if _pos != last_pos:
                        last_pos = _pos
                        cap_dt = interval * 0.95
                    else:
                        cap_dt = 0.05
                except Exception:
                    cap_dt = interval * 0.95
                now = time.monotonic()
                if now < last_cap:
                    time.sleep(last_cap - now)
                    continue
                try:
                    raw, _, _ = capture.capture_screen_raw()
                    if raw is not None:
                        if raw_q.full():
                            _drop_oldest(raw_q)
                        raw_q.put(raw)
                except Exception:
                    pass
                last_cap = time.monotonic() + cap_dt
            else:
                time.sleep(0.5)

    def encode_worker():
        nonlocal encoder
        while not stop.is_set():
            if not (sess.streaming and _STREAMING and not sess.webrtc and not sess.rtp and not sess.rtp_pending):
                time.sleep(0.5)
                continue
            try:
                raw = raw_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if encoder is None:
                    h, w = raw.shape[:2]
                    if not lan and _WAN_W and cv2 is not None:
                        ew, eh = _WAN_W, _WAN_H
                    elif capture is not None and capture.IS_SOFT and cv2 is not None:
                        ew, eh = _SOFT_WIDTH, _SOFT_HEIGHT
                    else:
                        ew = _get_int("lan_width", 0) or w
                        eh = _get_int("lan_height", 0) or h
                    cq, maxrate, bufsize = sess.effective_params()
                    encoder = H264Encoder(ew, eh, fps=fps, gop=gop, cq=cq,
                                          maxrate=maxrate, bufsize=bufsize,
                                          preset=sess.preset)
                    while not out_q.empty():
                        _drop_oldest(out_q)
                    out_q.put(("config", ew, eh, w, h, encoder.enc_name))
                frame = raw
                if cv2 is not None and (raw.shape[1], raw.shape[0]) != (ew, eh):
                    frame = cv2.resize(raw, (ew, eh))
                h264 = encoder.encode(frame)
                if h264:
                    if out_q.full():
                        _drop_oldest(out_q)
                    out_q.put(("data", has_idr(h264), h264))
            except Exception:
                traceback.print_exc()
                if encoder is not None:
                    try:
                        encoder.close()
                    except Exception:
                        pass
                    encoder = None

    threading.Thread(target=capture_worker, daemon=True).start()
    threading.Thread(target=encode_worker, daemon=True).start()

    dropper = _FrameDropper(sess.gop, sess.fps)
    try:
        next_send = time.monotonic()
        while sess.running:
            if sess.streaming and _STREAMING and not sess.webrtc and not sess.rtp and not sess.rtp_pending:
                if sess._keyframe_request.is_set():
                    sess._keyframe_request.clear()
                    if encoder is not None:
                        encoder.close()
                        encoder = None
                    continue
                try:
                    item = out_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.005)
                    continue
                now = time.monotonic()
                if next_send > now:
                    await asyncio.sleep(next_send - now)
                if item[0] == "config":
                    await sess.send_config(item[1], item[2], item[3], item[4], fps, item[5])
                else:
                    if dropper.keep(item[1], sess._bitrate_tier):
                        await sess.ws.send(_frame_packet(item[1], sess.frame_seq, item[2]))
                        sess.frame_seq += 1
                next_send += interval
            else:
                if encoder is not None:
                    encoder.close()
                    encoder = None
                next_send = time.monotonic()
                await asyncio.sleep(0.5)
    except websockets.exceptions.ConnectionClosed:
        return
    finally:
        stop.set()
        if encoder is not None:
            try:
                encoder.close()
            except Exception:
                pass


async def _gpu_sender(sess):
    """Pure-GPU pipeline: ffmpeg ddagrab (DXGI) -> NVENC. The CPU only
    reads the encoded H.264 access units from ffmpeg's stdout."""
    streamer = None
    config_sent = False
    closing = threading.Event()
    deaths = 0
    death_ts = 0.0

    def start_streamer():
        nonlocal streamer, config_sent
        if streamer is not None:
            return True
        # Re-read the native desktop size on every (re)start: a resolution
        # change applies on the next reconnect without a server restart.
        # (The startup-cached _NATIVE_W/H would stay stale after the user
        # changes the desktop resolution — see the canvas mismatch bug.)
        nw, nh = (_native_screen_size() if _native_screen_size else (1920, 1080))
        sess.nw, sess.nh = nw, nh
        # Resolution: blank/0 in config = native desktop. Set lan_width/lan_height
        # (LAN) or wan_width/wan_height (WAN) to downscale the output; the desktop
        # is still captured at native and scaled by the encoder filter, so the
        # whole picture is shown, just at a lower resolution.
        if sess.lan:
            ew = _get_int("lan_width", 0) or nw
            eh = _get_int("lan_height", 0) or nh
        else:
            ew = _get_int("wan_width", 0) or nw
            eh = _get_int("wan_height", 0) or nh
        ew, eh = min(ew, nw), min(eh, nh)
        cap = (nw, nh) if (ew != nw or eh != nh) else None
        cq, maxrate, bufsize = sess.effective_params()
        s = GPUStreamer(ew, eh, fps=sess.fps, gop=sess.gop, cq=cq,
                        preset=sess.preset, maxrate=maxrate, bufsize=bufsize,
                        capture_w=cap[0] if cap else ew,
                        capture_h=cap[1] if cap else eh)
        # Register before first_frame: this runs on the executor thread,
        # and a disconnect while it is starting would cancel the coroutine
        # with streamer still None — leaking the ffmpeg process (which
        # keeps holding DXGI). Registering early lets the finally close it.
        streamer = s
        sess.tcp_streamer = s
        ok = False
        try:
            ok = s.first_frame(timeout=2.0)
        finally:
            if closing.is_set():
                s.close()
        if ok:
            config_sent = False
            return True
        s.close()
        streamer = None
        sess.tcp_streamer = None
        return False

    dropper = _FrameDropper(sess.gop, sess.fps)
    # Secure-desktop (UAC consent / lock screen) notice: DXGI duplication loses
    # access while the input desktop is Winlogon, so ffmpeg dies and the viewer
    # is left staring at a frozen last frame with nothing to explain it. The
    # probe runs as its own task because a poll inside the loop below gets
    # starved exactly when it matters — one iteration can spend seconds in the
    # start-retry block (each attempt sleeps 1.5s) and then end the connection.
    # Measured 22:37:53-58: the desktop flipped in that window, the loop never
    # polled again, and the client's watchdog had to reconnect instead.
    secure_last = False

    async def _secure_watch():
        nonlocal secure_last
        while sess.running and not closing.is_set():
            if sess.streaming and not sess.webrtc and not sess.rtp and not sess.rtp_pending:
                try:
                    secure = is_secure_desktop()
                except Exception:
                    secure = False
                if secure != secure_last:
                    secure_last = secure
                    _gpu_dbg("secure desktop: " + ("entered" if secure else "left"))
                    try:
                        await sess.ws.send(json.dumps({
                            "type": "screen_paused" if secure else "screen_resumed"}))
                    except Exception:
                        pass
            await asyncio.sleep(0.5)

    watch_task = asyncio.create_task(_secure_watch())
    try:
        while sess.running:
            if sess.streaming and _STREAMING and not sess.webrtc and not sess.rtp and not sess.rtp_pending:
                if sess._keyframe_request.is_set():
                    sess._keyframe_request.clear()
                    if streamer:
                        _gpu_dbg("keyframe request: restarting encoder")
                        streamer.close()
                        streamer = None
                    continue
                if streamer is None:
                    # DXGI access can be transiently lost (lock screen, UAC,
                    # session switch); retry a few times before giving up
                    # and falling back to the legacy (green-crosshair) path.
                    if secure_last:
                        # Spawning ffmpeg is pointless while the secure desktop
                        # owns the screen: ddagrab is denied every time and each
                        # attempt only spams the log. The watcher above clears
                        # secure_last as soon as the desktop is back.
                        await asyncio.sleep(0.5)
                        continue
                    ok = False
                    for attempt in range(_GPU_START_RETRIES):
                        try:
                            ok = await sess.loop.run_in_executor(executor, start_streamer)
                        except Exception as e:
                            # While the secure desktop owns the screen, ddagrab
                            # reports "access denied" and every encoder probe
                            # fails, which raises instead of returning False.
                            # Treat it as a failed attempt: letting it escape
                            # killed the sender loop outright, so the viewer
                            # neither got the pause notice nor an in-place retry.
                            _gpu_dbg(f"start_streamer raised: {e!r}")
                            ok = False
                        _gpu_dbg(f"start_streamer attempt {attempt + 1} -> {ok}")
                        if ok:
                            break
                        await asyncio.sleep(_GPU_START_RETRY_DELAY)
                    if not ok:
                        if secure_last:
                            # Capture is impossible until the secure desktop
                            # goes away; stay on this connection and retry
                            # instead of ending the stream and making the
                            # client's watchdog reconnect in a loop.
                            continue
                        await _fallback_to_legacy(sess, "failed to start")
                        return
                    continue
                if not streamer.alive():
                    _gpu_dbg(f"streamer dead (rc={streamer._proc.returncode})")
                    streamer.close()
                    streamer = None
                    sess.tcp_streamer = None
                    # Access loss is usually momentary (UAC, lock screen,
                    # display state churn): respawn in-place via the
                    # streamer-is-None retry path below instead of dropping
                    # the connection and waiting seconds for the client's
                    # frame-stall watchdog to reconnect.
                    deaths += 1
                    death_ts = time.monotonic()
                    if deaths >= _GPU_DEATH_RETRIES:
                        await _fallback_to_legacy(sess, "died")
                        return
                    continue
                # block until the next encoded frame arrives (the ffmpeg
                # cadence paces delivery; no artificial timing that could
                # burst or stall on the event loop)
                item = await sess.loop.run_in_executor(
                    executor, lambda: streamer.read(0.5))
                if item is None:
                    await asyncio.sleep(0.005)
                    continue
                is_idr, data = item
                if not config_sent:
                    config_sent = True
                    await sess.send_config(streamer.width, streamer.height,
                                           sess.nw, sess.nh, streamer.fps,
                                           streamer._encoder)
                if dropper.keep(is_idr, sess._bitrate_tier):
                    await sess.ws.send(_frame_packet(is_idr, sess.frame_seq, data))
                    sess.frame_seq += 1
                # frames flowing again: forgive past deaths once the stream
                # has stayed up a minute after the last one
                if deaths and time.monotonic() - death_ts > 60:
                    deaths = 0
            else:
                if streamer:
                    streamer.close()
                    streamer = None
                    sess.tcp_streamer = None
                secure_last = False
                await asyncio.sleep(0.5)
    except websockets.exceptions.ConnectionClosed:
        return
    except Exception as e:
        traceback.print_exc()
        _gpu_dbg(f"gpu sender exception: {e!r}")
    finally:
        closing.set()
        watch_task.cancel()
        if streamer:
            streamer.close()
            streamer = None
            sess.tcp_streamer = None


async def _fallback_to_legacy(sess, reason):
    # GPU capture lost (UAC / lock screen / session switch).  The old dxcam
    # legacy pipeline is native-crash-prone here (BEX64 / 0xc0000409 on some
    # GPU configs — Q470) and cannot capture the secure desktop anyway, so we
    # do NOT switch to it.  Instead this connection simply stops streaming:
    # the client's frame-stall watchdog reconnects and retries the GPU path
    # until capture becomes available again.
    _gpu_dbg(f"fallback to legacy ({reason})")
    print(f"  GPU streamer {reason} — pausing stream; client will reconnect")
    await asyncio.sleep(1)


async def ws_handler(websocket):
    """Video channel: H.264 frames + WebRTC negotiation."""
    _set_nodelay(websocket)
    ip = _real_ip(websocket.request.headers, websocket.remote_address[0] if websocket.remote_address else "")
    _audit("WS CONNECT", ip)
    lan = _is_lan(ip)
    sess = _VideoSession(
        websocket, lan,
        _pick_int(lan, "max_fps", "max_fps_lan", MAX_FPS),
        _pick_int(lan, "gop", "gop_lan", GOP_SIZE),
        _pick_int(lan, "cq", "cq_lan", 26, 18),
        _pick(lan, "preset", "preset_lan", "p4", "p1"),
        _pick(lan, "maxrate", "maxrate_lan", "6M", "40M"),
        _pick(lan, "bufsize", "bufsize_lan", "6M", "40M"),
        _cfg.get("ice_servers", []),
    )
    _webrtc_timeout_task = None

    # _ffmpeg_ready() re-checks the file so a just-downloaded ffmpeg is
    # picked up. Every connection re-evaluates the GPU path: when ffmpeg is
    # present we always try it (a transient UAC/lock loss falls back to
    # pausing, never to the crash-prone dxcam pipeline); when ffmpeg is
    # absent the pure-soft legacy pipeline runs from the start.
    async def screen_sender():
        if _ffmpeg_ready() and GPUStreamer is not None:
            _gpu_dbg("sender: GPU path selected")
            await _gpu_sender(sess)
        else:
            _gpu_dbg("sender: legacy path selected")
            await _legacy_sender(sess)

    sender_task = asyncio.create_task(screen_sender())

    try:
        async for message in websocket:
            if not isinstance(message, str):
                continue
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                continue

            cmd = msg.get("type", "")

            if cmd == "set_mode":
                if not msg.get("screen", False):
                    if sess.webrtc:
                        await sess.webrtc.close()
                        sess.webrtc = None
                    if sess.rtp:
                        await sess.rtp.close()
                        sess.rtp = None
                    sess.rtp_pending = False
                else:
                    fmt = msg.get("format")
                    # 传输方式切换时必须释放另一条路径的资源,否则旧的 RTP
                    # GPUStreamer 仍占着 DXGI/NVENC,与 TCP/webrtc 新采集冲突。
                    if sess.rtp and fmt != "rtp":
                        await sess.rtp.close()
                        sess.rtp = None
                    if sess.webrtc and fmt != "webrtc":
                        await sess.webrtc.close()
                        sess.webrtc = None
                sess.streaming = msg.get("screen", False)
                sess.rtp_pending = sess.streaming and msg.get("format") == "rtp" and RTPVideoTransport is not None
                if sess.streaming and WebRTCSession and msg.get("format") == "webrtc":
                    async def _webrtc_send(data):
                        try:
                            await websocket.send(data)
                        except Exception:
                            pass
                    async def _dc_handler(msg_str):
                        try:
                            await _exec_cmd(json.loads(msg_str))
                        except Exception:
                            pass
                    s = WebRTCSession(_webrtc_send, _dc_handler, sess.ice_servers)
                    track_fps, _ = _soft_clamp(sess.fps, sess.gop)
                    s.add_track(capture.capture_screen_raw, track_fps)
                    offer = await s.create_offer()
                    sess.webrtc = s
                    await websocket.send(json.dumps({
                        "type": "webrtc_offer",
                        "sdp": offer.sdp,
                        "sdp_type": offer.type,
                    }))
                    _webrtc_timeout_task = asyncio.create_task(_webrtc_timeout(sess))
                elif sess.streaming and RTPVideoTransport and msg.get("format") == "rtp":
                    if sess.rtp:
                        await sess.rtp.close()
                        sess.rtp = None
                    # 先等非 RTP sender 让出采集再冷启动:rtp_pending 门控是轮询的
                    # (最多 ~0.5s 后 sender 会自己关 ffmpeg),不等的话两套 ffmpeg
                    # 并抢 NVENC/DXGI,拖慢 first_frame、更容易超客户端协商超时。
                    _t0 = time.monotonic()
                    while sess.tcp_streamer is not None and time.monotonic() - _t0 < 2.0:
                        await asyncio.sleep(0.05)
                    try:
                        transport = await _start_rtp(sess)
                    except Exception:
                        traceback.print_exc()
                        transport = None
                    sess.rtp_pending = False
                    if transport is None:
                        await websocket.send(json.dumps({"type": "rtp_failed", "reason": "no streamer"}))
                    else:
                        _task = asyncio.create_task(_rtp_bitrate_loop(sess))
                        _BACKGROUND_TASKS.add(_task)
                        _task.add_done_callback(_BACKGROUND_TASKS.discard)
                        _ktask = asyncio.create_task(_rtp_keyframe_loop(sess))
                        _BACKGROUND_TASKS.add(_ktask)
                        _ktask.add_done_callback(_BACKGROUND_TASKS.discard)
            elif cmd == "rtp_answer":
                if sess.rtp:
                    await sess.rtp.handle_answer(msg["sdp"], msg.get("sdp_type", "answer"))
                    _gpu_dbg(f"rtp_answer handled, ICE={sess.rtp._pc.iceConnectionState}")
            elif cmd == "rtp_ice":
                if sess.rtp:
                    await sess.rtp.add_ice(msg["candidate"])
            elif cmd == "webrtc_answer":
                if sess.webrtc:
                    await sess.webrtc.handle_answer(msg["sdp"], msg.get("sdp_type", "answer"))
            elif cmd == "webrtc_ice":
                if sess.webrtc:
                    await sess.webrtc.add_ice(msg["candidate"])
            elif cmd == "bitrate_adapt":
                tier = max(0, min(2, int(msg.get("tier", 0))))
                if tier != sess._bitrate_tier:
                    print(f"  bitrate adapt: tier {sess._bitrate_tier} -> {tier}")
                    sess._bitrate_tier = tier
            elif cmd == "request_keyframe":
                if sess.streaming and not sess.webrtc:
                    sess._keyframe_request.set()
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _audit("WS DISCONNECT", ip)
        sess.running = False
        sender_task.cancel()
        if sess.webrtc:
            asyncio.ensure_future(sess.webrtc.close())
        if sess.rtp:
            asyncio.ensure_future(sess.rtp.close())
        if _webrtc_timeout_task:
            _webrtc_timeout_task.cancel()
        try:
            await sender_task
        except asyncio.CancelledError:
            pass
        print(f"WS disconnected: {websocket.remote_address}")


# ── Main ──
async def main():
    global _CERT_FINGERPRINT
    set_process_priority()

    if speech is not None:
        speech.init(_cfg)

    if is_wayland():
        print("WARNING: Wayland session detected — DeskBeam's Linux capture is X11-only")
        print("  (x11grab / xrandr / XTest). XWayland only exposes X11 clients, so a")
        print("  stream would be black or partial instead of failing loudly.")
        print("  Fix: log in to an 'Ubuntu on Xorg' session, or set WaylandEnable=false")
        print("  in /etc/gdm3/custom.conf and reboot. Remote-only mode still works.")

    if not _STREAMING:
        print("Streaming unavailable — running remote-only mode.")
        print("  Install for streaming: pip install av numpy dxcam")

    if SSL_CERT.is_file() and SSL_KEY.is_file():
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(SSL_CERT, SSL_KEY)
        # 自身证书指纹：前端登录后记录，每次访问校验。若连接到的服务器证书
        # 指纹与记录的指纹不同，说明可能被中间人（ARP 欺骗 + 伪证书）劫持。
        # 直接从 PEM 文件解析（不依赖 get_certificate 的版本差异）。
        _CERT_FINGERPRINT = _pem_fingerprint(SSL_CERT)
        proto = "https"
    else:
        ssl_context = None
        _CERT_FINGERPRINT = ""
        proto = "http"

    if not WEB_DIR.is_dir():
        print(f"ERROR: web directory not found: {WEB_DIR}")
        print("  The web/ directory contains the browser UI files and must be present.")
        sys.exit(1)

    asyncio.create_task(_mouse_flush_task())

    # Auto-download ffmpeg in the background if it is missing and a URL is
    # configured (config "ffmpeg_url").  The server starts immediately; the
    # GPU pipeline is selected dynamically once ffmpeg is available.
    _ffmpeg_url = str(_cfg.get("ffmpeg_url", "") or "").strip()
    if _STREAMING and _ffmpeg_url and not _ffmpeg_ready():
        threading.Thread(target=lambda: _ensure_ffmpeg(_ffmpeg_url), daemon=True).start()

    global _server
    # compression=None: permessage-deflate 对已编码的 H.264 帧毫无收益(不可压缩),
    # 却让每帧都过一遍 deflate/inflate —— 服务端白烧 CPU,手机端解压还站在解码
    # 关键路径上。信令 JSON 很小,不值得为此保留压缩。
    _server = await websockets.serve(
        ws_dispatch,
        HOST,
        PORT,
        ssl=ssl_context,
        process_request=http_handler,
        compression=None,
        ping_interval=30,
        ping_timeout=10,
    )
    print(f"Ready.  {proto}://{LAN_IP}:{PORT}")
    await _server.wait_closed()


if __name__ == "__main__":
    _write_pid()
    _kill_old_instances()
    _truncate_log()
    log_fh = _redirect_log()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
    finally:
        _unlink_pid()
        if log_fh:
            log_fh.close()
