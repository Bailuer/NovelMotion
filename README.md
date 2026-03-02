# NovelMotion

**Turn chapter text into storyboards, keyframe images, subtitles, and a ready-to-render video pipeline** — for short-form vertical (9:16) or landscape (16:9) video.

NovelMotion is a minimal Python CLI that takes raw narrative text and produces a structured storyboard (one “shot” per sentence), PNG keyframes per shot (placeholder or Stable Diffusion–rendered), an SRT subtitle file, and copy-paste FFmpeg commands to build the final video with burned-in subtitles.

---

## Table of contents

- [Features](#features)
- [Pipeline overview](#pipeline-overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Input format](#input-format)
- [Usage](#usage)
- [Output files](#output-files)
- [Environment variables](#environment-variables)
- [Stable Diffusion](#stable-diffusion)
- [FFmpeg: rendering the final video](#ffmpeg-rendering-the-final-video)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)
- [License](#license)

---

## Features

- **Text → storyboard:** Splits chapter text by sentences (using `。！？.!?` and newlines), assigns a fixed duration per sentence (default 5s), and builds a shot list with camera moves and image prompts.
- **Two frame modes:**
  - **Placeholder** (default): Fast Pillow-generated frames with shot index, camera tag, and prompt text — no GPU, ideal for quick iteration.
  - **Stable Diffusion:** Renders each shot with Diffusers (CUDA / Apple MPS / CPU), with optional Hugging Face token for gated models.
- **Subtitles:** Exports `subtitles.srt` aligned to shot timings (same duration per sentence).
- **FFmpeg-ready:** Prints a two-step command: (1) concat images with per-shot duration, (2) burn subtitles and output MP4. No FFmpeg required to generate assets; use the command when you’re ready to render.
- **Orientation:** Portrait (1080×1920) or landscape (1920×1080).
- **Secrets in env:** API keys/tokens via environment variables or `.env` (e.g. `HF_TOKEN`); no hardcoded credentials.

---

## Pipeline overview

```
chapter.txt
    │
    ▼
Split by sentences (。！？.!? / newlines)
    │
    ▼
Build storyboard: 1 shot per sentence, duration, camera move, prompt
    │
    ├──► storyboard.json
    ├──► subtitles.srt
    ├──► frames/frame_0001.png … (placeholder or SD)
    └──► Printed FFmpeg command → final MP4 (you run it)
```

**Camera moves** (assigned in a simple cycle per shot): `static`, `push`, `pull`, `pan-left`, `pan-right`, `tilt-up`, `tilt-down`.

---

## Requirements

- **Python 3.8+**
- **Pillow** — required for placeholder frames
- **FFmpeg** — optional; only needed when you run the printed command to produce the final MP4

For **Stable Diffusion** rendering (`--renderer sd`):

- `torch`, `diffusers`, `transformers`, `accelerate`
- GPU (CUDA) or Apple MPS recommended; CPU is supported but slow
- Sufficient disk space for model weights (e.g. ~4GB+ for SD 1.5)

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/NovelMotion.git
cd NovelMotion
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

For **Stable Diffusion** support, install the optional dependencies (uncomment the SD block in `requirements.txt` or run):

```bash
pip install torch diffusers transformers accelerate
```

---

## Quick start

Using the included sample chapter and **placeholder** frames (no GPU):

```bash
python main.py --input chapter.txt --outdir outputs/demo1 --title "Chapter 1"
```

You’ll get:

- `outputs/demo1/storyboard.json`
- `outputs/demo1/subtitles.srt`
- `outputs/demo1/frames/frame_0001.png` …

The script then prints an FFmpeg command; copy-paste it (and adjust paths if needed) to generate the final video with burned-in subtitles.

---

## Input format

- **File:** Plain text (`.txt`), UTF-8.
- **Sentences:** Split on `。！？.!?` followed by space/newline, or on newlines. Each resulting segment becomes one shot.
- **Example:** A paragraph with multiple sentences separated by `。` or `!` will produce one shot per sentence.

---

## Usage

```text
python main.py --input <path> --outdir <path> [options]
```

### General options

| Option | Default | Description |
|--------|---------|-------------|
| `--input` | *(required)* | Path to chapter text file (`.txt`) |
| `--outdir` | *(required)* | Output directory for storyboard, frames, SRT |
| `--title` | `"Chapter 1"` | Chapter title (overlays and metadata) |
| `--seconds-per-sentence` | `5.0` | Duration per sentence in seconds (min 1.5) |
| `--orientation` | `portrait` | `portrait` (9:16) or `landscape` (16:9) |
| `--renderer` | `placeholder` | `placeholder` (Pillow) or `sd` (Stable Diffusion) |

### Stable Diffusion options (when `--renderer sd`)

| Option | Default | Description |
|--------|---------|-------------|
| `--sd-model-id` | `runwayml/stable-diffusion-v1-5` | Hugging Face model ID (e.g. `stabilityai/sd-turbo`) |
| `--sd-steps` | `25` | Number of inference steps |
| `--sd-guidance` | `7.5` | Classifier-free guidance scale |
| `--sd-seed` | `42` | Base seed (per-shot seed = base + shot index) |
| `--sd-neg` | *(see below)* | Negative prompt |
| `--sd-max-side` | `1024` | Max side length in px (reduces VRAM; image upscaled to canvas) |

Default negative prompt: `low quality, blurry, bad anatomy, extra limbs, text, watermark, logo`.

### Examples

```bash
# Placeholder only, portrait, 5s per sentence
python main.py --input chapter.txt --outdir outputs/demo1

# Shorter shots, landscape
python main.py --input chapter.txt --outdir outputs/demo1_land --seconds-per-sentence 4 --orientation landscape

# Custom title
python main.py --input chapter.txt --outdir outputs/demo1 --title "Prologue"

# Stable Diffusion (GPU/MPS); use HF_TOKEN for gated models
python main.py --input chapter.txt --outdir outputs/demo1_sd --renderer sd

# SD with fewer steps and smaller max side for low VRAM
python main.py --input chapter.txt --outdir outputs/demo1_sd --renderer sd --sd-steps 20 --sd-max-side 512
```

---

## Output files

| File | Description |
|------|-------------|
| `storyboard.json` | Storyboard: `chapter_title`, `orientation`, `width`, `height`, `total_duration`, and a `shots` array. Each shot: `idx`, `text`, `duration`, `camera_move`, `scene`, `characters`, `prompt`. |
| `subtitles.srt` | Standard SRT: index, time range (`HH:MM:SS,mmm --> ...`), and wrapped text per shot. |
| `frames/frame_0001.png` … | One PNG per shot; size matches orientation (1080×1920 or 1920×1080). Placeholder: header + camera + prompt text. SD: generated image. |
| *(printed)* | FFmpeg command: step 1 concats frames with per-shot duration into a temp video; step 2 burns subtitles and writes final MP4. A `.concat.txt` file is also written next to the output MP4 path. |

---

## Environment variables

Secrets are read from the environment (and from `.env` if `python-dotenv` is installed). **Do not commit `.env`**; it is in `.gitignore`.

| Variable | Purpose |
|----------|---------|
| `HF_TOKEN` | Hugging Face token for gated/private models or higher rate limits. Create at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). |

Setup:

1. Copy `.env.example` to `.env`.
2. Add `HF_TOKEN=your_token_here` (only needed for SD with gated models or to avoid rate limits).
3. If you use `pip install python-dotenv`, `.env` is loaded automatically when you run `main.py`.

---

## Stable Diffusion

- **Device:** Auto-detected order: CUDA → Apple MPS → CPU.
- **Precision:** FP16 on CUDA/MPS when available.
- **Memory:** Attention slicing is enabled to reduce peak VRAM. Use `--sd-max-side` (e.g. 512 or 768) on low-VRAM GPUs.
- **Models:** Default is `runwayml/stable-diffusion-v1-5`. You can use e.g. `stabilityai/sd-turbo` for fewer steps; set `--sd-model-id` accordingly.
- **Token:** For gated or private models, set `HF_TOKEN` in `.env` or the environment.

---

## FFmpeg: rendering the final video

After running `main.py`, the script prints a two-step FFmpeg command.

1. **Step 1:** Build a silent video from the frame sequence using a concat demuxer and per-shot durations (the `.concat.txt` lists each `frame_XXXX.png` and its `duration`). Output: `temp_video.mp4`.
2. **Step 2:** Burn subtitles from `subtitles.srt` into `temp_video.mp4` and write the final MP4 (e.g. `novelmotion_portrait.mp4`) with AAC audio placeholder.

Paths in the command are absolute or relative to where you run FFmpeg; adjust if you run it from another directory. You can replace step 2 with your own audio/TTS/BGM pipeline later.

---

## Project structure

```text
NovelMotion/
├── main.py              # CLI: storyboard, frames, SRT, FFmpeg command
├── chapter.txt          # Sample chapter (input)
├── requirements.txt    # Pillow, python-dotenv; optional SD deps commented
├── .env.example         # Template for .env (copy to .env; do not commit)
├── .gitignore
├── LICENSE              # MIT
└── README.md
```

Generated outputs (e.g. `outputs/`, `temp_video.mp4`, `*.concat.txt`) are in `.gitignore` so the repo stays clean for public sharing.

---

## Roadmap

- **Current (MVP):** Text → storyboard → placeholder or SD frames → SRT → FFmpeg command.
- **Planned:** LLM-driven image prompts, TTS/BGM, audio mixing, optional ComfyUI/SD integration; replace placeholder pipeline with richer rendering.

---

## License

MIT. See [LICENSE](LICENSE).
