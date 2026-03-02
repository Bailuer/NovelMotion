from __future__ import annotations
import os, argparse
from pathlib import Path
from storyboard import Storyboard, Shot, split_into_sentences, sentences_to_shots, smooth_camera_moves, infer_dimensions
from llm import build_prompts_with_llm, load_character_cards, STYLE_PRESETS
from placeholder import export_placeholder_frames
from sd_renderer import render_frames_with_sd
from io_utils import export_srt, export_storyboard_json, export_shots_csv
from ffmpeg_utils import suggest_ffmpeg_command, render_with_ffmpeg
from utils import env

def build_storyboard(title: str, chapter_text: str, seconds_per_sentence: float, orientation: str, shots: list[Shot]|None=None) -> Storyboard:
    width, height = infer_dimensions(orientation)
    if shots is None:
        shots = sentences_to_shots(split_into_sentences(chapter_text), seconds_per_sentence)
    smooth_camera_moves(shots)
    return Storyboard(chapter_title=title or "Chapter", orientation=orientation, width=width, height=height, shots=shots)

def main():
    p = argparse.ArgumentParser(description="NovelMotion CLI")
    p.add_argument("--input", required=True); p.add_argument("--outdir", required=True)
    p.add_argument("--title", default="Chapter 1"); p.add_argument("--seconds-per-sentence", type=float, default=5.0)
    p.add_argument("--orientation", choices=["portrait","landscape"], default="portrait")
    p.add_argument("--renderer", choices=["placeholder","sd"], default="placeholder")
    p.add_argument("--sd-model-id", default="runwayml/stable-diffusion-v1-5")
    p.add_argument("--sd-steps", type=int, default=25); p.add_argument("--sd-guidance", type=float, default=7.5)
    p.add_argument("--sd-seed", type=int, default=42)
    p.add_argument("--sd-neg", default="low quality, blurry, bad anatomy, extra limbs, text, watermark, logo")
    p.add_argument("--sd-max-side", type=int, default=1024)
    p.add_argument("--sd-precision", choices=["auto","fp16","fp32"], default="auto")
    p.add_argument("--hf-token", default=None)

    p.add_argument("--prompt-engine", choices=["simple","ai"], default="simple")
    p.add_argument("--llm-provider", "--provider", dest="llm_provider", choices=["openai","gemini"], default=os.getenv("LLM_PROVIDER","openai"))
    p.add_argument("--llm-base-url", default=env("OPENAI_BASE_URL", env("LLM_BASE_URL","https://api.openai.com")))
    p.add_argument("--llm-model", default=env("OPENAI_MODEL", env("LLM_MODEL","gpt-4o-mini")))
    p.add_argument("--llm-api-key", default=env("OPENAI_API_KEY", env("LLM_API_KEY", env("GOOGLE_API_KEY",""))))
    p.add_argument("--llm-lang", choices=["en","zh"], default=env("LLM_LANG","en"))
    p.add_argument("--llm-temp", type=float, default=float(os.getenv("LLM_TEMP","0.4")))
    p.add_argument("--style-pack", choices=list(STYLE_PRESETS.keys()), default=os.getenv("STYLE_PACK",""))
    p.add_argument("--global-style", default=os.getenv("GLOBAL_STYLE",""))
    p.add_argument("--character-cards", default=os.getenv("CHARACTER_CARDS",""))
    p.add_argument("--prompt-debug", action="store_true")
    p.add_argument("--export-shots-csv", action="store_true")
    p.add_argument("--fix-hands-face", action="store_true")
    p.add_argument("--auto-render", action="store_true")

    p.add_argument(
        "--bgm", type=str, default=None,
        help="Path to background music file (mp3/wav)."
    )
    p.add_argument(
        "--bgm-gain", type=float, default=-14.0,
        help="BGM gain in dB (negative lowers volume). Default: -14."
    )
    p.add_argument(
        "--bgm-fade-in", type=float, default=1.0,
        help="Fade-in duration in seconds. Default: 1.0."
    )
    p.add_argument(
        "--bgm-fade-out", type=float, default=2.0,
        help="Fade-out duration in seconds. Default: 2.0."
    )

    args = p.parse_args()
    if args.llm_provider.lower() == "gemini":
        if "generativelanguage.googleapis.com" not in (args.llm_base_url or ""): args.llm_base_url = "https://generativelanguage.googleapis.com"
        if not args.llm_model or args.llm_model.startswith("gpt-"): args.llm_model = "gemini-1.5-flash"
    hf_token = args.hf_token or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")

    style_suffix = ""
    if args.style_pack: style_suffix = STYLE_PRESETS.get(args.style_pack,"")
    if args.global_style: style_suffix = f"{(style_suffix + ', ' if style_suffix else '')}{args.global_style}".strip(", ")
    char_cards = load_character_cards(args.character_cards)

    # lightweight face/hand fix
    if args.fix_hands_face:
        handface_pos = "detailed hands, five fingers on each hand, natural finger pose, clean anatomy, symmetrical hands, refined facial features, detailed eyes, sharp eyes, well-defined iris, beautiful face"
        handface_neg = "bad hands, missing fingers, extra fingers, fused fingers, deformed fingers, long fingers, mangled hands, mutated hands, poorly drawn hands, deformed face, cross-eyed, lazy eye, low-res eyes, asymmetrical eyes"
        style_suffix = f"{(style_suffix + ', ' if style_suffix else '')}{handface_pos}".strip(", ")
        if '--sd-neg' not in os.sys.argv:
            args.sd_neg = f"{args.sd_neg}, {handface_neg}".strip(", ")
        if args.sd_model_id.lower() != "stabilityai/sd-turbo" and args.sd_steps < 12:
            args.sd_steps = 12
        if args.sd_guidance < 6.5 and "anything" in args.sd_model_id.lower():
            args.sd_guidance = 6.5

    chapter_text = Path(args.input).read_text(encoding="utf-8")
    outdir = Path(args.outdir); frames_dir = outdir / "frames"; outdir.mkdir(parents=True, exist_ok=True)

    shots = None
    if args.prompt_engine == "ai" and (args.llm_api_key or ""):
        try:
            shots = build_prompts_with_llm(chapter_text, args.seconds_per_sentence, args.orientation,
                                           args.llm_model, args.llm_base_url, args.llm_api_key,
                                           language=args.llm_lang, provider=args.llm_provider, temperature=args.llm_temp,
                                           style_suffix=style_suffix, character_cards=char_cards,
                                           debug_path=(outdir / "llm_raw.json") if args.prompt_debug else None)
            if not shots: shots = None
        except Exception as e:
            print(f"[warn] LLM prompt generation failed: {e}; falling back to simple.", file=os.sys.stderr); shots=None

    from storyboard import sentences_to_shots, split_into_sentences
    width, height = infer_dimensions(args.orientation)
    if shots is None:
        shots = sentences_to_shots(split_into_sentences(chapter_text), args.seconds_per_sentence)
    sb = Storyboard(chapter_title=args.title, orientation=args.orientation, width=width, height=height, shots=shots)
    from storyboard import smooth_camera_moves; smooth_camera_moves(sb.shots)

    print(f"NM_TOTAL_SHOTS {len(sb.shots)}", flush=True)

    # export
    json_path = outdir / "storyboard.json"; srt_path = outdir / "subtitles.srt"
    export_storyboard_json(sb, json_path); export_srt(sb, srt_path)
    if args.export_shots_csv: export_shots_csv(sb, outdir / "shots.csv")

    if args.renderer == "sd":
        def progress_cb(done: int, total: int):
            # Mirror sd_renderer per-shot progress for UI
            print(f"NM_PROGRESS {done}/{total}", flush=True)
        render_frames_with_sd(
            sb,
            frames_dir,
            model_id=args.sd_model_id,
            steps=args.sd_steps,
            guidance=args.sd_guidance,
            seed=args.sd_seed,
            negative_prompt=args.sd_neg,
            max_side=args.sd_max_side,
            precision=args.sd_precision,
            hf_token=hf_token,
            progress_cb=progress_cb,
        )
    else:
        export_placeholder_frames(sb, frames_dir)

    out_mp4 = outdir / ("novelmotion_portrait.mp4" if args.orientation=="portrait" else "novelmotion_landscape.mp4")
    if args.auto_render:
        print("[ffmpeg] auto-render starting…", flush=True)
        try:
            render_with_ffmpeg(
                sb,
                frames_dir,
                srt_path,
                out_mp4,
                bgm=args.bgm,
                bgm_gain=args.bgm_gain,
                bgm_fade_in=args.bgm_fade_in,
                bgm_fade_out=args.bgm_fade_out,
            )
            print(f"[ffmpeg] auto-render done → {out_mp4}", flush=True)
        except Exception as e:
            print(f"[ffmpeg] auto-render failed: {e}", file=os.sys.stderr)
            # Fallback: print manual command for user to copy
            manual = suggest_ffmpeg_command(sb, frames_dir, srt_path, out_mp4)
            print("\n# Manual fallback — copy & run this:\n" + manual, flush=True)

    cmd = suggest_ffmpeg_command(sb, frames_dir, srt_path, out_mp4)
    print("\n✅ Done. Generated:")
    print(f"  • {json_path}")
    print(f"  • {srt_path}")
    print(f"  • {frames_dir}/frame_0001.png … frame_{len(sb.shots):04d}.png")
    if args.export_shots_csv: print(f"  • {outdir / 'shots.csv'}")
    if args.auto_render: print(f"  • {out_mp4}  (auto-rendered)")
    print(f"\n🔧 Prompt engine: {'AI' if args.prompt_engine=='ai' and (args.llm_api_key or '') else 'simple template'}")
    print(f"🔌 LLM: provider={args.llm_provider}, model={args.llm_model}, base={args.llm_base_url}")
    print(f"🎛️ LLM temp={args.llm_temp}, style_pack='{args.style_pack}', global_style='{args.global_style}'")
    if args.fix_hands_face: print("🖐️ Face/Hands fix: enabled (prompt + negative augmented)")
    if args.character_cards: print(f"👤 Character cards: {args.character_cards} (loaded {len(char_cards)} entries)")
    if args.prompt_debug: print(f"📝 LLM raw JSON saved to: {(outdir / 'llm_raw.json').as_posix()}")
    print("\n📽️ Render with FFmpeg (copy/paste the following):\n"); print(cmd)