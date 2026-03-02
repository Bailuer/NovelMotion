from __future__ import annotations
from pathlib import Path
from typing import Tuple, Callable, Optional
try:
    import torch
    from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
except Exception:
    torch = None
from storyboard import Storyboard
from utils import pick_device, round_to_mult8, scale_to_max_side, clip_truncate


# Helper to load SD pipeline from repo/dir or single-file (safetensors/ckpt/URL)
def _load_sd_pipe(model_id: str, use_fp16: bool, hf_token: Optional[str]):
    """
    Load SD pipeline from either a diffusers repo/dir or a single-file safetensors/ckpt/URL.
    Avoids model_index.json 404 for repos that only host .safetensors (e.g., gsdf/Counterfeit-V3.0).
    """
    if torch is None:
        raise RuntimeError("torch/diffusers not available")
    dtype = torch.float16 if use_fp16 else torch.float32
    is_single = (
        model_id.startswith("http://")
        or model_id.startswith("https://")
        or model_id.endswith(".safetensors")
        or model_id.endswith(".ckpt")
    )
    if is_single:
        # Handle Hugging Face 'resolve/main' URLs explicitly: download to local cache first
        local_path = None
        if (model_id.startswith("https://huggingface.co/") or model_id.startswith("http://huggingface.co/")) and "/resolve/" in model_id:
            try:
                # Parse repo_id and filename from the URL
                # e.g. https://huggingface.co/gsdf/Counterfeit-V3.0/resolve/main/Counterfeit-V3.0_fix_fp16.safetensors
                parts = model_id.split("huggingface.co/", 1)[1].split("/")
                repo_id = "/".join(parts[0:2])  # gsdf/Counterfeit-V3.0
                # parts may be [..., 'resolve', 'main', 'filename']
                if "resolve" in parts:
                    idx = parts.index("resolve")
                    filename = "/".join(parts[idx+2:])  # skip 'resolve' and revision
                else:
                    filename = parts[-1]
                from huggingface_hub import hf_hub_download
                local_path = hf_hub_download(repo_id=repo_id, filename=filename, revision="main", token=hf_token)
            except Exception:
                local_path = None
        pipe = StableDiffusionPipeline.from_single_file(
            local_path if local_path else model_id,
            torch_dtype=dtype,
            use_safetensors=True,
            token=hf_token,
        )
    else:
        pipe = StableDiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=dtype,
            token=hf_token,
        )
    # Prefer a DPM-Solver scheduler (close to DPM++ 2M Karras)
    try:
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    except Exception:
        pass
    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass
    return pipe

def render_frames_with_sd(
    storyboard: Storyboard, frames_dir: Path, *,
    model_id: str, steps: int, guidance: float, seed: int,
    negative_prompt: str, max_side: int, precision: str, hf_token: str|None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    if torch is None:
        raise RuntimeError("Install diffusers/transformers/accelerate/torch first.")
    frames_dir.mkdir(parents=True, exist_ok=True)
    device = pick_device()

    if precision not in ("auto","fp16","fp32"): precision = "auto"
    use_fp16 = (precision=="fp16") or (precision=="auto" and device=="cuda")

    pipe = _load_sd_pipe(model_id, use_fp16, hf_token)
    try: pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    except Exception: pass
    try: pipe.enable_attention_slicing()
    except Exception: pass
    pipe = pipe.to(device)
    try:
        if hasattr(pipe,"enable_vae_slicing"): pipe.enable_vae_slicing()
        if hasattr(pipe,"enable_vae_tiling"): pipe.enable_vae_tiling()
    except Exception: pass
    if device == "mps":
        try: pipe.upcast_vae()
        except Exception:
            try: pipe.vae = pipe.vae.to(dtype=torch.float32)
            except Exception: pass

    W,H = storyboard.width, storyboard.height
    gen_w, gen_h = scale_to_max_side(W,H,max_side)
    W8, H8 = round_to_mult8(gen_w), round_to_mult8(gen_h)

    gen_base = torch.Generator(device=device)
    total = len(storyboard.shots)
    done = 0
    total_units = total * int(steps)
    done_units = 0
    # Announce total units (shots * steps) for fine-grained progress in UI
    print(f"NM_TOTAL_UNITS {total_units}", flush=True)

    def _unit_cb(step: int, timestep: int, kwargs=None):
        nonlocal done_units, total_units
        done_units += 1
        # Fine-grained per-step progress
        print(f"NM_UNITS {done_units}/{total_units}", flush=True)
    for shot in storyboard.shots:
        gen = gen_base.manual_seed(int(seed) + int(shot.idx))

        cam_hint = {
            "static":"static shot, centered composition", "push":"dolly zoom in, subject larger in frame",
            "pull":"zoom out, reveal background", "pan-left":"pan left motion blur streaks",
            "pan-right":"pan right motion blur streaks", "tilt-up":"tilt up perspective", "tilt-down":"tilt down perspective"
        }.get(shot.camera_move,"cinematic framing")

        sfw_suffix = ", safe for work, fully clothed, modest attire, covered shoulders and legs, PG-13"
        full_prompt = clip_truncate(f"{shot.prompt}, {cam_hint}{sfw_suffix}", pipe.tokenizer)
        neg_full = (negative_prompt + ", nsfw, nude, naked, nipples, breasts, bikini, lingerie, underwear, cleavage").strip(", ")

        out = pipe(
            prompt=full_prompt,
            negative_prompt=neg_full,
            height=H8, width=W8,
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            generator=gen,
            return_dict=True,
            callback=_unit_cb,
            callback_steps=1,
        )
        image = out.images[0]
        flagged = False
        try: flagged = bool(getattr(out, "nsfw_content_detected", [False])[0])
        except Exception: pass
        if flagged:
            safer_suffix = ", more clothes, long sleeves, no skin exposure, conservative outfit"
            retry_prompt = clip_truncate(full_prompt + safer_suffix, pipe.tokenizer)
            gen_retry = torch.Generator(device=device).manual_seed(int(seed) + int(shot.idx) + 999)
            out2 = pipe(
                prompt=retry_prompt,
                negative_prompt=neg_full + ", nsfw, naked",
                height=H8, width=W8,
                num_inference_steps=int(steps),
                guidance_scale=float(guidance),
                generator=gen_retry,
                return_dict=True,
                callback=_unit_cb,
                callback_steps=1,
            )
            image = out2.images[0]

        if (gen_w, gen_h) != (W,H): image = image.resize((W,H))
        image.save(frames_dir / f"frame_{shot.idx:04d}.png")
        done += 1
        if progress_cb is not None:
            try:
                progress_cb(done, total)
            except Exception:
                pass
        else:
            print(f"NM_PROGRESS {done}/{total}", flush=True)