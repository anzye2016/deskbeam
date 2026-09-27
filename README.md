# DeskBeam

基于浏览器的桌面串流与远程遥控（Windows / Ubuntu） —— 手机、平板、任意浏览器，随时随地控制你的电脑。

## 功能

| 能力 | 说明 |
|---|---|
| 桌面串流 | 硬件编码串流（Windows：ddagrab→NVENC/AMF/QSV；Ubuntu X11：x11grab→VAAPI），低延迟、CPU 占用低 |
| 触控板遥控 | 手机屏幕当触摸板，多指缩放、滑动、点击 |
| 快捷键 | 常用快捷键（Ctrl+C/V、Alt+Tab、Win、F5 等） |
| GYRO 激光笔 | 手机陀螺仪当激光笔，晃动机身移动光标 |
| 文字输入 | 浏览器输入框 → 电脑键盘输入 |
| 语音转文字 | 按住说话，自动识别为文字发送 |
| 安全 | TLS 加密传输 + 口令认证（可选 TOTP） |

## 三种使用模式

点击顶部模式按钮切换：

- **REMOTE**：触控板遥控，无画面，纯控制
- **SCREEN**：实时桌面串流 + 叠加控制
- **GYRO**：陀螺仪激光笔 + 快捷键 + 语音输入

## 快速开始

```powershell
git clone https://github.com/anzye2016/deskbeam.git
cd deskbeam
copy config.example.json config.json
start.bat
```

`start.bat` 自动创建虚拟环境、安装依赖、生成证书并启动服务。放行防火墙 **8770** 端口后，用浏览器打开 `https://<主机局域网IP>:8770`（首次会提示自签名证书警告，点“继续访问”即可）。

## Ubuntu (X11)

Web 端同样支持 Ubuntu 平台（需 Xorg 会话，Wayland 不支持）。复制项目到 Linux 机器，执行 `./start.sh` 自动建 venv、装依赖并启动（依赖清单见 `requirements-linux.txt`，硬件编解码走 VAAPI）：

```bash
sudo apt install ffmpeg python3-venv      # 一次性系统依赖（按 GPU 补装 VAAPI 驱动）
cd deskbeam && ./start.sh                 # 自动建 venv + 装依赖 + 启动
```

同一 `config.json`、`certgen.py` 生成证书，浏览器访问 `https://<Linux主机IP>:8770` 即可。

## 免 Python 部署（exe）

目标机器无需安装 Python。运行 `build.bat` 生成 `DeskBeam.exe`，与 `config.json`、`cert.pem`、`key.pem` 一起复制部署即可。

## 操作面板

点击页面左上角的 LIVE 字样打开操作面板：

- 串流状态：编码方式（硬件 / 软件）与分辨率，可判断串流是否正常或降级
- Logout 退出登录 · GYRO 切换陀螺仪 · Shutdown 关闭服务 · 主题切换

## 浏览器要求

串流画面用 Chrome / Edge 94+（WebCodecs）效果最佳。Firefox / Safari 会自动降级到 WebRTC 播放（约 30fps、延迟略高），遥控功能在所有浏览器可用。

## 配置

复制 `config.example.json` 为 `config.json` 后按需修改（端口、口令、帧率、码率等）。TLS 证书可用 `python certgen.py` 生成。

## 安全

TLS 加密传输 + 口令认证（可选 TOTP 动态码），口令连续错误 5 次封锁 24 小时。`config.json` 与证书文件不入库，请妥善保管。

## 许可证

MIT — 详见 [LICENSE](LICENSE)
