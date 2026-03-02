#!/usr/bin/env python3
"""
NovelMotion — Step 1 MVP Pipeline (CLI)
=======================================

Goal of this step
-----------------
Create a *minimal yet useful* Python-only pipeline that turns raw chapter text
into:
  1) A structured storyboard (JSON) made of shots (default 5s per sentence)
  2) Placeholder keyframes (PNG) per shot with legible prompts (for fast demo)
  3) Subtitles file (SRT) aligned to the shot timings
  4) A ready-to-copy FFmpeg command to render the final video (9:16 or 16:9)

Later steps (not in this file) will swap placeholder frames for SD/ComfyUI
renders and add TTS/BGM/audio mixing. This file is dependency-light so you can
run quickly and iterate in VSCode.

Usage
-----
python main.py \
  --input chapter.txt \
  --outdir outputs/demo1 \
  --seconds-per-sentence 5 \
  --orientation portrait  # or landscape

Requires: Pillow (PIL). Install: `pip install -r requirements.txt`.
FFmpeg is not required for generation, but recommended for the final render.

Author: NovelMotion
License: MIT
"""
from __future__ import annotations

import argparse
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
import dataclasses
import json
import math
import os
import re
import textwrap
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:  # Pillow optional until frame export
    Image = None
    ImageDraw = None
    ImageFont = None

# Optional: Stable Diffusion (Diffusers)
try:
    import torch
    from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
    _SD_AVAILABLE = True
except Exception:
    torch = None
    StableDiffusionPipeline = None
    DPMSolverMultistepScheduler = None
    _SD_AVAILABLE = False

# ----------------------------
# Data structures
# ----------------------------

CAMERA_MOVES = ["static", "push", "pull", "pan-left", "pan-right", "tilt-up", "tilt-down"]


@dataclass
class Shot:
    idx: int
    text: str
    duration: float = 5.0
    camera_move: str = "static"
    scene: str = ""
    characters: List[str] = field(default_factory=list)
    prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class Storyboard:
    chapter_title: str
    orientation: str  # 'portrait' or 'landscape'
    width: int
    height: int
    shots: List[Shot]

    @property
    def total_duration(self) -> float:
        return float(sum(s.duration for s in self.shots))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter_title": self.chapter_title,
            "orientation": self.orientation,
            "width": self.width,
            "height": self.height,
            "total_duration": self.total_duration,
            "shots": [s.to_dict() for s in self.shots],
        }


# ----------------------------
# Text → sentences → shots
# ----------------------------

SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s+|\n+")


def split_into_sentences(text: str) -> List[str]:
    # Normalize spaces and trim
    t = re.sub(r"\s+", " ", text.strip())
    if not t:
        return []
    parts = re.split(SENTENCE_SPLIT_RE, t)
    # Remove blanks and keep reasonable length
    parts = [p.strip() for p in parts if p and p.strip()]
    return parts


def choose_camera_move(i: int) -> str:
    # Simple deterministic cycle for now
    return CAMERA_MOVES[i % len(CAMERA_MOVES)]


def build_prompt_from_sentence(sentence: str) -> str:
    # Very lightweight prompt draft (to be replaced by LLM-driven prompt later)
    # Keep it short for placeholder frames
    return (
        "Anime style, dramatic lighting, rich background, cinematic composition, "
        + sentence[:160]
    )


def sentences_to_shots(sentences: List[str], seconds_per_sentence: float) -> List[Shot]:
    shots: List[Shot] = []
    for i, s in enumerate(sentences, start=1):
        shots.append(
            Shot(
                idx=i,
                text=s,
                duration=max(1.5, float(seconds_per_sentence)),
                camera_move=choose_camera_move(i - 1),
                prompt=build_prompt_from_sentence(s),
            )
        )
    return shots


# ----------------------------
# Stable Diffusion renderer (optional)
# ----------------------------

