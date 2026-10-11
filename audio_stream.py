"""PC 音频采集(WASAPI 回环) -> aiortc 音频轨。

当前只在 **RTP/UDP 路径**上启用。TCP 路径的视频是应用层 H.264 over WebSocket,
没有音频通道 —— 要加就得在浏览器里重建一套 WebCodecs AudioDecoder + 抖动缓冲
+ 音画对齐,等于把 WebRTC 已经做好的事重做一遍。所以音频目前是 UDP 专属能力
(WAN/Tailscale/移动端自动走 UDP)。

设计要点(全部来自 Piik 的实测经验,见 docs/HISTORY.md 的"音画同步"一节):

* **20ms 固定节拍**:一个 48kHz 立体声 s16 帧 = 960 样本。由 recv() 自己按真实
  时间配速,不能读到就发 —— 那会灌爆发送端(实测没有配速时音频跑到 1150fps)。
* **有界丢弃队列**:采集线程只保留最近 4 帧(80ms),满了丢最旧的。积压的旧声音
  重放出来比丢掉更糟(会越拖越迟)。
* **饥饿时补静音并推进时间轴**:采不到就发静音,RTP 时间戳照常前进,绝不把旧
  音频挤成一串突发。
* **时间戳锚定单调时钟**:与 rtp_stream 的视频时钟同一套规则,否则音画会随丢帧
  持续错开(实测帧计数时钟下 3.3s 未交付 → 3277ms 偏移)。
* **可选能力**:采集失败/依赖缺失一律返回 None,视频不受影响(音频永远不能拖垮
  视频)。

依赖 PyAudioWPatch(仅 Windows,提供 WASAPI loopback);缺失时本模块可用但
start_audio_track() 返回 None。
"""
import asyncio
import fractions
import math as _math
import threading
import time

AFRAME = 960          # 20ms @ 48kHz
ARATE = 48000
ACH = 2
NEED = AFRAME * ACH * 2      # 每帧字节数(s16 立体声)
# 上限 20 帧 = 400ms,纯粹是**安全阀**:稳态下队列会排空(实测残留 0),只有
# 视频管线造成的瞬态堆积才会用到它。实测瞬态峰值 ~16 帧,所以 20 帧可以做到
# 0 丢帧;设 8 帧会丢 1.8%(每丢一帧就是 20ms 的音频空洞,听感是零星咔哒)。
MAXBUF = NEED * 20
MAXQ = 20                   # 投递给事件循环的帧队列上限,与 MAXBUF 同量级


