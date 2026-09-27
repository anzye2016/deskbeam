"""WebRTC screen streaming with data channel for control commands."""
import asyncio, fractions, json, time
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import av

class ScreenTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, capture_fn, fps=15):
        super().__init__()
        self._capture_fn = capture_fn
        self._interval = 1.0 / fps
        self._last_frame = None
        self._start = time.monotonic()
        self._pts = 0

    async def recv(self):
        now = time.monotonic()
        wait = self._interval - (now - self._start) % self._interval
        if wait > 0:
            await asyncio.sleep(wait)
        raw, w, h = await self._capture_fn()
        if raw is None or w == 0 or h == 0:
            return await self.recv()
        frame = av.VideoFrame(w, h, "bgra")
        frame.planes[0].update(raw)
        frame.pts = self._pts
        self._pts += int(90000 * self._interval)
        frame.time_base = fractions.Fraction(1, 90000)
        return frame


class WebRTCSession:
    def __init__(self, ws_send, data_handler=None, ice_servers=None):
        # 显式传入 iceServers(空列表也传):aiortc 在 iceServers=None 时会回退到
        # 默认 Google STUN(国内不可达),createOffer 阻塞约 5s。RTP 走局域网/
        # Tailscale 直连,只需 host 候选,不需要 STUN。
        servers = []
        for s in (ice_servers or []):
            servers.append(RTCIceServer(urls=s["urls"], username=s.get("username", ""), credential=s.get("credential", "")))
        self._pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        self._ws_send = ws_send
        self._data_handler = data_handler
        self._track = None
        self._done = asyncio.Event()

        @self._pc.on("iceconnectionstatechange")
        async def on_ice():
            s = self._pc.iceConnectionState
            print(f"  WebRTC ICE state: {s}")
            if s in ("failed", "closed", "disconnected"):
                self._done.set()

        @self._pc.on("icecandidate")
        async def on_candidate(candidate):
            if candidate:
                try:
                    await self._ws_send(json.dumps({
                        "type": "webrtc_ice",
                        "candidate": {"candidate": candidate.candidate,
                                      "sdpMid": candidate.sdpMid or "0",
                                      "sdpMLineIndex": candidate.sdpMLineIndex or 0}
                    }))
                except Exception:
                    pass

        self._dc = self._pc.createDataChannel("deskbeam")

        @self._dc.on("message")
        async def on_dc_message(msg):
            if self._data_handler:
                try:
                    await self._data_handler(msg)
                except Exception:
                    pass

    def add_track(self, capture_fn, fps=15):
        self._track = ScreenTrack(capture_fn, fps)
        self._pc.addTrack(self._track)

    async def create_offer(self):
        await self._pc.setLocalDescription(await self._pc.createOffer())
        return self._pc.localDescription

    async def handle_answer(self, sdp, sdp_type):
        answer = RTCSessionDescription(sdp=sdp, type=sdp_type)
        await self._pc.setRemoteDescription(answer)

    async def add_ice(self, candidate_dict):
        from aiortc import RTCIceCandidate
        c = candidate_dict
        parts = c.get("candidate", "").split()
        if len(parts) >= 8 and parts[0].startswith("candidate:"):
            _, foundation = parts[0].split(":", 1)
            component = int(parts[1])
            protocol = parts[2]
            priority = int(parts[3])
            ip = parts[4]
            port = int(parts[5])
            ctype = parts[7]
        else:
            foundation, component, protocol, priority, ip, port, ctype = "", 0, "", 0, "", 0, ""
        candidate = RTCIceCandidate(
            component=component, foundation=foundation, ip=ip, port=port,
            priority=priority, protocol=protocol, type=ctype,
            sdpMid=c.get("sdpMid", "0"),
            sdpMLineIndex=c.get("sdpMLineIndex", 0))
        await self._pc.addIceCandidate(candidate)

    async def close(self):
        if self._track:
            self._track.stop()
        await self._pc.close()
        self._done.set()