def _pick_device() -> str:
    # Prefer CUDA, then Apple MPS, else CPU
    try:
        if torch is None:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and getattr(torch.backends.mps, "is_available", lambda: False)():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _round_to_mult8(x: int) -> int:
    # SD UNet prefers dimensions divisible by 8
    return int((x // 8) * 8)

# Helper: scale to max side, preserving aspect ratio, round to multiple of 8
def _scale_to_max_side(w: int, h: int, max_side: int) -> Tuple[int, int]:
    # Keep aspect ratio; cap the longer side to max_side; round to multiple of 8.
    if max(w, h) <= max_side:
        return _round_to_mult8(w), _round_to_mult8(h)
    if w >= h:
        scale = max_side / float(w)
    else:
        scale = max_side / float(h)
    new_w = _round_to_mult8(int(w * scale))
    new_h = _round_to_mult8(int(h * scale))
    new_w = max(8, new_w)
    new_h = max(8, new_h)
    return new_w, new_h


def render_frames_with_sd(
    storyboard: Storyboard,
    frames_dir: Path,
    model_id: str = "runwayml/stable-diffusion-v1-5",
    steps: int = 25,
    guidance: float = 7.5,
    seed: int = 42,
    negative_prompt: str = "low quality, blurry, bad anatomy, extra limbs, text, watermark, logo",
    max_side: int = 1024,  # cap the longer side during generation (helps MPS/VRAM)
) -> None:
    if not _SD_AVAILABLE:
        raise RuntimeError(
            "Stable Diffusion not available. Please `pip install diffusers transformers accelerate torch` "
            "and ensure a compatible PyTorch (CUDA or MPS) is installed."
        )

    frames_dir.mkdir(parents=True, exist_ok=True)
    device = _pick_device()

    use_fp16 = _pick_device() in ("cuda", "mps")
    hf_token = os.environ.get("HF_TOKEN") or None
    pipe = StableDiffusionPipeline.from_pretrained(
        model_id,
        torch_dtype=torch.float16 if use_fp16 else None,
        token=hf_token,
    )
    # Switch scheduler for faster/cleaner inference
    try:
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    except Exception:
        pass

    # Memory tweaks: fp16 on GPU/MPS + attention slicing to lower peak RAM
    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass

    pipe = pipe.to(device)

    W, H = storyboard.width, storyboard.height
    # Generate at a smaller size (preserve AR), then resize up to canvas.
    gen_w, gen_h = _scale_to_max_side(W, H, max_side)
    W8, H8 = _round_to_mult8(gen_w), _round_to_mult8(gen_h)

    # Reusable generator per device for deterministic seeds
    gen_base = torch.Generator(device=device)
    for shot in storyboard.shots:
        # Per-shot seed for deterministic-but-varied frames
        gen = gen_base.manual_seed(int(seed) + int(shot.idx))

        # Enrich prompt with simple camera hints
        cam_hint = {
            "static": "static shot, centered composition",
            "push": "dolly zoom in, subject larger in frame",
            "pull": "zoom out, reveal background",
            "pan-left": "pan left motion blur streaks",
            "pan-right": "pan right motion blur streaks",
            "tilt-up": "tilt up perspective",
            "tilt-down": "tilt down perspective",
        }.get(shot.camera_move, "cinematic framing")

        full_prompt = f"{shot.prompt}, {cam_hint}"
        image = pipe(
            prompt=full_prompt,
            negative_prompt=negative_prompt,
            height=H8,
            width=W8,
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            generator=gen,
        ).images[0]

        # Always fit to final canvas size to match subtitles/layout
        if (gen_w, gen_h) != (W, H):
            image = image.resize((W, H))

        out_path = frames_dir / f"frame_{shot.idx:04d}.png"
        image.save(out_path)


# ----------------------------
# Exports: frames, SRT, JSON
# ----------------------------


def seconds_to_srt_ts(seconds: float) -> str:
    td = timedelta(seconds=float(seconds))
    # Format as HH:MM:SS,mmm
    total_ms = int(td.total_seconds() * 1000)
    hh = total_ms // 3_600_000
    rem = total_ms % 3_600_000
    mm = rem // 60_000
    rem = rem % 60_000
    ss = rem // 1000
    ms = rem % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def export_srt(storyboard: Storyboard, out_path: Path) -> None:
    t = 0.0
    lines = []
    for shot in storyboard.shots:
        start = t
        end = t + shot.duration
        t = end
        lines.append(str(shot.idx))
        lines.append(f"{seconds_to_srt_ts(start)} --> {seconds_to_srt_ts(end)}")
        # Wrap text to avoid overly long single lines in players
        wrapped = textwrap.fill(shot.text, width=28)
        lines.append(wrapped)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


# Minimal, readable placeholder frames so you can demo immediately
# They include: shot number, camera move, and the (shortened) prompt

def export_placeholder_frames(storyboard: Storyboard, frames_dir: Path) -> None:
    if Image is None:
        raise RuntimeError("Pillow is not installed. Please `pip install pillow`.\n")

    frames_dir.mkdir(parents=True, exist_ok=True)

    # Try to pick a reasonable font; fall back to default
    try:
        font_title = ImageFont.truetype("arial.ttf", 64)
        font_body = ImageFont.truetype("arial.ttf", 38)
        font_small = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_small = ImageFont.load_default()

    W, H = storyboard.width, storyboard.height

    for shot in storyboard.shots:
        img = Image.new("RGB", (W, H), color=(18, 18, 24))
        draw = ImageDraw.Draw(img)

        # Frame header band
        header_h = int(H * 0.12)
        draw.rectangle([(0, 0), (W, header_h)], fill=(40, 40, 60))

        # Title: chapter + shot idx
        title = f"{storyboard.chapter_title} — Shot {shot.idx:02d}"
        draw.text((40, 30), title, fill=(255, 255, 255), font=font_title)

        # Camera move tag
        tag = f"CAM: {shot.camera_move}   DUR: {shot.duration:.1f}s"
        draw.text((40, header_h + 20), tag, fill=(220, 220, 220), font=font_small)

        # Prompt block (wrapped)
        prompt_text = textwrap.fill(shot.prompt, width=50)
        draw.text((40, header_h + 80), prompt_text, fill=(230, 230, 240), font=font_body)

        # Footer line
        footer = f"NovelMotion Placeholder — Replace with SD/ComfyUI render"
        tw, th = draw.textlength(footer, font=font_small), font_small.size
        draw.text((W - tw - 40, H - th - 30), footer, fill=(180, 180, 200), font=font_small)

        out_path = frames_dir / f"frame_{shot.idx:04d}.png"
        img.save(out_path)


def export_storyboard_json(storyboard: Storyboard, out_path: Path) -> None:
    out_path.write_text(json.dumps(storyboard.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------
# FFmpeg helper
# ----------------------------


def suggest_ffmpeg_command(storyboard: Storyboard, frames_dir: Path, srt_path: Path, out_mp4: Path, fps: int = 30) -> str:
    # We will generate a concat-friendly list with per-frame duration using -framerate and -r
    # Simpler: convert each shot to N identical frames proportional to duration? Not efficient.
    # For MVP we use a filter that holds each PNG for `duration` seconds via `loop` is hard.
    # Pragmatic approach: make an image sequence at 1 frame per shot, then use `tpad` to set duration — but subtitles need stable timeline.
    # Instead we will advise a moviepy/ffmpeg method that respects durations via `-pattern_type glob` and `-r` plus `-vf tpad`.
    # To keep things robust for users, we suggest a per-shot concat file.

    concat_txt = out_mp4.with_suffix(".concat.txt")
    with concat_txt.open("w", encoding="utf-8") as f:
        for shot in storyboard.shots:
            img_name = f"frame_{shot.idx:04d}.png"
            f.write(f"file '{(frames_dir / img_name).as_posix()}'\n")
            # Each image is looped for `duration` seconds using `-loop 1` per input in concat demuxer is not supported;
            # So we emulate by writing the same line then `duration` — concat demuxer supports `duration` directive.
            # NOTE: Rounding to 3 decimals for stability.
            f.write(f"duration {shot.duration:.3f}\n")
        # Last file listed twice to set exact stream duration
        last_img = (frames_dir / f"frame_{storyboard.shots[-1].idx:04d}.png").as_posix()
        f.write(f"file '{last_img}'\n")

    vf_scale = f"scale={storyboard.width}:{storyboard.height}:force_original_aspect_ratio=decrease,pad={storyboard.width}:{storyboard.height}:(ow-iw)/2:(oh-ih)/2"

    cmd = (
        "# 1) Create silent video from frames with per-shot durations\n"
        f"ffmpeg -y -f concat -safe 0 -i '{concat_txt.as_posix()}' -vsync vfr -pix_fmt yuv420p -vf \"{vf_scale}\" temp_video.mp4\n\n"  # noqa: E501
        "# 2) Burn subtitles (or keep as soft subs by moving -vf to -vf subtitles)")

    cmd += (
        f"\nffmpeg -y -i temp_video.mp4 -vf \"subtitles='{srt_path.as_posix()}'\" -c:a aac -b:a 192k -movflags +faststart '{out_mp4.as_posix()}'\n"
        "# Tip: replace step 2 with audio mixing once TTS/BGM files exist.\n"
    )
    return cmd


# ----------------------------
# Orchestration
# ----------------------------


def infer_dimensions(orientation: str) -> Tuple[int, int]:
    if orientation == "portrait":
        return 1080, 1920
    else:
        return 1920, 1080


def build_storyboard(title: str, chapter_text: str, seconds_per_sentence: float, orientation: str) -> Storyboard:
    width, height = infer_dimensions(orientation)
    sentences = split_into_sentences(chapter_text)
    shots = sentences_to_shots(sentences, seconds_per_sentence)
    return Storyboard(
        chapter_title=title or "Chapter",
        orientation=orientation,
        width=width,
        height=height,
        shots=shots,
    )


def main():
    parser = argparse.ArgumentParser(description="NovelMotion — Step 1 MVP: text → storyboard/frames/srt")
    parser.add_argument("--input", required=True, help="Path to a .txt file with the chapter text")
    parser.add_argument("--outdir", required=True, help="Output directory for assets")
    parser.add_argument("--title", default="Chapter 1", help="Chapter title for overlays/metadata")
    parser.add_argument("--seconds-per-sentence", type=float, default=5.0, help="Default duration per sentence")
    parser.add_argument("--orientation", choices=["portrait", "landscape"], default="portrait", help="Aspect orientation")
    parser.add_argument("--renderer", choices=["placeholder", "sd"], default="placeholder", help="Frame renderer: placeholder (Pillow) or sd (Stable Diffusion)")
    parser.add_argument("--sd-model-id", default="runwayml/stable-diffusion-v1-5", help="Hugging Face model id for Stable Diffusion (e.g., 'runwayml/stable-diffusion-v1-5', 'stabilityai/sd-turbo')")
    parser.add_argument("--sd-steps", type=int, default=25, help="Stable Diffusion inference steps")
    parser.add_argument("--sd-guidance", type=float, default=7.5, help="Classifier-free guidance scale")
    parser.add_argument("--sd-seed", type=int, default=42, help="Base seed for per-shot generation")
    parser.add_argument("--sd-neg", default="low quality, blurry, bad anatomy, extra limbs, text, watermark, logo", help="Negative prompt")
    parser.add_argument("--sd-max-side", type=int, default=1024, help="Cap the longer side (in px) during SD generation to reduce VRAM usage; final image is upscaled to canvas.")

    args = parser.parse_args()

    chapter_text = Path(args.input).read_text(encoding="utf-8")
    outdir = Path(args.outdir)
    frames_dir = outdir / "frames"
    outdir.mkdir(parents=True, exist_ok=True)

    storyboard = build_storyboard(
        title=args.title,
        chapter_text=chapter_text,
        seconds_per_sentence=args.seconds_per_sentence,
        orientation=args.orientation,
    )

    # Exports
    json_path = outdir / "storyboard.json"
    srt_path = outdir / "subtitles.srt"
    export_storyboard_json(storyboard, json_path)
    export_srt(storyboard, srt_path)
    if args.renderer == "sd":
        render_frames_with_sd(
            storyboard=storyboard,
            frames_dir=frames_dir,
            model_id=args.sd_model_id,
            steps=args.sd_steps,
            guidance=args.sd_guidance,
            seed=args.sd_seed,
            negative_prompt=args.sd_neg,
            max_side=args.sd_max_side,
        )
    else:
        export_placeholder_frames(storyboard, frames_dir)

    # FFmpeg instructions
    out_mp4 = outdir / ("novelmotion_portrait.mp4" if args.orientation == "portrait" else "novelmotion_landscape.mp4")
    cmd = suggest_ffmpeg_command(storyboard, frames_dir, srt_path, out_mp4)

    print("\n✅ Done. Generated:")
    print(f"  • {json_path}")
    print(f"  • {srt_path}")
    print(f"  • {frames_dir}/frame_0001.png … frame_{len(storyboard.shots):04d}.png")
    print("\n📽️ Render with FFmpeg (copy/paste the following):\n")
    print(cmd)


if __name__ == "__main__":
    main()
