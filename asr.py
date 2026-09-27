#!/usr/bin/env python3
"""asr - 语音转文字 (命令行工具)"""
import base64, json, re, sys, os, time, urllib.request, subprocess, tempfile, threading

SERVER = "http://127.0.0.1:8082"

def main():
    args = sys.argv[1:]
    if not args or "--help" in args or "-h" in args:
        print("用法: asr <音频文件> [-s [字幕.srt]]")
        print("  需先 m asr 启动服务")
        sys.exit(0)

    audio = None
    subtitle = False
    srt_out = None
    i = 0
    while i < len(args):
        if args[i] in ("-s", "--subtitle"):
            subtitle = True
            if i + 1 < len(args) and not args[i+1].startswith("-"):
                i += 1
                srt_out = args[i]
        else:
            audio = args[i]
        i += 1

    if not audio or not os.path.isfile(audio):
        print(f"文件不存在: {audio}")
        sys.exit(1)

    size = os.path.getsize(audio)
    print(f"音频: {os.path.basename(audio)} ({size//1024//1024}MB)")
    print("编码中...")

    with open(audio, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = json.dumps({"audio": b64, "timestamp": subtitle})
    print(f"编码完成 ({len(b64)//1024}KB)")

    alive = True
    def spin():
        while alive:
            for c in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏":
                if not alive: break
                sys.stderr.write(f"\r  {c} 处理中...")
                sys.stderr.flush()
                time.sleep(0.3)
    t = threading.Thread(target=spin, daemon=True)
    t.start()

    try:
        req = urllib.request.Request(f"{SERVER}/v1/audio/transcriptions",
            data=payload.encode(), headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=600)
        data = json.loads(resp.read())
    except Exception as e:
        alive = False
        sys.stderr.write("\r               \r")
        print(f"请求失败: {e}")
        sys.exit(1)

    alive = False
    sys.stderr.write("\r               \r")

    text = data.get("text", "").strip()
    text = re.sub(r"\[\d+\.?\d*\]|\[S\d+\]", "", text).strip()
    print(f"\n{text}")

    if subtitle:
        def fmt(sec):
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s = sec % 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

        srt_path = srt_out or (os.path.splitext(audio)[0] + ".srt")
        srt_content = ""

        segments = data.get("segments", [])
        if segments:
            # MTD 格式（含 speaker 字段）：按标点拆成短句，时间按字数比例分配
            if "speaker" in segments[0]:
                lines = []
                idx = 0
                for seg in segments:
                    st = seg.get("start", 0)
                    et = seg.get("end", 0)
                    text = seg["text"]
                    parts = [s.strip() for s in re.split(r"(?<=[。！？.!?，、；：,;:])", text) if s.strip()]
                    if len(parts) <= 1:
                        parts = [text]
                    total = len(text)
                    cur = st
                    for p in parts:
                        dur = (et - st) * len(p) / max(total, 1)
                        idx += 1
                        lines.append(str(idx))
                        lines.append(f'{fmt(cur)} --> {fmt(cur + dur)}')
                        lines.append(p)
                        lines.append("")
                        cur += dur
                srt_content = "\n".join(lines)
            else:
                # ASR 对齐器格式（逐字）：用原始逐字时间戳合并成句子
                full_text = data.get("text", "").strip()
                sents = [s.strip() for s in re.split(r"(?<=[。！？.!?，、；：,;:])", full_text) if s.strip()]
                if len(sents) <= 1 and full_text:
                    sents = [full_text]
                # 逐字 segment 不含标点，拼接后去标点做匹配
                seg_text = "".join(s.get("text", "") for s in segments)
                seg_clean = re.sub(r'[，。！？、；：,.!?;:\s]', '', seg_text)
                seg_starts = [s.get("start_time", 0) for s in segments]
                seg_ends = [s.get("end_time", 0) for s in segments]
                lines = []
                pos = 0
                for idx, s in enumerate(sents, 1):
                    s_clean = re.sub(r'[，。！？、；：,.!?;:\s]', '', s)
                    start_pos = seg_clean.find(s_clean, pos)
                    if start_pos < 0:
                        start_pos = pos
                    end_pos = start_pos + len(s_clean)
                    pos = end_pos
                    st = seg_starts[min(start_pos, len(seg_starts) - 1)]
                    et = seg_ends[min(end_pos - 1, len(seg_ends) - 1)]
                    lines.append(str(idx))
                    lines.append(f'{fmt(st)} --> {fmt(et)}')
                    lines.append(s)
                    lines.append("")
                srt_content = "\n".join(lines)
        elif data.get("srt"):
            srt_content = data["srt"]

        if srt_content:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            seg_count = sum(1 for l in srt_content.split("\n") if "-->" in l)
            print(f"字幕已保存: {srt_path} ({seg_count} 段)")
        else:
            print("未生成字幕")

    print(f"耗时: {int(time.time() - start_time)}s")

if __name__ == "__main__":
    start_time = time.time()
    main()