class LoopbackCapture:
    """WASAPI 回环采集。read() 在后台线程里跑,数据进有界字节缓冲。"""

    def __init__(self):
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._closing = False       # close() 开始后禁止 _reopen 再动底层流
        self._thread = None
        self._pa = None
        self._stream = None
        self.device = ""
        self.device_index = -1
        self.dev_rate = 0
        self._dev_ch = ACH
        self._chunk = AFRAME
        self.last_error = ""
        self.overruns = 0          # 缓冲满被丢弃的帧数
        self.reopens = 0           # 因设备切换/流失效重开的次数
        self.on_device = None      # 设备变化回调(采集线程调用)
        self._loop = None          # 事件循环(attach 后设置)
        self._aq = None            # 投递队列

    # -- 生命周期 --
    def start(self):
        import pyaudiowpatch as pyaudio
        import numpy as np  # noqa: F401  (失败要早暴露)

        self._pa = pyaudio.PyAudio()
        self._open_stream()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        return self

    def _open_stream(self):
        """按当前默认渲染端点打开回环流。设备被切换/拔出后必须重开。"""
        import pyaudiowpatch as pyaudio

        dev = self._pa.get_default_wasapi_loopback()
        self.device = str(dev.get("name", ""))
        self.device_index = dev["index"]
        self.dev_rate = int(dev.get("defaultSampleRate") or ARATE)
        self._dev_ch = int(dev.get("maxInputChannels") or ACH)
        self._chunk = max(64, int(self.dev_rate * 0.02))
        self._stream = self._pa.open(
            format=pyaudio.paInt16, channels=self._dev_ch, rate=self.dev_rate,
            input=True, input_device_index=self.device_index,
            frames_per_buffer=self._chunk)

    def _close_stream(self):
        st, self._stream = self._stream, None
        if st is not None:
            try:
                st.stop_stream()
            except Exception:
                pass
            try:
                st.close()
            except Exception:
                pass

    def _reopen(self):
        """换设备/流失效后重开采集。

        Windows 切换默认播放设备时,原来的 WASAPI 回环流会被失效;继续对一个
        失效的流反复 read() 实测会把进程拖进 C 层崩溃(设备切换后 DeskBeam
        自动重启过一次,server.log 里没有任何 Python traceback)。所以这里
        主动重开,而不是无限重试。
        """
        if self._closing:
            return False
        old = self.device
        self._close_stream()
        try:
            self._open_stream()
        except Exception as e:
            self.last_error = repr(e)
            self.device = old
            self.device_index = -1  # invalidate so the 0.5s device poll retries
            return False
        with self._lock:
            del self._buf[:]              # 设备变了,旧采样丢弃,别拼接出怪声
        self.reopens += 1
        print(f"  RTP audio: capture reopened -> '{self.device}' @ {self.dev_rate}Hz")
        cb = self.on_device
        if cb is not None:
            try:
                cb(self.device)
            except Exception:
                pass
        return True

    def close(self):
        """关采集。**顺序很重要**,这里的并发曾经把整个进程带走。

        实测(UDP -> TCP 切传输时,daemon.log + 事件日志):
        `DeskBeam exited (code -1073741819 (0xC0000005 访问违例))`,
        `出错模块名称: AUDIOSES.DLL`。原因是原来的 close() 只 join(timeout=1.0),
        而采集线程很可能正阻塞在 stream.read() 里;1 秒后主线程就 stop_stream /
        close / pa.terminate(),等于在 PortAudio 正在使用的对象上做释放 ——
        典型的 use-after-free。

        正确顺序:
          ① 置 _closing,阻止 _reopen 再动流;
          ② 置 _stop 后先 stop_stream(),让阻塞中的 read() 立刻返回;
          ③ 再 join;
          ④ **只有线程确实退出了**才 close 流并 terminate PortAudio。
        第 ④ 步的取舍是刻意的:线程没退出时宁可泄漏一个流(以及一个 PortAudio
        实例),也不要冒访问违例的风险 —— 崩掉的是整个服务,视频会一起没。
        """
        self._closing = True
        self._stop.set()
        st = self._stream
        if st is not None:
            try:
                st.stop_stream()
            except Exception:
                pass
        t = self._thread
        if t is not None:
            t.join(timeout=2.0)
        if t is not None and t.is_alive():
            self.last_error = "close: reader thread still alive; stream leaked"
            self._stream = None
            self._thread = None
            return
        self._close_stream()
        try:
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass
        self._pa = None

    # -- 采集线程 --
    def _reader(self):
        import numpy as np

        fails = 0
        next_check = time.monotonic() + 0.5
        while not self._stop.is_set():
            # 主动检测默认播放设备变化(每 ~0.5s 一次,开销可忽略)。
            now = time.monotonic()
            if now >= next_check:
                next_check = now + 0.5
                try:
                    if self._pa.get_default_wasapi_loopback()["index"] != self.device_index:
                        if self._reopen():
                            fails = 0
                except Exception:
                    pass
            if self._stream is None:
                time.sleep(0.05)
                continue
            try:
                raw = self._stream.read(self._chunk, exception_on_overflow=False)
                fails = 0
            except Exception as e:
                self.last_error = repr(e)
                fails += 1
                if fails >= 3:
                    # 流已失效(设备换/被拔):关掉重开,不要对死流无限重试。
                    self._reopen()
                    fails = 0
                time.sleep(0.05)
                continue
            a = np.frombuffer(raw, dtype=np.int16)
            if self._dev_ch > 1:
                a = a.reshape(-1, self._dev_ch)
            else:
                a = a.reshape(-1, 1)
            if a.shape[1] == 1:
                a = np.repeat(a, 2, axis=1)          # 单声道 -> 立体声
            elif a.shape[1] > 2:
                a = a[:, :2]                          # 多声道取前两路
            if self.dev_rate != ARATE:
                # 线性重采样到 48kHz。默认端点通常是 48k,这条只是兜底。
                n_out = max(1, int(round(a.shape[0] * ARATE / self.dev_rate)))
                src = np.arange(a.shape[0], dtype=np.float64)
                dst = np.linspace(0, a.shape[0] - 1, n_out)
                a = np.stack([np.interp(dst, src, a[:, c].astype(np.float64))
                              for c in range(2)], axis=1).astype(np.int16)
            data = a.astype(np.int16).tobytes()
            with self._lock:
                self._buf += data
                if len(self._buf) > MAXBUF:
                    drop = len(self._buf) - MAXBUF
                    drop -= drop % NEED               # 整帧丢弃,别切碎样本
                    if drop > 0:
                        del self._buf[:drop]
                        self.overruns += drop // NEED
            # 整帧直接投递给事件循环。**不要**让消费端每帧跑一次
            # run_in_executor:那样消费速率跟不上生产,队列会稳定增长到撞上限丢帧。
            loop = self._loop
            while loop is not None and len(self._buf) >= NEED:
                with self._lock:
                    if len(self._buf) < NEED:
                        break
                    frame = bytes(self._buf[:NEED])
                    del self._buf[:NEED]
                try:
                    loop.call_soon_threadsafe(self._offer, frame)
                except RuntimeError:
                    with self._lock:
                        self._buf[:0] = frame      # 循环已关,放回去
                    break

    def attach(self, loop, aq):
        """把事件循环与投递队列交给采集线程(只调一次)。"""
        with self._lock:
            self._loop = loop
            self._aq = aq

    def _offer(self, frame):
        """在事件循环线程上执行:入队,满了丢最旧。"""
        aq = self._aq
        if aq is None:
            return
        try:
            aq.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                aq.get_nowait()
                self.overruns += 1
                aq.put_nowait(frame)
            except Exception:
                pass

    def flush(self):
        """丢弃当前积压,不计数。

        采集在 RTPVideoTransport 构造时就启动了,而 offer/ICE 协商期间没人消费,
        那 ~1 秒里积压的帧会在队列满时被当"溢出"丢掉。那段音频本来也不属于任何
        一个已建立的会话,首帧消费前直接清掉即可。"""
        with self._lock:
            del self._buf[:]


