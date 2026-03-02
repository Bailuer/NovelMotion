from __future__ import annotations
import sys, shutil, subprocess
from pathlib import Path
from storyboard import Storyboard

def suggest_ffmpeg_command(sb: Storyboard, frames_dir: Path, srt_path: Path, out_mp4: Path) -> str:
    concat_file = out_mp4.with_suffix(".concat.txt")
    with concat_file.open("w", encoding="utf-8") as f:
        for shot in sb.shots:
            img = (frames_dir / f"frame_{shot.idx:04d}.png").resolve().as_posix()
            f.write(f"file '{img}'\n"); f.write(f"duration {shot.duration:.3f}\n")
        last_img = (frames_dir / f"frame_{sb.shots[-1].idx:04d}.png").resolve().as_posix()
        f.write(f"file '{last_img}'\n")
    vf_scale = f"scale={sb.width}:{sb.height}:force_original_aspect_ratio=decrease,pad={sb.width}:{sb.height}:(ow-iw)/2:(oh-ih)/2"
    cmd = (
        "# 1) Create silent video from frames with per-shot durations\n"
        f"ffmpeg -y -f concat -safe 0 -i '{concat_file.as_posix()}' -fps_mode vfr -pix_fmt yuv420p -vf \"{vf_scale}\" temp_video.mp4\n\n"
        "# 2) Burn subtitles (or keep as soft subs by moving -vf to -vf subtitles)\n"
        f"ffmpeg -y -i temp_video.mp4 -vf \"subtitles='{srt_path.as_posix()}'\" -c:a aac -b:a 192k -movflags +faststart '{out_mp4.as_posix()}'\n"
        "# Tip: replace step 2 with audio mixing once TTS/BGM files exist.\n"
    )
    cmd += (
        "\n# Optional: add background music (looped to video duration)\n"
        "# 1) Loop and trim BGM to match video length, with fade in/out and lower volume\n"
        "# ffmpeg -y -stream_loop -1 -i path/to/bgm.mp3 -t <VIDEO_SECONDS> -ac 2 "
        "#   -af \"atrim=0:<VIDEO_SECONDS>,asetpts=N/SR/TB,afade=t=in:st=0:d=1,afade=t=out:st=<VIDEO_SECONDS-2>:d=2,volume=0.2\" bgm_looped.wav\n"
        "# 2) Burn subtitles and mux BGM\n"
        "# ffmpeg -y -i temp_video.mp4 -i bgm_looped.wav -map 0:v:0 -map 1:a:0 "
        "#   -vf \"subtitles='" + srt_path.as_posix() + "'\" -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart '" + out_mp4.as_posix() + "'\n"
    )
    return cmd

def render_with_ffmpeg(
    sb: Storyboard,
    frames_dir: Path,
    srt_path: Path,
    out_mp4: Path,
    *,
    bgm: str | Path | None = None,
    bgm_gain: float = -14.0,
    bgm_fade_in: float = 1.0,
    bgm_fade_out: float = 2.0,
    **kwargs,
) -> None:
    """
    Render frames to a video, burn subtitles, and (optionally) loop/mix a BGM file to the total duration.
    - bgm: optional path to an mp3/wav file
    - bgm_gain: negative dB reduces the BGM loudness (e.g., -14 dB)
    - bgm_fade_in / bgm_fade_out: fade durations in seconds
    """
    # Backward compatibility for old parameter names
    if "bgm_path" in kwargs and bgm is None:
        bgm = kwargs["bgm_path"]
    if "bgm_gain_db" in kwargs and bgm_gain == -14.0:
        bgm_gain = kwargs["bgm_gain_db"]
    if shutil.which("ffmpeg") is None:
        print("[warn] ffmpeg not found in PATH; skipping auto render. Install: `brew install ffmpeg`", file=sys.stderr)
        return
    concat_file = out_mp4.with_suffix(".concat.txt")
    with concat_file.open("w", encoding="utf-8") as f:
        for shot in sb.shots:
            img = (frames_dir / f"frame_{shot.idx:04d}.png").resolve().as_posix()
            f.write(f"file '{img}'\n"); f.write(f"duration {shot.duration:.3f}\n")
        last_img = (frames_dir / f"frame_{sb.shots[-1].idx:04d}.png").resolve().as_posix()
        f.write(f"file '{last_img}'\n")
    vf_scale = f"scale={sb.width}:{sb.height}:force_original_aspect_ratio=decrease,pad={sb.width}:{sb.height}:(ow-iw)/2:(oh-ih)/2"
    temp_mp4 = out_mp4.parent / "temp_video.mp4"
    # Step 1: silent video from frames with durations
    cmd1 = ["ffmpeg","-y","-f","concat","-safe","0","-i",concat_file.as_posix(),"-fps_mode","vfr","-pix_fmt","yuv420p","-vf",vf_scale,temp_mp4.as_posix()]
    subprocess.run(cmd1, check=True)

    # Optional: prepare BGM loop to the total duration
    looped_bgm = None
    if bgm is not None:
        dur = float(sb.total_duration)
        looped_bgm = out_mp4.parent / "bgm_looped.wav"
        # Build audio filter: trim to duration, fade in/out, set volume, ensure 2ch
        linear_gain = 10 ** (bgm_gain / 20.0)
        af = f"atrim=0:{dur:.3f},asetpts=N/SR/TB,afade=t=in:st=0:d={max(0.0,bgm_fade_in):.3f},afade=t=out:st={max(0.0,dur - max(0.0,bgm_fade_out)):.3f}:d={max(0.0,bgm_fade_out):.3f},volume={linear_gain:.5f}"
        cmd_bgm = ["ffmpeg","-y","-stream_loop","-1","-i",str(bgm),"-t",f"{dur:.3f}","-ac","2","-af",af,looped_bgm.as_posix()]
        subprocess.run(cmd_bgm, check=True)

    # Step 2: burn subtitles and (optionally) add BGM as audio
    if looped_bgm is None:
        cmd2 = ["ffmpeg","-y","-i",temp_mp4.as_posix(),"-vf",f"subtitles='{srt_path.as_posix()}'","-c:a","aac","-b:a","192k","-movflags","+faststart",out_mp4.as_posix()]
    else:
        # Map video from temp, audio from looped bgm
        cmd2 = ["ffmpeg","-y","-i",temp_mp4.as_posix(),"-i",looped_bgm.as_posix(),"-map","0:v:0","-map","1:a:0","-vf",f"subtitles='{srt_path.as_posix()}'","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",out_mp4.as_posix()]
    subprocess.run(cmd2, check=True)
    print(f"[ffmpeg] render complete → {out_mp4.as_posix()}")