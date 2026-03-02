from __future__ import annotations
from pathlib import Path
import textwrap
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
from storyboard import Storyboard

def export_placeholder_frames(storyboard: Storyboard, frames_dir: Path) -> None:
    if Image is None: raise RuntimeError("Please `pip install pillow`.")
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        font_title = ImageFont.truetype("arial.ttf", 64)
        font_body  = ImageFont.truetype("arial.ttf", 38)
        font_small = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font_title = font_body = font_small = ImageFont.load_default()

    W,H = storyboard.width, storyboard.height
    for shot in storyboard.shots:
        img = Image.new("RGB",(W,H),(18,18,24)); draw = ImageDraw.Draw(img)
        header_h = int(H*0.12); draw.rectangle([(0,0),(W,header_h)], fill=(40,40,60))
        title = f"{storyboard.chapter_title} — Shot {shot.idx:02d}"
        draw.text((40,30), title, fill=(255,255,255), font=font_title)
        tag = f"CAM: {shot.camera_move}   DUR: {shot.duration:.1f}s"
        draw.text((40, header_h+20), tag, fill=(220,220,220), font=font_small)
        prompt_text = textwrap.fill(shot.prompt, width=50)
        draw.text((40, header_h+80), prompt_text, fill=(230,230,240), font=font_body)
        footer = "NovelMotion Placeholder — Replace with SD/ComfyUI render"
        draw.text((W-520, H-50), footer, fill=(180,180,200), font=font_small)
        img.save(frames_dir / f"frame_{shot.idx:04d}.png")