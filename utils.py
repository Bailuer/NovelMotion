from __future__ import annotations
import os, torch
from typing import Tuple

def env(key: str, default: str | None = None) -> str | None:
    v = os.getenv(key)
    return v if v not in ("", None) else default

def pick_device() -> str:
    try:
        if torch.cuda.is_available(): return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available(): return "mps"
    except Exception: pass
    return "cpu"


# Round up to nearest multiple of 8 (required by many image models)
def round_to_mult8(x: int) -> int:
    x = int(x)
    return ((x + 7) // 8) * 8

def scale_to_max_side(w: int, h: int, max_side: int) -> Tuple[int,int]:
    if max(w, h) <= max_side:
        return round_to_mult8(w), round_to_mult8(h)
    scale = max_side / float(max(w, h))
    new_w = max(8, round_to_mult8(int(w * scale)))
    new_h = max(8, round_to_mult8(int(h * scale)))
    return new_w, new_h

def clip_truncate(text: str, tokenizer, reserve: int = 0) -> str:
    try:
        max_len = int(getattr(tokenizer, "model_max_length", 77))
        max_len = max(8, max_len - int(reserve))
        enc = tokenizer(text, truncation=True, max_length=max_len, return_tensors="pt")
        dec = tokenizer.batch_decode(enc["input_ids"], skip_special_tokens=True)
        return dec[0] if dec else text
    except Exception: return text[:500]