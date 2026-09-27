"""Screen capture + H.264 encoding via a bundled/system ffmpeg.

Windows pipeline: ddagrab (DXGI Desktop Duplication, D3D11) -> h264_nvenc.
Everything stays on the GPU; the CPU only reads the encoded H.264 bitstream
from ffmpeg's stdout. This is the same architecture as Sunshine.

Linux pipeline: x11grab -> h264_vaapi (per renderD device probe) -> libx264.
X11 grabs emit frames at a steady cadence even on a static desktop, so the
Win32 nudge window is not needed.

Requires an ffmpeg binary with the matching filters/encoders.
"""

import ctypes
import glob
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

_IS_WIN = sys.platform == "win32"
if _IS_WIN:
    import ctypes.wintypes

# 编码器启动失败的错误关键字（ffmpeg stderr）。探测阶段抓到即判失败，
# 不依赖进程退出——有些失败（挂起不产帧）进程不退，但 stderr 会报错。
_ENC_ERROR_RE = re.compile(
    br"cannot load|unknown encoder|error while opening|could not open|"
    br"not support|impossible to convert|error reinitializing|"
    br"failed to configure|invalid argument|no such file",
    re.IGNORECASE,
)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Wayland guard (Linux): the capture path here is x11grab + xrandr, and input
# injection is XTest - all X11-only. Under a Wayland session XWayland still
# sets DISPLAY so x11grab starts and "works", but it can only see X11 clients,
# which shows up as a black or half-empty picture with no error. Detect it and
# refuse with the reason instead of streaming something misleading.
try:
    from platform_api import is_wayland, session_type
except Exception:  # platform_api unavailable: never block capture on this
    def is_wayland():
        return False

    def session_type():
        return "unknown"

_WAYLAND_MSG = (
    "Wayland session detected (XDG_SESSION_TYPE=wayland): DeskBeam's Linux "
    "capture is X11-only (x11grab/xrandr/XTest). XWayland would only expose "
    "X11 clients, so the stream would be black or partial. Log in to an "
    "'Ubuntu on Xorg' session, or set WaylandEnable=false in "
    "/etc/gdm3/custom.conf and reboot. Remote-only mode still works."
)


def _find_ffmpeg():
    exe = "ffmpeg.exe" if _IS_WIN else "ffmpeg"
    cands = []
    if getattr(sys, "frozen", False):
        # PyInstaller onefile: ffmpeg may be bundled inside _MEIPASS, or kept
        # as an external ffmpeg/ folder next to the exe (smaller, faster start).
        cands += [
            os.path.join(getattr(sys, "_MEIPASS", _SCRIPT_DIR), "ffmpeg", exe),
            os.path.join(os.path.dirname(sys.executable), "ffmpeg", exe),
        ]
    else:
        cands.append(os.path.join(_SCRIPT_DIR, "ffmpeg", exe))
    if not _IS_WIN:
        found = shutil.which("ffmpeg")
        if found:
            cands.append(found)
    globals()["_FFMPEG_CANDIDATES"] = cands
    return next((p for p in cands if os.path.isfile(p)), cands[0])


FFMPEG_EXE = _find_ffmpeg()
FFMPEG_EXISTS = os.path.isfile(FFMPEG_EXE)

_DEBUG_FILE = os.path.join(tempfile.gettempdir(), "gpu_stream_debug.txt")


