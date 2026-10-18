"""Voice transcription: local WSL-based ASR or a remote API.

The local path shells out to a WSL python script that talks to a local
transcription server (127.0.0.1:8082). The online path posts the audio to a
configured OpenAI-style API. init() must be called once at startup with the
server config; transcription runs on a single-worker executor.
"""

import base64
import json
import re
import threading
import time
from pathlib import Path
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_cfg = {}
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")

_local_fail_ts = 0          # 上次本地 ASR 失败的时间(用于冷却)
_local_fails = 0            # 连续失败次数(用于退避:失败越多,冷却越久)
_asr_lock = threading.Lock()
_asr_cooldown = 10
LOCAL_URL = ""              # **生效**的地址:被开关关掉时为空
_local_cfg_url = ""         # 配置里写的地址(开关关掉也不丢,重新打开即恢复)
_local_enabled = True       # 运行期开关,持久化在 config.json 的 asr_local_enabled
LOCAL_FORMAT = "json"


def init(cfg):
    """Bind the server config (single source of truth). Call once at startup."""
    global _cfg, _asr_cooldown, LOCAL_URL, LOCAL_FORMAT, _local_cfg_url, _local_enabled
    _cfg = cfg
    _asr_cooldown = _int_cfg("asr_cooldown", 10)
    # 本地 ASR:走 HTTP API。服务跑在 WSL / Windows 本机 / 局域网另一台机器 / Docker
    # 都一样能用 —— 只要把它暴露成一个 HTTP 接口即可,不依赖 wsl.exe、也不解析 stdout。
    _local_cfg_url = (cfg.get("asr_local_url", "") or "").strip()
    LOCAL_FORMAT = (cfg.get("asr_local_format", "") or "json").strip().lower()
    # 运行期开关:默认开;config 里 asr_local_enabled=false 时关掉(但保留地址)
    _local_enabled = str(cfg.get("asr_local_enabled", True)).strip().lower() not in ("false", "0", "no", "off", "")
    LOCAL_URL = _local_cfg_url if _local_enabled else ""
    _local_fails = 0


def set_local_enabled(on):
    """运行期开关。关掉只是不碰本地,地址仍保留 -> 重新打开立刻恢复。"""
    global _local_enabled, LOCAL_URL, _local_fail_ts, _local_fails
    _local_enabled = bool(on)
    LOCAL_URL = _local_cfg_url if _local_enabled else ""
    _local_fail_ts = 0
    _local_fails = 0
    return _local_enabled


def is_local_enabled():
    return bool(_local_enabled)


def _int_cfg(key, default=0):
    try:
        return int(_cfg[key])
    except (KeyError, ValueError, TypeError):
        return default


def transcribe(wav_path):
    """识别入口。**本地优先,失败回退在线。**

    1. asr_local_url  -> 本地/局域网的 ASR HTTP 服务(快、免费、私密)
       失败后按 asr_cooldown 冷却,冷却期内直接跳过,免得每句话都白等一次超时。
    2. asr_api_url + asr_api_key -> 在线 API(OpenAI 风格)
    3. 都不行 -> 空字符串(调用方按"没识别出内容"处理)
    """
    global _local_fail_ts, _local_fails
    if _local_enabled:
        # **只用本地,不兜底在线。**
        # 有开关还兜底,等于开关失效:本地挂了会悄悄走在线,用户以为在用本地,
        # 既发现不了问题、又在花在线 API 的钱(用户明确提过这个担心)。
        # 所以两者彻底隔离:选了哪个就只用哪个,用不了就返回空(什么都不输入)。
        if not LOCAL_URL:
            return ""
        # 退避:连续失败时冷却翻倍(60 -> 120 -> 240 -> 480 -> 900 封顶),
        # 本地挂了就不必每句话都白等一次超时;成功一次立刻复位。
        cd = min(_asr_cooldown * (2 ** max(0, _local_fails - 1)), 900)
        if (time.time() - _local_fail_ts) < cd:
            return ""                     # 冷却期内:这次语音就当作没识别出来
        text = _transcribe_local_http(wav_path)
        if text:
            _local_fail_ts = 0
            _local_fails = 0
            return text
        _local_fail_ts = time.time()
        _local_fails += 1
        return ""                         # 本地失败 -> 空,绝不回退在线
    # **只用在线**
    api_url = _cfg.get("asr_api_url", "").strip()
    api_key = _cfg.get("asr_api_key", "").strip()
    if api_url and api_key:
        return _transcribe_online(wav_path, api_url, api_key)
    return ""