def available():
    """能否采到系统声音。不抛异常。"""
    try:
        import pyaudiowpatch  # noqa: F401
        return True
    except Exception:
        return False


def db_to_gain(db):
    try:
        db = float(db)
    except (TypeError, ValueError):
        return 1.0
    db = max(-24.0, min(24.0, db))
    return 10.0 ** (db / 20.0)


def frame_rms(data):
    """一帧 s16 的 RMS(用 float64 算,int16 平方会溢出)。"""
    import numpy as np

    a = np.frombuffer(data, dtype=np.int16)
    if a.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))


# ── 自动增益(AGC)──────────────────────────────────────────────────────
# 目的:抹平不同播放设备之间巨大的回环电平差 —— 实测 H180(USB 耳机)采集峰值
# 17601,而 P27QBD(NVIDIA HDMI)只有 889,差约 26dB,固定增益没法同时照顾两边。
#
# **分工是这里最关键的设计**:AGC 只做**慢速的平均电平归一化**,峰值/瞬态保护
# 交给 apply_gain 的软限幅。这样:
#   * 不需要让 AGC 去追每一个瞬态(那会产生抽吸感),也不会把峰值推爆;
#   * AGC 甚至可以慢到 7.5dB/s,因为爆音有软限幅兜着。
#
# 防止"拉太高导致失真"的四道闸:
#   ① 目标定在 -22dBFS(不是 0dBFS),给峰值留约 10dB 余量,基本不碰软限幅;
#   ② 增益上限 +24dB,不把极小的信号连底噪一起拉起来;
#   ③ 静音门限:输入 RMS 低于门限时**冻结**增益,不放大底噪;
#   ④ 减小快(75dB/s)、增大慢(7.5dB/s):前者防突发爆音,后者防"呼吸"。
AGC_TARGET_RMS = 7000.0        # ≈ -13 dBFS。2600(-22dBFS)实测偏轻;再高就要开始
                               # 明显碰软限幅了(见下面 set_agc_target 的说明)
