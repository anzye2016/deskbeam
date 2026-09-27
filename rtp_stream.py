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
        # 帧序号用于算 RTP 时间戳:每帧 +90000/fps ticks(帧率固定,直接乘除,
        # 不做累加,避免整数截断漂移)。
        self._fps_num = 0
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
            packet.pts = self._fps_num * 90000 // self._fps
            self._fps_num += 1
            packet.time_base = fractions.Fraction(1, 90000)
            return packet


class RTPVideoTransport:
    """Server side of a WebRTC RTP video pipe. Signaling (offer/answer/ICE)
    flows over the existing /ws WebSocket; the encoded H.264 travels over
    standard RTP/UDP with browser-native loss recovery."""

    def __init__(self, ws_send, streamer_ref, fps, ice_servers=None, on_keyframe=None,
                 pacer_bps=0):
        self._ws_send = ws_send
        self._streamer_ref = streamer_ref
        self._on_keyframe = on_keyframe
        self._pacer_bps = pacer_bps
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
        self._install_pacer(pacer_bps)
        self._closed = False

    def _install_pacer(self, bps):
        """Wrap the DTLS transport's _send_rtp so every outgoing packet passes
        through a token bucket. Opt-in: bps<=0 disables it (default)."""
        if not bps or bps <= 0:
            return
        try:
            transport = self._pc.getTransceivers()[0].sender.transport
            orig = transport._send_rtp
            pacer = _Pacer(bps)

            async def _paced(data):
                await pacer.wait(len(data))
                await orig(data)

            transport._send_rtp = _paced
            print(f"  RTP pacer: {bps / 1e6:.1f} Mbps")
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
            s = self._streamer_ref[0]
            if s is not None:
                s.close()
        except Exception:
            pass
        try:
            await self._pc.close()
        except Exception:
            pass