def _transcribe_online(wav_path, url, key):
    # 接受 Path 和 str 两种类型 —— _transcribe_local_http 用 open() 两者都行,
    # 这里原来只能 Path,类型不一致容易在别的调用点炸。
    wav_data = Path(wav_path).read_bytes()
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
        # 8s:实测真实一次识别(3 秒音频)约 2.2s,8s 足够;原来 20s 会让
        # 『服务收下连接但不回』这种最坏情况卡住 20 秒(视频不卡,但用户看不到任何反应)。
        resp = urllib.request.urlopen(req, timeout=8)
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


# 本地模型(如 MTD)的输出会内联时间戳/说话人标记。这些是要打字的正文的一部分吗?
# 不是 —— 它们是给人看的元信息,留着会被原样输入到电脑上。这里清掉。
#
# 只清**确凿是元信息**的形式,避免误删正文:
#   [1.23] [S1]                  asr.py L67 同款(MTD 内联标签)
#   [00:01.230 --> 00:00:02.5]   SRT 时间轴
#   [00:01] (00:01.2)            短时间戳
#   说话人1: 演讲者2：SPEAKER_00:   说话人前缀
# "[重要]" "(注意)" 这类不含冒号的不会被误删。
_ASR_TAG_RES = [
    re.compile(r"\[\d+\.?\d*\]"),
    re.compile(r"\[S\d+\]"),
    re.compile(r"\[\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*-->[^\]]*\]"),
    re.compile(r"[\[\(]\s*\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*[\]\)]"),
    re.compile(r"(?:说话人|演讲者|SPEAKER|Speaker)[\s_-]*\d*\s*[:：]\s*", re.I),
    re.compile(r"^\s*(?:说话人|演讲者|SPEAKER|Speaker)[\s_-]*\d*\s*$", re.I),
]


def _strip_asr_tags(s):
    """去掉本地 ASR 输出里的时间戳/说话人标记;对干净文本是恒等变换。"""
    for rx in _ASR_TAG_RES:
        s = rx.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _transcribe_local_http(wav_path):
    """直接调 ASR 服务的 HTTP 接口(不经 wsl.exe,因此与平台无关)。

    两种方言,由 config `asr_local_format` 选:

      json    MTD 这套服务的接口(与 asr.py 一致):
              POST {asr_local_url}/v1/audio/transcriptions
              {"audio": "<base64>", "timestamp": false}  ->  {"text": "..."}
      openai  OpenAI 兼容接口(multipart):
              POST {asr_local_url}/v1/audio/transcriptions
              file=@x.wav, model=<asr_api_model>          ->  {"text": "..."}
              覆盖 faster-whisper-server / LocalAI / speaches 等现成实现。

    失败时按 asr_cooldown 冷却,避免每句话都白等一次超时。"""
    url = LOCAL_URL.rstrip("/")
    if not url.endswith("/v1/audio/transcriptions"):
        url = url + "/v1/audio/transcriptions"
    try:
        with open(wav_path, "rb") as f:
            raw = f.read()
        if LOCAL_FORMAT == "openai":
            boundary = "----deskbeam" + str(int(time.time() * 1000))
            model = (_cfg.get("asr_api_model", "") or "whisper-1").strip()
            parts = []
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n".encode())
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\n"
                         f"Content-Type: audio/wav\r\n\r\n".encode())
            parts.append(raw)
            parts.append(f"\r\n--{boundary}--\r\n".encode())
            body = b"".join(parts)
            ctype = f"multipart/form-data; boundary={boundary}"
        else:
            body = json.dumps({"audio": base64.b64encode(raw).decode(), "timestamp": False}).encode()
            ctype = "application/json"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        text = str(data.get("text", "") or "").strip()
        # 有些实现会把时间戳/说话人内联在 text 里(MTD 就是),这里再保险滤一次
        out = []
        for line in text.split("\n"):
            line = _strip_asr_tags(line)
            if line:
                out.append(line)
        return " ".join(out).strip()
    except Exception as e:
        print(f"  local ASR http failed: {type(e).__name__}: {e}")
        return ""