AGC_GATE_RMS = 70.0            # ≈ -53 dBFS,低于此视为静音
AGC_MAX_DB = 36.0              # 要够大:P27QBD 那种极轻的设备需要 +25dB 以上
AGC_MIN_DB = -18.0
AGC_UP_DB_PER_S = 7.5          # 增大(变响)要慢,否则会抽吸
AGC_DOWN_DB_PER_S = 75.0       # 减小(变轻)要快,突发大音量才压得住
AGC_RMS_TAU = 0.15             # 电平平滑时间常数(s)


def set_agc_target(rms):
    """覆盖 AGC 的目标平均电平(config `audio_agc_target`,单位 RMS 计数)。

    这是"够不够响"和"会不会失真"之间的那个旋钮,因人而异:
      * 2600(-22dBFS):实测用户觉得偏轻,手机要开到最大;
      * 7000(-13dBFS):默认值,对典型节目(峰值因数 12~16dB)峰值大致落在
        -1~-5dBFS,基本不碰 24000 的软限幅拐点;
      * 12000 以上:峰值会持续压在软限幅上 —— 听着更响,但那就是失真。
    旧版本 H180 上那个"正好"的固定 +12dB,输出 RMS 约 27700(高于满量程均方根),
    等于限幅器一直在工作,正是这里要避免的。
    """
    global AGC_TARGET_RMS
    try:
        v = float(rms)
    except (TypeError, ValueError):
        return AGC_TARGET_RMS
    AGC_TARGET_RMS = max(500.0, min(20000.0, v))
    return AGC_TARGET_RMS


class Agc:
    """把平均电平缓慢归一化到 AGC_TARGET_RMS。thread-safe 不需要:只在 recv()
    里调用,那是单线程的。"""

    def __init__(self, start_db=0.0, frame_s=AFRAME / float(ARATE)):
        self.db = max(AGC_MIN_DB, min(AGC_MAX_DB, float(start_db)))
        self.gain = 10.0 ** (self.db / 20.0)
        self.level = 0.0                     # 平滑后的输入 RMS(诊断用)
        self._frame_s = frame_s
        self._k = 1.0 - _math.exp(-frame_s / AGC_RMS_TAU)

    def update(self, data):
        """按这一帧更新增益并返回它。静音时保持原增益。"""
        self.level += (frame_rms(data) - self.level) * self._k
        if self.level < AGC_GATE_RMS:
            return self.gain                  # 静音/极轻:冻结,不拉底噪
        want = 20.0 * _math.log10(AGC_TARGET_RMS / max(self.level, 1.0))
        want = max(AGC_MIN_DB, min(AGC_MAX_DB, want))
        if want < self.db:
            step = AGC_DOWN_DB_PER_S * self._frame_s
        else:
            step = AGC_UP_DB_PER_S * self._frame_s
        self.db = want if abs(want - self.db) <= step else (
            self.db + step if want > self.db else self.db - step)
        self.gain = 10.0 ** (self.db / 20.0)
        return self.gain


def apply_gain(data, gain):
    """对一帧 s16 PCM 施加数字增益,带**软拐点限幅**。

    手机端要把音量拉满才勉强听得见,说明回环采到的电平本身偏低;Opus 是有损的,
    提高码率并不能把电平抬起来,只能在编码前做数字增益(解码后再放大等于同时
    放大量化噪声,质量更差)。

    增益拉大后**不要**硬削波——那会产生刺耳的谐波失真。这里在 ~73% 满量程处
    起软拐点,超出部分用 tanh 压缩到满量程:小信号完全线性,大信号被压住。
    """
    if gain == 1.0:
        return data
    import numpy as np
    a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    a *= gain
    knee = 24000.0
    over = np.abs(a) > knee
    if over.any():
        mag = np.abs(a[over])
        a[over] = np.sign(a[over]) * (
            knee + (32767.0 - knee) * np.tanh((mag - knee) / (32767.0 - knee)))
    return np.clip(a, -32768.0, 32767.0).astype(np.int16).tobytes()


# aiortc 的 OpusEncoder 是它自己 new 出来的,没有参数通道,所以这里打一次
# 模块级补丁。只打一次,重复调用只更新目标码率。
_OPUS_BITRATE = 128000
_OPUS_PATCHED = False


