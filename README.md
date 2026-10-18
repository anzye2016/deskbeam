# DeskBeam

基于浏览器的桌面串流与远程遥控（Windows / Ubuntu X11） —— 手机、平板、任意浏览器，随时随地控制你的电脑。

**不用装客户端**：浏览器打开网页就能用。

## 功能

| 能力 | 说明 |
|---|---|
| 桌面串流 | 硬件编码（Windows：ddagrab→NVENC/AMF/QSV；Ubuntu X11：x11grab→VAAPI），低延迟、CPU 占用低 |
| 双传输 | **默认 UDP/RTP**（局域网亦然）：丢包不阻塞后续帧，码率随网络自动升降档；也可手动切回 TCP |
| 触控板遥控 | 手机屏幕当触摸板，多指缩放（0.5x~10x）、滑动、点击、**按住不动 = 按住左键**（可拖拽） |
| 快捷键 | 常用快捷键（Ctrl+C/V、Alt+Tab、Win、F5 等），支持多指同时按住 |
| GYRO 激光笔 | 手机陀螺仪当激光笔，晃动机身移动光标，配翻页键讲 PPT |
| 声音回传 | UDP 下把电脑声音一并传过来（WASAPI 回环 → Opus），带**自动增益**，不同设备的音量差会自动拉平 |
| 文字 / 语音 | 输入框打字 → 电脑键盘；按住说话转文字：可接**在线接口**，也可接**本地或局域网上的 ASR 服务**（HTTP 接口，模型跑在 WSL / Windows / Docker 都可以，默认本地优先） |
| ESP-HID 补充 | 配合 [esp-macro](https://github.com/anzye2016/esp-macro) 把 ESP32 当**真正的 USB 键鼠**：在安全桌面（UAC / 锁屏）、模态菜单等**合成输入失效**的场景下依然可以操作 |
| 安全 | TLS 加密 + 口令认证（可选 TOTP 动态码）+ 局域网访问开关 |

## 三种使用模式

点击顶部模式按钮切换：

- **REMOTE**：触控板遥控，无画面，纯控制（带宽极低，手机流量也够用）
- **SCREEN**：实时桌面串流 + 叠加控制（放大到满屏时标题栏保留左右键与滚轮）
- **GYRO**：陀螺仪激光笔 + 可自定义按键（按住画面 = 按住左键，可拖拽）

## 快速开始

```powershell
git clone https://github.com/anzye2016/deskbeam.git
cd deskbeam
copy config.example.json config.json
start.bat
```

`start.bat` 自动创建虚拟环境、安装依赖、生成证书、放行防火墙并启动服务（首次会请求管理员权限以创建防火墙规则）。之后用浏览器打开 `https://<主机IP>:8770` —— 首次会提示自签名证书警告，点“继续访问”即可。

想从外网连回来，推荐用 Tailscale 等组网工具：媒体流在组网内直连，无需把服务暴露到公网。

## Ubuntu (X11)

复制项目到 Linux 机器，执行 `./start.sh` 自动建 venv、装依赖并启动：

```bash
sudo apt install ffmpeg python3-venv      # 一次性系统依赖（按 GPU 补装 VAAPI 驱动）
cd deskbeam && ./start.sh                 # 自动建 venv + 装依赖 + 启动
```

**需要 Xorg 会话，Wayland 不支持**（Wayland 限制全局抓屏）。同一份 `config.json`、`certgen.py` 生成证书，浏览器访问 `https://<Linux主机IP>:8770` 即可。

## ESP-HID 补充（可选）

[esp-macro](https://github.com/anzye2016/esp-macro) 是配套项目：ESP32-S3 当 USB 键鼠，并可用继电器做开机/重启。

手机网页通过一个 relay 转发命令，DeskBeam 的页面也能直接用这个通道（设置里填 relay 地址与 token）。它是**真正的 USB HID 设备**，所以在安全桌面（UAC / 锁屏）、模态菜单这类"合成输入进不去"的场景下依然可以操作。

## 免 Python 部署（exe）

目标机器无需安装 Python。运行 `build.bat` 生成 `DeskBeam.exe`，与 `config.json`、`cert.pem`、`key.pem` 一起复制部署即可。

## 操作面板

点击页面左上角的 LIVE 字样打开操作面板：

- 串流状态：编码方式（硬件 / 软件）与分辨率，可判断串流是否正常或降级
- 传输方式（UDP / TCP）、声音开关（UDP 下）、本地/在线语音识别、详细统计：RTT / 解码 / 上屏 / 缓冲 / 丢帧，UDP 另显示丢包、抖动与 NACK
- Logout 退出登录 · GYRO 切换陀螺仪 · Shutdown 关闭服务 · 主题切换

## 浏览器要求

串流画面用 Chrome / Edge 94+（WebCodecs）效果最佳。Firefox / Safari 会自动降级到 WebRTC 播放（约 30fps、延迟略高），遥控功能在所有浏览器可用。

## 配置

复制 `config.example.json` 为 `config.json` 后按需修改（端口、口令、帧率、码率、传输与声音等）。音频相关参数为 `audio_*` 系列，仅在 UDP 模式下生效；语音识别可用 `asr_local_url` 指向本地/局域网的 ASR 服务，或用 `asr_api_*` 接在线接口。TLS 证书可用 `python certgen.py` 生成。

## 安全

TLS 加密传输 + 口令认证（可选 TOTP 动态码），口令连续错误 5 次封锁 24 小时。`config.json` 与证书文件不入库，请妥善保管。

## 许可证

MIT — 详见 [LICENSE](LICENSE)