def _dbg(msg):
    try:
        with open(_DEBUG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def ffmpeg_ready():
    """True when an ffmpeg.exe is available (any of the candidate paths)."""
    return any(os.path.isfile(p) for p in _FFMPEG_CANDIDATES)


def ensure_ffmpeg(url=None, timeout=900):
    """Auto-download ffmpeg.exe if it is missing and a URL is configured.

    Returns True when ffmpeg is available afterwards.  Downloads to the
    writable candidate path (next to the exe when frozen, else next to the
    script) and verifies the binary runs before installing it.
    """
    if ffmpeg_ready():
        return True
    if not url:
        _dbg("ffmpeg missing; no ffmpeg_url configured, GPU streaming unavailable")
        return False
    target = _FFMPEG_CANDIDATES[-1]  # writable: exe dir (frozen) / script dir (dev)
    tmp = target + ".tmp"
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        _dbg(f"downloading ffmpeg -> {target}")
        req = urllib.request.Request(url, headers={"User-Agent": "DeskBeam/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        if not _IS_WIN:
            os.chmod(tmp, 0o755)
        if _verify_ffmpeg(tmp):
            os.replace(tmp, target)
            _dbg("ffmpeg downloaded and verified OK")
            return True
        _dbg("downloaded file failed ffmpeg verification, discarding")
    except Exception as e:
        _dbg(f"ffmpeg download failed: {e!r}")
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    return ffmpeg_ready()


def _verify_ffmpeg(path):
    try:
        r = subprocess.run([path, "-version"], capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def _xrandr_primary():
    """(w, h, refresh) of the primary output via xrandr; (0, 0, 0) when
    unavailable. Refresh falls back to 0 when the driver's mode table only
    marks the current mode without printing its rate — snap_fps treats 0 as
    'no snapping'."""
    try:
        r = subprocess.run(["xrandr", "--query"], capture_output=True, timeout=5)
        lines = r.stdout.decode("utf-8", "replace").splitlines()
    except Exception:
        return 0, 0, 0.0
    start = -1
    geom = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(\S+) connected(?: primary)?\s+(\d+)x(\d+)\+\d+\+\d+", ln)
        if m and ("primary" in ln or start == -1):
            geom = (int(m.group(2)), int(m.group(3)))
            if "primary" in ln:
                start = i
                break
            start = i
    if start != -1:
        for ln in lines[start + 1:]:
            if re.match(r"^\S+ (connected|disconnected)", ln):
                break  # next output block
            rm = re.search(r"([\d.]+)\s*\*", ln)
            if rm:
                try:
                    return geom[0], geom[1], float(rm.group(1))
                except ValueError:
                    break
    return (geom[0], geom[1], 0.0) if geom else (0, 0, 0.0)


def native_screen_size():
    """Return the primary monitor resolution (native capture size)."""
    if not _IS_WIN:
        w, h, _ = _xrandr_primary()
        if w:
            return w, h
        try:
            from Xlib import display as _xd
            s = _xd.Display().screen()
            return int(s.width_in_pixels), int(s.height_in_pixels)
        except Exception:
            return 1920, 1080
    try:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def refresh_rate():
    """Return the primary display refresh rate in Hz (best effort)."""
    if not _IS_WIN:
        return int(_xrandr_primary()[2])
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        dc = user32.GetDC(0)
        try:
            rate = gdi32.GetDeviceCaps(dc, 116)  # VREFRESH
        finally:
            user32.ReleaseDC(0, dc)
        return int(rate)
    except Exception:
        return 0


def snap_fps(requested, refresh=None):
    """Pick an fps that keeps the capture cadence steady without over-downgrading.

    ddagrab paces its captures against the monitor's presents; a badly
    non-integer ratio of presents-per-frame (e.g. 60 fps on a 165 Hz panel =
    2.75) makes the capture cadence jitter, which shows up as periodic gaps.
    When that happens we snap to the divisor of the refresh rate closest to
    the request — but only if it costs little (<~15%).  Otherwise we keep the
    requested fps: on refresh rates like 75 Hz the only divisor is 25 fps, and
    running at 25 fps hurts far more than the mild cadence jitter at 60 fps.
    """
    if refresh is None:
        refresh = refresh_rate()
    if refresh <= 0 or requested <= 0:
        return max(int(requested), 1)
    req = int(requested)
    ratio = refresh / req
    if abs(ratio - round(ratio)) < 0.05:
        return req  # already a whole number of presents per frame
    best = 1
    for n in range(2, req + 1):
        if refresh % n == 0 and abs(n - req) < abs(best - req):
            best = n
    if best < req * 0.85:
        return req
    return best


class _NudgeWindow:
    """A tiny topmost window used to force Desktop Duplication to emit frames.

    DXGI Desktop Duplication only reports *surface changes*: on a perfectly
    static desktop ddagrab would emit nothing (no first frame, and the stream
    would stall). Briefly showing/hiding this 2x2 pixel corner window creates a
    real surface change so ddagrab always produces an initial frame. With
    ddagrab's `dup_frames=1` the stream then keeps flowing at `framerate`.
    """

    _CLS = "DeskBeamNudgeWnd"

    def __init__(self):
        self._user32 = ctypes.windll.user32
        self._hwnd = None
        self._pump_tid = None
        try:
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_longlong)

            @WNDPROC
            def wndproc(hwnd, msg, wp, lp):
                if msg == 0x000F:  # WM_PAINT
                    ps = ctypes.wintypes.PAINTSTRUCT()
                    self._user32.BeginPaint(hwnd, ctypes.byref(ps))
                    self._user32.EndPaint(hwnd, ctypes.byref(ps))
                    return 0
                return self._user32.DefWindowProcW(hwnd, msg, wp, lp)

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
                            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                            ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                            ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                            ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p)]

            wc = WNDCLASSW()
            wc.lpfnWndProc = wndproc
            wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            wc.lpszClassName = self._CLS
            self._user32.RegisterClassW(ctypes.byref(wc))
            w, h = native_screen_size()
            self._user32.CreateWindowExW.restype = ctypes.c_void_p
            self._hwnd = self._user32.CreateWindowExW(
                0x08000000 | 0x20,  # WS_EX_TOPMOST | WS_EX_TOOLWINDOW
                self._CLS, "n",
                0x40000000,  # WS_POPUP
                w - 2, h - 2, 2, 2, 0, 0, wc.hInstance, 0)
            if self._hwnd:
                threading.Thread(target=self._pump, daemon=True).start()
        except Exception:
            self._hwnd = None

    def _pump(self):
        self._pump_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = ctypes.wintypes.MSG()
        while self._user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def toggle(self, times=3, interval=0.4):
        """Flash the window a few times; each flash is a desktop surface change."""
        if not self._hwnd:
            return
        for _ in range(times):
            self._user32.ShowWindow(self._hwnd, 5)  # SW_SHOW
            time.sleep(interval)
            self._user32.ShowWindow(self._hwnd, 0)  # SW_HIDE
            time.sleep(interval)

    def destroy(self):
        if self._hwnd:
            self._user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._pump_tid:
            ctypes.windll.kernel32.PostThreadMessageW(self._pump_tid, 0x0012, 0, 0)  # WM_QUIT


def _popen_ffmpeg(cmd):
    """Spawn ffmpeg and lift it to ABOVE_NORMAL priority, matching the
    server process. Under CPU-heavy foreground apps a Normal-priority
    ffmpeg loses scheduling slices, its stdout pipe backs up, and the
    client sees frame-rate drops; ABOVE_NORMAL fixes that without the
    starvation risk HIGH would pose on a 4-core box."""
    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
              "bufsize": 0}
    if _IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, **kwargs)
    if _IS_WIN:
        try:
            PROCESS_SET_INFORMATION = 0x0200
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, proc.pid)
            if h:
                try:
                    ctypes.windll.kernel32.SetPriorityClass(h, 0x00008000)  # ABOVE_NORMAL
                finally:
                    ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            pass
    else:
        try:
            os.nice(-5)
        except Exception:
            pass  # needs CAP_SYS_NICE; not fatal
    try:
        os.set_blocking(proc.stderr.fileno(), False)
    except Exception:
        pass
    return proc


