"""WebRTC RTP video transport for pre-encoded NVENC H.264.

Unlike the old WebRTC experiment (DataChannel over SCTP), this path feeds the
already-NVENC-encoded access units straight into aiortc's RTP packetizer via
H264Encoder.pack(), avoiding SCTP entirely: the stream goes out as standard
RTP video on UDP, and the browser plays it through RTCRtpReceiver -> VideoDecoder
with browser-native NACK retransmission and keyframe (PLI) recovery.

Server side of the WebRTC offer/answer + ICE signaling is handled by the caller
over the existing /ws WebSocket; only the encoded H.264 travels over RTP/UDP.
"""

import asyncio
import fractions
import json
import time

import av
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCRtpCodecCapability


def apply_packet_mtu(mtu=0):
    """调小 aiortc H264 打包器的单包 RTP payload 上限(默认 1300)。

    线上包 = payload + 20(IPv4) + 8(UDP) + 12(RTP) + 10(SRTP tag) + 头部扩展
    ≈ payload + 50~70。aiortc 默认 1300 放出约 1350~1370B,而 Tailscale /
    WireGuard 的内层 MTU 是 1280-60=1220(且桌面 MTU 1280 更小),于是**每个
    视频包都被 IP 分片**:包数翻倍,且丢一个分片等于丢整包(重传窗口随之吃紧)。

    默认 1100 给 RTP 头部扩展留出余量,线上一包 ≈1100+50~70 = 1150~1170,
    在 Tailscale 与常规 1500 MTU 链路上都不分片。局域网想省包数可调高
    (例如 1300 恢复 aiortc 默认行为;普通以太网 MTU 1500 下 1400 也安全)。

    这是**进程级**改动(打的是 aiortc.codecs.h264 的模块全局),同时覆盖
    RTP 主路径与老浏览器 WebRTC 兜底路径。mtu<=0 表示不动。
    """
    if not mtu or int(mtu) <= 0:
        return 0
    try:
        from aiortc.codecs import h264
        old = h264.PACKET_MAX
        h264.PACKET_MAX = max(400, int(mtu))
        print(f"  RTP MTU: H264 packet max {old} -> {h264.PACKET_MAX} bytes")
        return h264.PACKET_MAX
    except Exception as e:
        print(f"  RTP MTU patch failed: {e!r}")
        return 0


class _Pacer:
    """Virtual-clock token bucket to smooth RTP micro-bursts (one frame is
    packetized into ~90+ packets which aiortc emits in one tight loop).

    A per-packet `sleep(deficit)` is wrong on Windows: the default timer
    resolution is ~15.6ms, so every small sleep rounds up and the stream ends
    up throttled *below* target (measured 2.0 Mbps -> 1.16). Instead we keep a
    virtual "due" time: send while we are behind it, sleep only when clearly
    ahead. Sleep overshoot is then repaid by the next packets going out
    immediately, so the long-run rate stays accurate.

    NOTE: pacing below what a frame needs to fit its frame interval will STARVE
    the sender and add latency, so the target must exceed the encoder's actual
    output rate — hence opt-in (config rtp_pacer_mbps, 0 = off)."""

    def __init__(self, bps, burst_s=0.02):
        self.per_byte = 1.0 / max(1.0, float(bps) / 8.0)
        self.burst_s = burst_s
        self.due = None

    def set_bps(self, bps):
        """运行期改目标速率(档位变化时由上层调用)。已排定的 due 不动,所以
        降档时不会把已经在途的包倒扣,只是后续包按新速率计入。"""
        self.per_byte = 1.0 / max(1.0, float(bps) / 8.0)

    async def wait(self, nbytes):
        now = time.monotonic()
        if self.due is None:
            self.due = now
        elif now - self.due > self.burst_s:
            # 空闲后重新开始:积攒的额度最多只到 burst_s,不无限累积成突发
            self.due = now - self.burst_s
        self.due += nbytes * self.per_byte
        delay = self.due - time.monotonic()
        if delay > 0.002:          # 低于计时器精度就别白睡
            await asyncio.sleep(delay)