def apply_opus_params(bitrate=128000):
    """把 aiortc 的 Opus 编码器改成适合**系统声音**的参数。

    aiortc 默认 `bit_rate = 96000` 且 `application = "voip"`。voip 是给语音
    清晰度做的优化,放到音乐/游戏/视频上会明显发闷、失真 —— 系统声音应该用
    `application = "audio"`。顺带让 config `audio_bitrate` 真正生效(此前那个
    配置项是空转的:值传进来了却没人用)。

    进程级生效,返回实际使用的码率。
    """
    global _OPUS_BITRATE, _OPUS_PATCHED
    try:
        _OPUS_BITRATE = max(16000, min(510000, int(bitrate or 128000)))
    except (TypeError, ValueError):
        _OPUS_BITRATE = 128000
    if _OPUS_PATCHED:
        return _OPUS_BITRATE
    try:
        from aiortc.codecs import opus
    except Exception as e:
        print(f"  RTP audio: opus patch skipped ({e!r})")
        return _OPUS_BITRATE

    _orig_init = opus.OpusEncoder.__init__

    def _init(self):
        _orig_init(self)
        try:
            self.codec.bit_rate = _OPUS_BITRATE
            # PyAV 的 options 在首次 encode 打开编码器时才生效,这里设置有效。
            self.codec.options = {"application": "audio"}
        except Exception:
            pass

    opus.OpusEncoder.__init__ = _init
    _OPUS_PATCHED = True
    return _OPUS_BITRATE


def start_audio_track(cfg=None, on_device=None):
    """按 config 起一条音频轨。任何失败都返回 None(视频照常)。

    on_device: 采集设备变化时的回调(在采集线程里调用),上层用来把新的设备名
    推给客户端 —— 否则界面会一直显示旧设备名。
    """
    cfg = cfg or {}
    br = apply_opus_params(cfg.get("bitrate", 128000))
    gain = db_to_gain(cfg.get("gain_db", 0))
    if cfg.get("target_rms"):
        set_agc_target(cfg.get("target_rms"))
    cap = None
    try:
        cap = LoopbackCapture().start()
    except Exception as e:
        print(f"  RTP audio: capture unavailable ({e!r})")
        try:
            if cap is not None:
                cap.close()
        except Exception:
            pass
        return None
    cap.on_device = on_device
    track = PCMStreamTrack(cap)
    track.gain = gain
    if cfg.get("agc"):
        # 起始增益**不超过 0dB**:AGC 要 0.16s 才能把增益降下来,而从 +12dB 起步会
        # 在这 0.16s 里把已经偏响的设备顶到软限幅上(实测 H180 峰值冲到 32371),
        # 听感是一声短促的爆音。宁可开头几秒偏轻(轻设备 7.5dB/s 爬上去,约 3.5s
        # 到 +27dB),也不要爆音。
        track.enable_agc(min(float(cfg.get("gain_db", 0) or 0), 0.0))
    print(f"  RTP audio: loopback '{cap.device}' @ {cap.dev_rate}Hz -> "
          f"Opus {br // 1000}kbps application=audio "
          + (f"AGC (start {cfg.get('gain_db', 0)}dB, target RMS {AGC_TARGET_RMS:.0f})"
             if track._agc is not None
             else f"gain {cfg.get('gain_db', 0)}dB (x{gain:.2f})"))
    return track


def _import_aiortc():
    from aiortc import MediaStreamTrack
    return MediaStreamTrack


try:
    _Base = _import_aiortc()
except Exception:                                     # aiortc 缺失也不能 import 失败
    _Base = object