class GPUStreamer:
    """Runs `ffmpeg -f lavfi -i ddagrab=... -c:v h264_nvenc -f h264 -` and
    yields encoded H.264 access units read from its stdout.

    Frames are delimited with the `h264_metadata=aud=insert` bitstream filter
    (an AUD NAL starts every access unit), so no CPU-side pixel work happens.
    """

    _START = b"\x00\x00\x01"

    def __init__(self, width, height, fps=30, gop=15, cq=18, preset="p1",
                 maxrate="40M", bufsize="80M", draw_mouse=True,
                 capture_w=None, capture_h=None, slices=1):
        if not _IS_WIN and is_wayland():
            _dbg("refusing to capture: " + session_type() + " session")
            raise RuntimeError(_WAYLAND_MSG)
        # 抗丢包分片数(>1 生效)。1 = 关闭(局域网无丢包时可省这点压缩开销)。
        # 仅 RTP 路径显式传 >1(server.py _rtp_start_streamer 读 config "slices");
        # TCP 不丢包用不上,多 slice 反而压低压缩效率、加大帧,故默认 1。
        self.slices = max(1, int(slices or 1))
        # 无 GPU 机器软编（libx264）CPU 吃不消原生分辨率。软编时自动降规格：
        # 分辨率缩到不超过软编上限（保持宽高比），帧率降到 soft fps。硬编
        # （NVENC/QSV）保持原生。soScale 记录是否降了分辨率，供上层查询。
        cap_w = capture_w or width
        cap_h = capture_h or height
        vf = None
        if _IS_WIN and (cap_w != width or cap_h != height):
            vf = f"hwdownload,format=bgra,scale={width}:{height}:flags=lanczos,format=nv12"
        # 探测编码器链，找到可用编码器。硬编复用探测进程（省一次启动）；
        # 软编需降规格，探测进程释放后再按降规格重启。
        enc_final, probe_proc = self._probe_encoder(vf, cap_w, cap_h, width, height,
                                                    draw_mouse, fps, cq, gop, maxrate, bufsize, preset,
                                                    self.slices)
        self._encoder = enc_final
        self.soScale = False
        need_restart = False
        if enc_final == "libx264":
            # 软编：分辨率缩到 soft 上限（保持宽高比），帧率降到 15 上限
            max_soft_w = 1280
            max_soft_h = 720
            soft_fps = 15
            if (width > max_soft_w or height > max_soft_h) and (width > 0 and height > 0):
                scale = min(float(max_soft_w) / width, float(max_soft_h) / height, 1.0)
                sw = max(160, int(width * scale // 2 * 2))
                sh = max(120, int(height * scale // 2 * 2))
                _dbg(f"soft encoder: downscaling {width}x{height} -> {sw}x{sh}")
                width, height = sw, sh
                self.soScale = True
                need_restart = True
            if fps > soft_fps:
                _dbg(f"soft encoder: fps {fps} -> {soft_fps}")
                fps = soft_fps
                need_restart = True
        self.width = width
        self.height = height
        # Snap to a whole divisor of the monitor refresh (e.g. 55 on a 165 Hz
        # panel instead of 60) so the capture cadence is steady; report the
        # actual fps via self.fps so the client paces correctly.
        self.fps = snap_fps(fps)
        # ddagrab captures a fixed region; when the requested output is smaller
        # than the desktop we must capture the native desktop and downscale,
        # otherwise the picture would be cropped. capture_w/h = native size.
        # vf already includes hwdownload (downscale from native when needed).
        if self.soScale and _IS_WIN:
            # 软编降规格：无论是否 wan_downscale，都要从原生缩到目标尺寸。
            # vf 已有 hwdownload+scale（若 wan_downscale）；否则补一个 scale。
            if vf is None:
                vf = f"hwdownload,format=bgra,scale={width}:{height}:flags=lanczos,format=nv12"
        # Queue depth is a jitter-tolerance tradeoff, not just a latency
        # bound: on overflow the dropped frame is a P-frame, which breaks the
        # reference chain — the decoder freezes until the next IDR (~1 GOP).
        # A frame count is the wrong unit: the same 16 frames is 290ms at
        # 55fps but 500ms at 32fps. Express the budget in time instead — 0.3s
        # reproduces the empirically safe 16 @55fps (8 overflowed during
        # mouse-motion bitrate bursts) and keeps 32fps at ~310ms.
        self._q = queue.Queue(maxsize=max(4, int(round(self.fps * 0.3))))
        self._pending = None
        self._stop = threading.Event()
        self._frame_nals = []
        self._frame_idr = False
        self.chain_broken = False
        self.produced = 0
        self.produced_bytes = 0
        self.dropped = 0
        self._proc = None
        self._err_buf = b""
        if need_restart:
            # 软编降规格：释放探测进程，按最终规格重启
            try:
                probe_proc.terminate()
                probe_proc.wait(timeout=2)
            except Exception:
                pass
            cmd = self._build_cmd(enc_final, vf, cap_w, cap_h, width, height,
                                  draw_mouse, fps, cq, gop, maxrate, bufsize, preset,
                                  self.slices)
            _dbg(f"restarting soft encoder at {width}x{height} fps={self.fps}")
            try:
                self._proc = _popen_ffmpeg(cmd)
            except OSError as e:
                raise RuntimeError(f"encoder {enc_final}: spawn failed ({e})")
        else:
            # 硬编：复用探测进程，零额外启动开销
            self._proc = probe_proc
            _dbg(f"reusing probe process (no restart)")
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._err_loop, daemon=True).start()
        # x11grab (Linux) produces frames on a fixed cadence even when the
        # desktop is static — the Win32 nudge window is only needed for
        # DXGI Desktop Duplication's change-driven delivery.
        self._nudge = _NudgeWindow() if _IS_WIN else None
        _dbg(f"started {width}x{height} fps={self.fps} maxrate={maxrate} slices={self.slices} encoder={self._encoder} pid={self._proc.pid}")

    def _probe_encoder(self, vf, cap_w, cap_h, width, height,
                       draw_mouse, fps, cq, gop, maxrate, bufsize, preset, slices=1):
        """探测编码器链，返回 (编码器名, 探测进程)。探测进程不终止——
        硬编复用为正式进程（省一次启动），软编由调用方决定是否重启降规格。"""
        self._err_buf = b""
        self._vaapi_dev = None
        for entry in self._encoder_chain():
            enc = entry[0]
            if enc == "h264_vaapi":
                self._vaapi_dev = entry[1]
            cmd = self._build_cmd(enc, vf, cap_w, cap_h, width, height,
                                  draw_mouse, fps, cq, gop, maxrate, bufsize, preset, slices)
            _dbg(f"trying encoder: {enc}" + (f" ({self._vaapi_dev})" if enc == "h264_vaapi" else ""))
            try:
                proc = _popen_ffmpeg(cmd)
            except OSError as e:
                _dbg(f"encoder {enc}: spawn failed ({e})")
                continue
            # 非阻塞探测：进程退出或 stderr 出现错误关键字都算失败。
            err_buf = b""
            failed = False
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                rc = proc.poll()
                if rc is not None:
                    err = proc.stderr.read(4096).decode("utf-8", "replace").strip()[:300]
                    _dbg(f"encoder {enc}: exited rc={rc} ({err})")
                    failed = True
                    break
                err_buf += self._drain_stderr(proc)
                if _ENC_ERROR_RE.search(err_buf):
                    _dbg(f"encoder {enc}: error in stderr ({err_buf[-200:].decode('utf-8','replace').strip()})")
                    failed = True
                    break
                time.sleep(0.02)
            if failed:
                try:
                    proc.kill()
                except Exception:
                    pass
                proc.wait(timeout=2)
                continue
            # 探测成功：进程保持运行，返回给调用方复用
            self._err_buf = err_buf + self._drain_stderr(proc)
            return enc, proc
        raise RuntimeError("no usable H.264 encoder (vaapi/nvenc/qsv/libx264 all failed)")

    def _encoder_chain(self):
        if not _IS_WIN:
            # one vaapi attempt per render device, then NVIDIA NVENC (when the
            # proprietary driver exposes it), then CPU fallback
            chain = [("h264_vaapi", d) for d in sorted(glob.glob("/dev/dri/renderD*"))]
            chain.append(("h264_nvenc", None))
            chain.append(("libx264", None))
            return chain
        return [("h264_nvenc", None), ("h264_amf", None), ("h264_qsv", None),
                ("libx264", None)]

    def _build_cmd(self, enc, vf, cap_w, cap_h, width, height,
                   draw_mouse, fps, cq, gop, maxrate, bufsize, preset, slices=1):
        # 分片编码:一帧拆成多个 slice,单个 RTP 包丢失只损坏一条 slice(其余行
        # 照常解码),不会整帧花/停。NVENC 再用 constrained-encoding 让 slice
        # 之间互不参考,把损坏限制在本 slice 内。vaapi/amf/qsv 未验证,不加。
        slices = max(1, int(slices or 1))
        slice_args = ["-slices", str(slices)] if slices > 1 else []
        if not _IS_WIN:
            disp = os.environ.get("DISPLAY", ":0")
            src = ["-f", "x11grab", "-framerate", str(fps),
                   "-video_size", f"{cap_w}x{cap_h}",
                   "-draw_mouse", "1" if draw_mouse else "0",
                   "-i", disp]
            scale = f"scale={width}:{height}:flags=lanczos," \
                if (cap_w != width or cap_h != height) else ""
            if enc == "h264_vaapi":
                # CQP constant quality maps DeskBeam's cq directly; -bf 0 and
                # forced IDR keep the GOP aligned like the NVENC path.
                # Explicit device: multi-GPU boxes must probe/lock the right
                # render node, not let ffmpeg guess.
                vf = f"{scale}format=nv12,hwupload"
                enc_args = ["-vaapi_device", self._vaapi_dev,
                            "-c:v", "h264_vaapi",
                            "-rc_mode", "CQP",
                            "-global_quality", str(cq),
                            "-bf", "0",
                            "-g", str(gop), "-profile:v", "main"]
            elif enc == "h264_nvenc":
                # NVENC reads CPU frames directly (internal copy to GPU);
                # same low-latency quality args as the Windows path.
                vf = f"{scale}format=nv12"
                enc_args = ["-c:v", "h264_nvenc",
                            "-preset", preset, "-tune", "ll", "-zerolatency", "1",
                            "-rc", "vbr", "-cq", str(cq), "-g", str(gop),
                            "-b:v", "0",
                            "-maxrate", maxrate, "-bufsize", bufsize,
                            "-profile:v", "main", "-bf", "0",
                            "-fflags", "nobuffer", "-flags", "low_delay"]
                if slices > 1:
                    enc_args += slice_args + ["-constrained-encoding", "1"]
            else:  # libx264
                vf = f"{scale}format=yuv420p"
                enc_args = ["-c:v", "libx264",
                            "-preset", "veryfast", "-tune", "zerolatency",
                            "-profile:v", "main", "-crf", str(cq),
                            "-g", str(gop)]
                if slices > 1:
                    enc_args += slice_args
            return ([FFMPEG_EXE, "-hide_banner", "-loglevel", "error"]
                    + src + ["-bsf:v", "h264_metadata=aud=insert"]
                    + ["-vf", vf] + enc_args + ["-f", "h264", "-"])
        if enc == "h264_amf":
            # AMF 吃不了 ddagrab 的 d3d11 硬件帧，先 hwdownload 再喂编码器。
            # lowlatency_high_quality 兼顾延迟与画质；cqp 恒定质量（cq 映射到
            # I/P 帧 QP），-bf 0 关 B 帧减延迟；-forced_idr 保证 GOP 对齐。
            vf = vf or "hwdownload,format=bgra,format=nv12"
            enc_args = [
                "-c:v", "h264_amf",
                "-usage", "lowlatency_high_quality",
                "-rc", "cqp", "-qp_i", str(cq), "-qp_p", str(cq),
                "-bf", "0", "-max_b_frames", "0",
                "-forced_idr", "1",
                "-g", str(gop),
                "-profile:v", "main",
            ]
        elif enc == "h264_qsv":
            # QSV 吃不了 ddagrab 的 d3d11 硬件帧，先 hwdownload 再喂编码器
            vf = vf or "hwdownload,format=bgra,format=nv12"
            # QSV 用 load_plugin=hw（Win 走 MF/兼容层），参数取低延迟风格
            enc_args = [
                "-c:v", "h264_qsv",
                "-preset", "veryfast",
                "-global_quality", str(cq),
                "-g", str(gop), "-bf", "0",
                "-profile:v", "main",
            ]
        elif enc == "libx264":
            # 软编吃不了 ddagrab 的 d3d11 硬件帧，必须 hwdownload 到 CPU 内存
            vf = vf or "hwdownload,format=bgra,format=nv12"
            enc_args = [
                "-c:v", "libx264",
                "-preset", "veryfast", "-tune", "zerolatency",
                "-profile:v", "main", "-crf", str(cq), "-g", str(gop),
            ]
            if slices > 1:
                enc_args += slice_args
        else:  # h264_nvenc
            enc_args = [
                "-c:v", enc,
                "-preset", preset, "-tune", "ll", "-zerolatency", "1",
                "-rc", "vbr", "-cq", str(cq), "-g", str(gop), "-b:v", "0",
                "-maxrate", maxrate, "-bufsize", bufsize,
                "-profile:v", "main", "-bf", "0",
                "-fflags", "nobuffer", "-flags", "low_delay",
            ]
            if slices > 1:
                enc_args += slice_args + ["-constrained-encoding", "1"]
        cmd = [
            FFMPEG_EXE, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"ddagrab=video_size={cap_w}x{cap_h}:framerate={fps}:draw_mouse={1 if draw_mouse else 0}:dup_frames=1",
            "-bsf:v", "h264_metadata=aud=insert",
        ]
        if vf:
            cmd += ["-vf", vf]
        cmd += enc_args + ["-f", "h264", "-"]
        return cmd

    def _drain_stderr(self, proc):
        """Non-blocking drain of a subprocess's stderr pipe. Returns bytes."""
        chunk = b""
        try:
            fd = proc.stderr.fileno()
            while True:
                try:
                    c = os.read(fd, 65536)
                except (OSError, BlockingIOError):
                    break
                if not c:
                    break
                chunk += c
        except Exception:
            pass
        return chunk

    def _err_loop(self):
        last_stats = 0.0
        last_produced = 0
        last_bytes = 0
        try:
            while not self._stop.is_set():
                chunk = self._drain_stderr(self._proc)
                if not chunk:
                    time.sleep(0.2)
                else:
                    for line in chunk.splitlines():
                        line = line.decode("utf-8", "replace").strip()
                        if line:
                            _dbg("stderr: " + line)
                # Periodic pipeline stats: distinguishes capture-side stalls
                # (produced rate drops; ddagrab missing presents under GPU
                # load) from client-side backpressure (dropped grows; the
                # WebSocket send cannot keep up with the network).
                now = time.monotonic()
                if now - last_stats >= 15:
                    dt = now - last_stats if last_stats else 0.0
                    rate = (self.produced - last_produced) / dt if dt else 0.0
                    kbps = (self.produced_bytes - last_bytes) * 8 / dt / 1000 if dt else 0.0
                    _dbg(f"stats: fps={rate:.1f} kbps={kbps:.0f} produced={self.produced} "
                         f"dropped={self.dropped} qsize={self._q.qsize()}")
                    last_stats, last_produced, last_bytes = now, self.produced, self.produced_bytes
        except Exception:
            pass

    # -- low level: read stdout, split NAL units, group into access units --
    @staticmethod
    def _find_start(buf, pos=0):
        i = buf.find(GPUStreamer._START, pos)
        if i == -1:
            return -1
        if i > 0 and buf[i - 1] == 0:  # 4-byte start code
            return i - 1
        return i

    def _read_loop(self):
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = self._proc.stdout.read(65536)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            buf = self._drain(buf)
        self._stop.set()

    def _drain(self, buf):
        frame_nals = self._frame_nals
        frame_idr = self._frame_idr
        while True:
            s = self._find_start(buf, 0)
            if s == -1:
                break
            s2 = self._find_start(buf, s + 3)
            if s2 == -1:
                break
            nal = buf[s:s2]
            buf = buf[s2:]
            if len(nal) < 5:
                continue
            sc4 = nal[:4] == b"\x00\x00\x00\x01"
            header = nal[4] if sc4 else nal[3]
            ntype = header & 0x1F
            if ntype == 9:  # AUD -> boundary between access units
                if frame_nals:
                    if self._q.full():
                        # keep the freshest frame: drop the oldest. That drop
                        # breaks the H.264 reference chain (surviving P-frames
                        # referenced the dropped one) — flag it so read() skips
                        # deltas until the next IDR instead of shipping corrupt
                        # frames (decoder artifacts until the natural IDR).
                        try:
                            self._q.get_nowait()
                            self.dropped += 1
                            self.chain_broken = True
                        except queue.Empty:
                            pass
                    payload = b"".join(frame_nals)
                    self._q.put((frame_idr, payload))
                    self.produced += 1
                    self.produced_bytes += len(payload)
                    frame_nals.clear()
                    frame_idr = False
                continue
            if ntype in (1, 5, 6, 7, 8):  # slices, SEI, SPS, PPS
                frame_nals.append(nal)
                if ntype == 5:
                    frame_idr = True
        self._frame_nals = frame_nals
        self._frame_idr = frame_idr
        return buf

    # -- public API --
    def first_frame(self, timeout=2.0):
        """Wait for the first access unit, nudging the desktop (tiny window
        flash) in the background in case it is static. The first access unit
        is kept for the next read()."""
        time.sleep(0.1)  # let the nudge window's message pump start
        start = time.monotonic()
        next_nudge = start
        while time.monotonic() - start < timeout:
            if self._proc.poll() is not None:
                _dbg(f"first_frame: proc exited rc={self._proc.returncode}")
                return False
            if self._nudge and time.monotonic() >= next_nudge:
                self._nudge.toggle(times=1, interval=0.4)
                next_nudge = time.monotonic() + 1.2
            try:
                self._pending = self._q.get(timeout=0.1)
                _dbg(f"first_frame: OK after {time.monotonic()-start:.2f}s")
                return True
            except queue.Empty:
                continue
        _dbg(f"first_frame: TIMEOUT {timeout}s")
        return False

    def read(self, timeout=0.2):
        """Return (is_idr, h264_access_unit) or None when nothing is ready.

        After a queue-overflow drop the reference chain is broken: intermediate
        deltas are discarded here (counted as dropped) and the stream restarts
        at the next IDR, so callers only ever see chain-safe frames."""
        while True:
            if self._pending is not None:
                item, self._pending = self._pending, None
            else:
                try:
                    item = self._q.get(timeout=timeout)
                except queue.Empty:
                    return None
            is_idr, data = item
            if self.chain_broken and not is_idr:
                self.dropped += 1
                continue
            if is_idr:
                self.chain_broken = False
            return item

    def alive(self):
        return self._proc.poll() is None

    def close(self):
        self._stop.set()
        if self._nudge:
            try:
                self._nudge.destroy()
            except Exception:
                pass
        rc = self._proc.poll()
        if rc is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        else:
            _dbg(f"close: ffmpeg already exited rc={rc}")
        try:
            err = self._proc.stderr.read(4096)
        except Exception:
            err = b""
        if err and err.strip():
            _dbg("close stderr: " + err.decode("utf-8", "replace").strip()[:300])