class NVENCStreamTrack(MediaStreamTrack):
    """A MediaStreamTrack whose recv() returns the next av.Packet from the
    GPUStreamer. aiortc recognizes a non-Frame return value and calls
    H264Encoder.pack() on it, which splits the access unit into RTP packets
    WITHOUT re-encoding."""

    kind = "video"

    def __init__(self, streamer_ref, fps):
        super().__init__()
        self._streamer_ref = streamer_ref
        self._fps = max(1, int(fps or 30))
        # RTP 时间戳锚定单调时钟:首个 AU 记锚点,之后 pts = (now - t0)*90000。
        #
        # 不要用"已交付帧计数 * 90000/fps":丢帧发生在 GPUStreamer.read() 内部
        # (断链跳帧 gpu_stream.py:796-798、队列溢出 :730-741),recv() 根本看不到;
        # 重建编码器时 track 对象还活着,那 0.5~2s 空窗也不计数。于是每丢一帧/每重建
        # 一次,视频媒体时钟就永久落后墙上时钟一截 —— 接收端靠 RTCP SR 的 NTP↔RTP
        # 映射对齐两条流,视频时钟落后就会被判成"该更晚播",**音画持续错开且不可恢复**。
        # 音频的时间戳来自样本计数(= 硬件时钟),所以只有视频会漂。
        # 实测(每 4s 丢 15 帧 + 一次 0.8s 重建,2.5s+0.8s=3.3s):
        #   帧计数时钟 → 传输层音画偏移 3277ms;锚定时钟 → 3ms。
        # 复现/对照见 tests/av_sync_probe.py(--fix 切换两种时钟)。
        #
        # 注意 pts 只从交付时刻推导,不保证严格递增(同一毫秒内可能连出两帧),
        # 故下面用 _last_pts 强制单调。
        self._t0 = None
        self._last_pts = -1
        self._closed = False

    def stop(self):
        self._closed = True
        try:
            super().stop()
        except Exception:
            pass

    async def recv(self):
        # 不自行限速:GPUStreamer.read() 会阻塞直到下一帧编码出来(ffmpeg 的采集
        # 节拍本身就是限速器)。按 1/fps 主动 sleep 会让消费速率恒等于生产速率,
        # 一旦生产端出现突发(编码卡顿后追帧)造成队列积压,就再也排不掉 —— 实测
        # 后帧在队列里滞留 ~160ms 均值 / ~280ms 峰值且永不下降;读到就发可在下一
        # 帧内排空。TCP 路径同样不限速。
        while True:
            if self._closed:
                raise StopAsyncIteration
            s = self._streamer_ref[0]
            if s is None:
                await asyncio.sleep(0.05)
                continue
            item = await asyncio.to_thread(s.read, 0.5)
            if item is None:
                continue
            is_idr, data = item
            packet = av.Packet(data)
            now = time.monotonic()
            if self._t0 is None:
                self._t0 = now
            pts = int((now - self._t0) * 90000)
            if pts <= self._last_pts:
                pts = self._last_pts + 1     # 严格单调:同一毫秒内连出两帧也不重复
            self._last_pts = pts
            packet.pts = pts
            packet.time_base = fractions.Fraction(1, 90000)
            return packet


