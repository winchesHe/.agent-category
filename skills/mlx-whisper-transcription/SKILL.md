---
name: mlx-whisper-transcription
description: 在 Apple Silicon Mac 上用 MLX Whisper 离线转写本地音频并生成文本与字幕。
---

# MLX Whisper Transcription

在 Apple Silicon Mac 上用固定的 `whisper-large-v3-turbo` 模型离线转写本地音频。音频不上传，模型正式存放在用户数据目录，不依赖 Hugging Face cache 作为安装结果。

## 前置条件

| 项 | 要求 |
|---|---|
| 平台 | macOS + Apple Silicon `arm64` |
| Python | `>=3.10`，由 `uv` 按 PEP 723 声明准备隔离环境 |
| 模型 | 默认位于 `~/.local/share/mlx-whisper/models/whisper-large-v3-turbo` |
| 磁盘 | 首次安装模型约需 1.5 GB；临时安装阶段需额外空间 |
| 认证 | 无；本 Skill 不调用云端 API |

不要求全局安装 `ffmpeg`。CLI 使用 `imageio-ffmpeg` 随包二进制解码音频。

## 脚本位置

唯一入口始终相对于本 `SKILL.md` 所在目录：

```bash
SKILL_DIR="<本 SKILL.md 所在目录>"
uv run "$SKILL_DIR/scripts/mlx_whisper_transcription.py" <subcommand> [flags]
```

始终使用 `SKILL_DIR` 绝对路径，不依赖 CWD；不要直接调用 `scripts/mwt/commands/*.py`。

## 子命令速查表

| 子命令 | 作用 | 必填输入 |
|---|---|---|
| `doctor` | 只读检查平台、ffmpeg 和正式模型完整性 | 无 |
| `setup` | 安装固定 revision 模型到正式目录 | 无 |
| `transcribe` | 离线转写单个本地音频 | `audio` |

## 通用 flag

| Flag | 说明 |
|---|---|
| `--model-dir PATH` | 临时覆盖模型目录；默认读取 `MLX_WHISPER_MODEL_DIR`，再回退正式目录 |
| `--format json\|human\|summary` | 默认 `json`；JSON 写 stdout，human/summary 写 stderr |

`transcribe` 专用 flag：

| Flag | 说明 |
|---|---|
| `--output-dir PATH` | 产物目录，默认音频所在目录 |
| `--output-name NAME` | 产物基础文件名，不能包含目录 |
| `--output-formats txt,srt,json\|all` | 默认 `all`，生成三种格式 |
| `--language auto\|zh\|en\|...` | 默认自动识别；已知中文时传 `zh` |
| `--initial-prompt TEXT` | 可选上下文提示，可能诱导静音幻觉 |
| `--word-timestamps / --no-word-timestamps` | 默认启用词级时间戳 |
| `--overwrite` | 显式覆盖已有产物；默认拒绝覆盖 |

## 场景决策树

```text
用户要求把本地音频转文字或生成字幕？
  -> doctor
  -> ready=true：transcribe <audio> --output-formats all
  -> ready=false 且只缺模型：告知首次安装约 1.5 GB，用户确认后 setup
  -> setup 成功后再 transcribe

用户明确说音频为中文？
  -> transcribe <audio> --language zh

用户未说明语言？
  -> 保持 --language auto

用户提供专有名词提示？
  -> 先提示 initial prompt 可能诱导幻觉
  -> 用户仍要求时才传 --initial-prompt

用户要求把外语音频翻译成中文？
  -> 先转写源语言，再交给独立翻译流程
  -> 不使用 Whisper translate 冒充中文翻译

用户要求区分说话人？
  -> 明确首版不支持 diarization，不伪造说话人标签
```

## 领域知识

### 模型存储

默认模型固定为：

```text
repo: mlx-community/whisper-large-v3-turbo
revision: a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb
path: ~/.local/share/mlx-whisper/models/whisper-large-v3-turbo
```

`setup` 可以复用 Hugging Face cache 加速下载，但只有正式目录包含非空 `config.json` 和 `weights.safetensors` 才算成功。有效模型已存在时，`setup` 幂等返回；`--force` 仍先在临时目录下载和校验，再替换旧模型。

### 输出语义

- TXT 是按识别段落输出的原始文本。
- SRT 是字幕时间轴；默认词级时间戳提高切分质量。
- JSON 保留模型原始 `text`、`segments`、`words` 和 `language`。
- CLI 自己的 JSON 摘要只包含输入、模型、语言、时长、段数和产物路径，不混入转写 JSON。

自动转写不是逐字准确。最终回复必须提醒用户核对人名、股票名、公司名和低音质片段。

## NEVER 规则

- 不要在 `transcribe` 中隐式下载模型。先用 `doctor` 判断，用户确认约 1.5 GB 安装后才能执行 `setup`。
- 不要把 Hugging Face cache 路径当正式模型目录；成功安装必须指向 `~/.local/share/mlx-whisper/models/` 或用户显式目录。
- 不要自动回退 OpenAI、Venice 等云端 API；音频必须留在本机。
- 不要默认覆盖已有 TXT/SRT/JSON；只有用户授权后传 `--overwrite`。
- 不要自动修改原始转写里的专有名词；如需整理稿，另建产物并保留原始结果。
- 不要默认注入专有名词 prompt；实测长 prompt 会让静音段产生重复幻觉。
- 不要删除、移动或改写输入音频，不在输入目录残留 PCM/WAV 临时文件。
- 不要声称 Whisper `translate` 能翻译成中文；该任务只输出英语。

## 错误处理

| 退出码 | 原因 | 处理 |
|---:|---|---|
| 0 | 成功 | 解析 stdout JSON；`doctor` 的 `ready` 决定是否可转写 |
| 2 | 参数、环境或模型缺失 | 检查平台、输入路径、模型目录和输出格式 |
| 3 | 文件系统权限错误 | 更换可写模型/输出目录或修复权限 |
| 4 | 下载、解码、模型、目标冲突或推理错误 | 根据 stderr 修复；已有产物需明确决定是否覆盖 |
| 5 | 受控子进程超时 | 检查音频、磁盘或网络后重试 |

失败时 stdout 保持为空，错误写 stderr。

## 示例

```bash
SKILL_DIR="/Users/moego-winches/Desktop/Company/person/skills/mlx-whisper-transcription"

# 检查是否就绪
uv run "$SKILL_DIR/scripts/mlx_whisper_transcription.py" doctor

# 用户确认首次约 1.5 GB 安装后执行
uv run "$SKILL_DIR/scripts/mlx_whisper_transcription.py" setup

# 自动识别语言，生成 TXT/SRT/JSON
uv run "$SKILL_DIR/scripts/mlx_whisper_transcription.py" transcribe \
  "/path/to/audio.m4a"

# 明确中文，并指定输出目录
uv run "$SKILL_DIR/scripts/mlx_whisper_transcription.py" transcribe \
  "/path/to/audio.mp3" \
  --language zh \
  --output-dir "/path/to/output"

# 用户明确授权后覆盖已有产物
uv run "$SKILL_DIR/scripts/mlx_whisper_transcription.py" transcribe \
  "/path/to/audio.wav" \
  --overwrite
```