class PCMStreamTrack(_Base):
    """把回环 PCM 按 20ms 节拍喂给 aiortc(由它编码成 Opus)。

    两条硬规则,都是踩过坑才立起来的:

    * **节奏由采集时钟驱动**,不是 sleep 定时。WASAPI 按硬件时钟出样本,
      recv() 阻塞等采集线程唤醒即可;用 asyncio.sleep(20ms) 在 Windows 上会
      退化成 31/15/32ms 交替。
    * **RTP 时间戳 = 已发送样本数**,每包严格 +960。音频不能用墙上时钟算
      pts(那会把上面的抖动写进时间戳),否则浏览器 NetEq 会做时间伸缩对齐,
      听感是"加速/断续/不平滑"。这里也**不做严格单调夹取**——那正是把抖动
      变成 "+1 步进"的元凶。
    """

    kind = "audio"

    def __init__(self, cap):
        try:
            super().__init__()
        except Exception:
            pass
        self._cap = cap
        # 采集设备名(暴露给上层塞进 screen_config,客户端显示在按钮提示里 ——
        # "没声音"最常见的原因就是采到的不是你正在用的那个输出设备)。
        self.device = getattr(cap, "device", "")
        self._nsamples = 0        # 已发送样本数 = 音频媒体的唯一时钟
        self.delivered = 0
        self.silence = 0
        self.gain = 1.0           # 固定数字增益(编码前),见 apply_gain
        self._agc = None          # 打开自动增益时用它替代 self.gain
        self._agc_n = 0
        self._aq = None
        self._loop = None

    def enable_agc(self, start_db=0.0):
        """开自动增益。start_db 是起始增益(一般取 config audio_gain_db)。"""
        self._agc = Agc(start_db)
        return self._agc

    def stop(self):
        try:
            super().stop()
        except Exception:
            pass
        try:
            self._cap.close()
        except Exception:
            pass

    async def recv(self):
        import av

        if self._aq is None:
            self._loop = asyncio.get_running_loop()
            self._aq = asyncio.Queue(maxsize=MAXQ)
            self._due = None                     # 补静音的 20ms 节拍锚点(见下)
            # 第一次被消费:丢掉协商期间积压的启动瞬态(见 LoopbackCapture.flush)
            self._cap.flush()
            self._cap.attach(self._loop, self._aq)

        # 补静音的节拍必须按**计划表**推进,不能用一个固定超时。
        # 原来这里是 wait_for(self._aq.get(), 0.4):采集一旦饿死,每 0.4s 才吐出
        # 一帧 20ms 静音 —— 包率塌到 **2.5 包/秒**。实测(手机端真会话):
        #     电脑无声   -> 音收 2-3/s(就是 1/0.4),音缓一路涨到 3s+ 且音画失步
        #     电脑放音乐 -> 音收 50/s、音出 ~48000 样本/s、音缓从 3700ms 降到 1000ms
        # 即 WASAPI 渲染端点空闲时回环根本不供数,而我们把它当成了"没有声音"而不是
        # "没有节拍",于是时间轴照走、包却几乎不发,接收端 NetEq 长期饥饿。
        #
        # **不能简单把 0.4 改小**:Windows 定时器精度 ~15.6ms,直接等 20ms 会退化成
        # 15/31ms 交替,平均包率可能偏**快** —— 那就变成媒体时钟跑在真实时间前面,
        # 正是 AGENTS.md 警告过的那类问题。改成"每帧把 _due 推进 20ms、只等到 _due",
        # 平均严格 50 帧/秒,定时器量化只贡献小抖动。
        # **pts = 已发送样本数、严格 +960 的不变量不变。**
        now = time.monotonic()
        if self._due is None or now - self._due > 0.5:
            self._due = now                      # 首次,或落后太多:重新对齐
        wait = self._due - now
        if wait > 0:
            try:
                data = await asyncio.wait_for(self._aq.get(), wait)
            except asyncio.TimeoutError:
                data = None
        else:
            try:
                data = self._aq.get_nowait()
            except asyncio.QueueEmpty:
                data = None
        self._due += AFRAME / ARATE              # 每帧严格推进 20ms
        if data is None:
            self.silence += 1
            data = b"\x00" * NEED
            out = data                      # 全零,不必过增益(省一次 numpy 往返)
        else:
            self.delivered += 1
            if self._agc is not None:
                out = apply_gain(data, self._agc.update(data))
                self._agc_n += 1
                if self._agc_n % 500 == 0:   # 每 10s 记一次,便于确认收敛值
                    print(f"  RTP agc: {self._agc.db:+.1f} dB "
                          f"(in RMS {self._agc.level:.0f})")
            else:
                out = apply_gain(data, self.gain)

        frame = av.AudioFrame(format="s16", layout="stereo", samples=AFRAME)
        frame.sample_rate = ARATE
        frame.planes[0].update(out)
        frame.pts = self._nsamples
        frame.time_base = fractions.Fraction(1, ARATE)
        self._nsamples += AFRAME      # 送出的样本数,严格 +960
        return frame