class RTPVideoTransport:
    """Server side of a WebRTC RTP video pipe. Signaling (offer/answer/ICE)
    flows over the existing /ws WebSocket; the encoded H.264 travels over
    standard RTP/UDP with browser-native loss recovery."""

    def __init__(self, ws_send, streamer_ref, fps, ice_servers=None, on_keyframe=None,
                 pacer_bps=0, audio=None, on_audio_device=None):
        self._ws_send = ws_send
        self._streamer_ref = streamer_ref
        self._on_keyframe = on_keyframe
        self._on_audio_device = on_audio_device
        self.audio_track = None
        from aiortc import RTCIceServer
        from aiortc.rtcconfiguration import RTCConfiguration
        # 显式传入 iceServers(空列表也传):aiortc 在 iceServers=None 时会回退到
        # 默认 Google STUN(stun.l.google.com:19302,国内不可达),导致每次
        # createOffer 阻塞约 5s 等 STUN 超时。RTP 走局域网/Tailscale 直连,
        # 只需 host 候选,不需要 STUN。
        servers = [RTCIceServer(urls=s["urls"], username=s.get("username", ""), credential=s.get("credential", ""))
                   for s in (ice_servers or [])]
        self._pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        self._track = NVENCStreamTrack(streamer_ref, fps)
        self._pc.addTrack(self._track)
        # 只协商 H.264（我们的 track 只产 H.264），避免对端选到 VP8
        for transceiver in self._pc.getTransceivers():
            if transceiver.kind == "video":
                try:
                    h264 = RTCRtpCodecCapability(
                        mimeType="video/H264", clockRate=90000,
                        parameters={"level-asymmetry-allowed": "1",
                                    "packetization-mode": "1",
                                    "profile-level-id": "42001f"})
                    transceiver.setCodecPreferences([h264])
                except Exception as e:
                    print(f"  setCodecPreferences failed: {e!r}")
        self._hook_keyframe_requests()
        self._pacer = None
        self._pacer_bps = 0
        # 音频必须先于 pacer 装上:pacer 需要知道音频的 SSRC 才能把音频包排除
        # 在外(见 _install_pacer)。
        if audio:
            self._add_audio(audio)
        self._install_pacer(pacer_bps)
        self._closed = False

    def _add_audio(self, cfg):
        try:
            import audio_stream
        except Exception as e:
            print(f"  RTP audio unavailable: {e!r}")
            return
        try:
            self.audio_track = audio_stream.start_audio_track(
                cfg, on_device=self._on_audio_device)
            if self.audio_track is not None:
                self._pc.addTrack(self.audio_track)
        except Exception as e:
            print(f"  RTP audio failed: {e!r}")
            self.audio_track = None

    def set_pacer_bps(self, bps):
        """运行期改发送 pacer 的目标码率。码率分档会重建编码器,重建后的实际
        产出只有原来的一部分,继续用基准档的 pacer 目标等于没限速(而限得过低又
        会把大 I 帧拖成恒定延迟),所以由上层按当前档位重算。bps<=0 或变化很小
        时忽略。"""
        p = getattr(self, "_pacer", None)
        if p is None or not bps or bps <= 0:
            return
        if abs(bps - self._pacer_bps) < max(1000, self._pacer_bps * 0.01):
            return
        self._pacer_bps = bps
        p.set_bps(bps)
        print(f"  RTP pacer: {bps / 1e6:.1f} Mbps")

    def _audio_ssrc(self):
        """当前音频 sender 的 SSRC(没有音轨则为 None)。"""
        try:
            for tr in self._pc.getTransceivers():
                if tr.kind == "audio" and tr.sender is not None:
                    return getattr(tr.sender, "_ssrc", None)
        except Exception:
            pass
        return None

    def _install_pacer(self, bps):
        """包装 DTLS transport 的 _send_rtp,让出包过一个令牌桶。opt-in:
        bps<=0 不装(默认)。

        **音频包必须绕过 pacer**。`_send_rtp` 是音视频共用的,而 pacer 是内联
        sleep 的 —— 一个视频 I 帧(~180 个包)会把这几百毫秒内到达的音频包一起
        压在它后面,每个 GOP 抖一次,听感就是"断续、像抽帧"。音频总码率只有
        128kbps,根本不需要平滑,直接放行最稳。"""
        if not bps or bps <= 0:
            return
        try:
            transport = self._pc.getTransceivers()[0].sender.transport
            orig = transport._send_rtp
            pacer = _Pacer(bps)
            audio_ssrc = self._audio_ssrc()

            async def _paced(data):
                if audio_ssrc is not None and len(data) >= 12:
                    # RTP 固定头:byte 8..11 是 SSRC
                    if int.from_bytes(data[8:12], "big") == audio_ssrc:
                        await orig(data)
                        return
                await pacer.wait(len(data))
                await orig(data)

            transport._send_rtp = _paced
            self._pacer = pacer
            self._pacer_bps = bps
            print(f"  RTP pacer: {bps / 1e6:.1f} Mbps"
                  + (" (audio bypass)" if audio_ssrc is not None else ""))
        except Exception as e:
            print(f"  RTP pacer install failed: {e!r}")

    def _hook_keyframe_requests(self):
        """对端（浏览器）丢包后会发 RTCP PLI/FIR 请求关键帧，aiortc 收到会调用
        sender._send_keyframe()，但 pack() 分支不消费该标志（RTP 路径下等于被
        丢掉）。这里把它转交上层，由上层重建编码器强制出 IDR —— 否则只能等正常
        GOP（gop/fps 秒），表现为长时间花屏。"""
        if self._on_keyframe is None:
            return
        try:
            sender = self._pc.getTransceivers()[0].sender
            orig = sender._send_keyframe

            def _sk():
                try:
                    orig()
                except Exception:
                    pass
                try:
                    self._on_keyframe()
                except Exception:
                    pass

            sender._send_keyframe = _sk
        except Exception as e:
            print(f"  RTP keyframe hook failed: {e!r}")

        @self._pc.on("icecandidate")
        async def on_candidate(candidate):
            if candidate is None or self._ws_send is None:
                return
            try:
                await self._ws_send(json.dumps({
                    "type": "rtp_ice",
                    "candidate": {
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid or "0",
                        "sdpMLineIndex": candidate.sdpMLineIndex or 0,
                    },
                }))
            except Exception:
                pass

        @self._pc.on("iceconnectionstatechange")
        async def on_ice_state():
            s = self._pc.iceConnectionState
            print(f"  RTP ICE state: {s}")

    async def create_offer(self):
        await self._pc.setLocalDescription(await self._pc.createOffer())
        return self._pc.localDescription

    async def handle_answer(self, sdp, sdp_type):
        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp, type=sdp_type or "answer"))

    async def add_ice(self, candidate_dict):
        from aiortc import RTCIceCandidate
        c = candidate_dict
        parts = c.get("candidate", "").split()
        if len(parts) >= 8 and parts[0].startswith("candidate:"):
            _, foundation = parts[0].split(":", 1)
            candidate = RTCIceCandidate(
                component=int(parts[1]), foundation=foundation,
                protocol=parts[2], priority=int(parts[3]),
                ip=parts[4], port=int(parts[5]), type=parts[7],
                sdpMid=c.get("sdpMid", "0"),
                sdpMLineIndex=c.get("sdpMLineIndex", 0))
        else:
            candidate = RTCIceCandidate(
                component=1, foundation="0", protocol="udp", priority=0,
                ip="0.0.0.0", port=0, type="host",
                sdpMid=c.get("sdpMid", "0"),
                sdpMLineIndex=c.get("sdpMLineIndex", 0))
        try:
            await self._pc.addIceCandidate(candidate)
        except Exception:
            pass

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._track.stop()
        except Exception:
            pass
        try:
            if self.audio_track is not None:
                self.audio_track.stop()      # 同时关掉 WASAPI 采集线程
        except Exception:
            pass
        try:
            s = self._streamer_ref[0]
            if s is not None:
                s.close()
        except Exception:
            pass
        try:
            await self._pc.close()
        except Exception:
            pass
