# WHAM→GMR Docker 启动参考

镜像：`11111p5p/wham-gmr:latest`（Docker Hub）。

> ⚠️ 镜像必须包含 `scripts/pipeline_watchdog.py` 与 `scripts/latest_frame_queue.py`，
> 否则运行时报 `ModuleNotFoundError: No module named 'scripts.pipeline_watchdog'`。
> 增量重建：`docker build -f docker/Dockerfile.patch -t 11111p5p/wham-gmr:latest .`，然后 `docker push`。

## 模式一：视频文件 → 关节角（Windows / Linux 均可）

Windows Docker Desktop **只能**跑这个模式（透传不了摄像头）。

```powershell
# Windows PowerShell
docker run --rm --gpus all `
  -v "${PWD}\out:/output" `
  11111p5p/wham-gmr:latest
```

```bash
# Linux
docker run --rm --gpus all -v "$PWD/out:/output" 11111p5p/wham-gmr:latest
```

跑自己的视频：把视频挂载进容器，再以参数传容器内路径 `/input/xxx.mp4`。

输出：`out/csv/live_motion.csv`（关节角）、`out/pkl/my_motion.pkl`。

## 模式二：摄像头实时（仅 Linux 宿主）

Windows Docker Desktop 不支持 USB 摄像头透传；请用 Linux 宿主，或 Windows 本机 `run.ps1`。

```bash
docker run --gpus all --rm \
  --device /dev/video0:/dev/video0 \
  -e VIDEO=0 \
  -e WHAM_USE_YOLOPOSE=1 \
  -e WHAM_GPU_SCHEDULER=1 \
  -e WHAM_INFER_INTERVAL=2 \
  -e WHAM_LATEST_FRAME=1 \
  -e WHAM_LATEST_FRAME_KEEP=1 \
  -e WHAM_ADAPTIVE_KEEP=0 \
  -e CAMERA_ELEVATION=0 \
  -e CAMERA_AZIMUTH=90 \
  -e CAMERA_DISTANCE_SCALE=1.5 \
  -v "$PWD/out:/output" \
  11111p5p/wham-gmr:latest
```

## 优化参数对照

| 参数 | 值 | 作用 | 生效范围 |
|---|---|---|---|
| `WHAM_USE_YOLOPOSE` | 1 | 单阶段 YOLOv8-pose（~27ms/帧） | 视频/摄像头 |
| `WHAM_GPU_SCHEDULER` | 1 | WHAM 独占 GPU | 视频/摄像头 |
| `WHAM_INFER_INTERVAL` | 2 | 隔帧推理，算量减半（细节变粗） | 视频/摄像头 |
| `WHAM_BATCH_K` | 2 | 批量窗口推理 ~2× 吞吐 | 视频/摄像头 |
| `GMR_TORCH_DEVICE` | cuda | GMR IK 放 GPU | 视频/摄像头 |
| `GMR_RENDER_SCALE` | 0.1 | 砍 MuJoCo 渲染分辨率 | 视频/摄像头 |
| `CAMERA_ELEVATION` | 0 | 平视 | 取景 |
| `CAMERA_AZIMUTH` | 90 | 正面 | 取景 |
| `CAMERA_DISTANCE_SCALE` | 1.5 | 取景距离 | 取景 |
| `WHAM_LATEST_FRAME` | 1 | 丢旧帧保低延迟 | 仅摄像头 |
| `WHAM_LATEST_FRAME_KEEP` | 1 | 队列只留 1 帧 | 仅摄像头 |
| `WHAM_ADAPTIVE_KEEP` | 0 | 关快速运动自动放宽 | 仅摄像头 |
| `GMR_HEADLESS_RECORD` | 1 | 无头离屏（默认）；0=弹窗需 X | 渲染 |
| `RECORD_GMRVIDEO` | 0 | 不写机器人 mp4；1=写 | 渲染 |

## 备注

- Windows 摄像头实时：用本机 `run.ps1`（`$env:VIDEO="0"`），Docker 透传不了摄像头。
- Linux 摄像头：容器内固定开 `VideoCapture(0)`，所以 `--device /dev/videoN:/dev/video0` 必须映射成 `/dev/video0`。

## 浏览器实时预览

需要 TCP 图片预览时，在接收图片的宿主机上运行 `python scripts/camera_preview_server.py`，打开 `http://127.0.0.1:8098`。生产端启动时须设 `TCP=1`，并能连接该宿主机的 TCP 9876 端口。新版接收端保持两条 MJPEG 流，图片一到就推给浏览器；慢浏览器只取最新 JPEG，每条流最多推送 15 FPS，不会重放积压帧。`/status` 会给出输入帧数、最新帧年龄和到达间隔的 p95，便于定位源头是否仍在卡顿。

可用 `PREVIEW_TCP_PORT`、`PREVIEW_HTTP_PORT` 和 `PREVIEW_MAX_FPS` 调整端口与呈现上限。这个接收端只去掉旧页面每 300 ms 拉图一次的限制，不会增加 WHAM/GMR 实际产生新动作的频率；若机器人源流本身只有约 2 FPS，仍需要先查推理与渲染耗时。请先停止占用相同端口的旧预览服务，再启动新版接收端。

摄像头、`--tcp`、无头 MuJoCo 且不录视频时，生产端默认开启统一展示时钟 `TCP_PRESENT_CLOCK=1`。相机采集持续更新最新画面；机器人预览按 `GMR_PREVIEW_FPS=15` 的时隙从最新 IK 姿态渲染。展示错过时隙会跳到下一个时隙，不补发旧图；两条 TCP 流由同一个展示线程发送。机器人姿态只在展示时以 `TCP_PRESENT_RESPONSE_MS=120` 毫秒的响应时间做因果平滑，不改变 CSV、PKL 或 IK 结果。原渲染分辨率保持不变。

观察日志中的 `[Present]`：`skipped` 是错过的展示时隙，`camera_gap_p95_ms` 和 `robot_gap_p95_ms` 是实际发送间隔，`camera_age_ms` 与 `robot_age_ms` 是画面所依据的采集帧年龄。接收端 `/status` 可核对网络到达节奏。若 GPU 渲染赶不上 15 FPS，先降低 `GMR_PREVIEW_FPS` 到设备能稳定维持的值，并对比机器人帧龄；可用 `TCP_PRESENT_CLOCK=0` 回退原路径。`WHAM_GPU_SCHEDULER=1` 时 MuJoCo 渲染也会在 WHAM 前向计算期间让出 GPU。相机与机器人计算延迟不同，统一时钟只能稳定展示节奏，不能保证两者动作在同一源时间戳上对齐。
