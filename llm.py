from __future__ import annotations
import os, json, requests, sys
from pathlib import Path
from typing import Dict, List, Optional
from storyboard import Shot, sentences_to_shots, split_into_sentences, choose_camera_move, CAMERA_MOVES
STYLE_PRESETS = {
    "anime_high": "highly detailed anime, clean lineart, rich background, vibrant colors, studio quality, sharp focus, masterpiece",
    "cinematic": "cinematic lighting, volumetric light, film grain, shallow depth of field, dramatic composition, masterpiece",
    "watercolor": "watercolor painting, soft edges, delicate brush strokes, pastel tones, artistic, illustration",
}

def load_character_cards(path: Optional[str]) -> Dict[str,str]:
    if not path: return {}
    p = Path(path)
    if not p.exists():
        print(f"[warn] character cards not found: {p}", file=sys.stderr); return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {str(k).strip(): str(v).strip() for k,v in data.items()}
    except Exception as e:
        print(f"[warn] failed to parse character cards {p}: {e}", file=sys.stderr); return {}

def call_llm_chat_openai(base_url: str, api_key: str, model: str, messages: List[Dict[str,str]], timeout=60, temperature=0.4) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type":"application/json"}
    payload = {"model": model, "messages": messages, "temperature": float(temperature),
               "response_format": {"type":"json_object"}}
    r = requests.post(url, headers=headers, json=payload, timeout=timeout); r.raise_for_status()
    data = r.json()
    try: return data["choices"][0]["message"]["content"]
    except Exception: raise RuntimeError(f"LLM(OpenAI) response parse error: {data}")

def call_llm_chat_gemini(base_url: str, api_key: str, model: str, messages: List[Dict[str,str]], timeout=60, temperature=0.4) -> str:
    merged = [f"[{m.get('role','user').upper()}]\n{m.get('content','')}" for m in messages]
    prompt = "\n\n".join(merged)
    base = base_url.rstrip("/")
    if not base.endswith("/v1beta"): base += "/v1beta"
    url = f"{base}/models/{model}:generateContent?key={api_key}"
    payload = {"contents":[{"role":"user","parts":[{"text":prompt}]}],
               "generationConfig":{"temperature":float(temperature), "responseMimeType":"application/json"}}
    r = requests.post(url, headers={"Content-Type":"application/json"}, json=payload, timeout=timeout); r.raise_for_status()
    data = r.json()
    try: return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception: raise RuntimeError(f"LLM(Gemini) response parse error: {data}")

def call_llm_chat(provider: str, base_url: str, api_key: str, model: str, messages: List[Dict[str,str]], timeout=60, temperature=0.4) -> str:
    if (provider or "openai").lower() == "gemini":
        return call_llm_chat_gemini(base_url, api_key, model, messages, timeout=timeout, temperature=temperature)
    return call_llm_chat_openai(base_url, api_key, model, messages, timeout=timeout, temperature=temperature)

def build_prompts_with_llm(
    chapter_text: str, seconds_per_sentence: float, orientation: str,
    model: str, base_url: str, api_key: str, language: str="en", provider: str="openai",
    temperature: float=0.4, style_suffix: str="", character_cards: Optional[Dict[str,str]]=None,
    debug_path: Optional[Path]=None,
):
    system = (
        "You are a storyboard AI for anime-style dynamic manga.\n"
        "INPUT: a Chinese chapter text.\n"
        "TASK: Split it into visual shots and output STRICT JSON with an array 'shots'.\n"
        "Each shot MUST include:\n"
        "  - 'text' : the original sentence or a faithful short summary in Chinese.\n"
        "  - 'prompt' : a SHORT visual prompt in {lang}, <=160 chars, NO narration.\n"
        "               The prompt MUST contain: character names (keep original script), key action, scene/location, mood.\n"
        "  - 'camera_move' : one of [static, push, pull, pan-left, pan-right, tilt-up, tilt-down].\n"
        "  - 'characters' : array of names appearing in the shot (use exact names from the text if present).\n"
        "  - 'scene' : a short setting tag.\n"
        "Optional BUT RECOMMENDED: 'action','emotion','time_of_day','props','weather'.\n"
        "CONSTRAINTS: Preserve proper nouns verbatim in 'prompt' & 'characters'; keep prompt concise.\n"
        "Return ONLY JSON: {\"shots\": [...]} with no extra text."
    ).replace("{lang}", "English" if language.lower().startswith("en") else "Chinese")

    user = {"role":"user","content":(
        f"Orientation: {orientation}. Default shot duration: {seconds_per_sentence}s.\n"
        "Prefer 1 sentence = 1 shot unless a sentence has two distinct visuals.\n"
        "Return STRICT JSON: {\"shots\": [{\"text\":..., \"prompt\":..., \"camera_move\":\"static|push|pull|pan-left|pan-right|tilt-up|tilt-down\", \"characters\":[...], \"scene\":\"...\", \"action\":\"\", \"emotion\":\"\", \"time_of_day\":\"\", \"props\":\"\", \"weather\":\"\"}]}\n\n"
        f"Chapter:\n{chapter_text}"
    )}

    content = call_llm_chat(provider, base_url, api_key, model, [{"role":"system","content":system}, user], temperature=temperature)

    # debug save + preview
    if debug_path is not None:
        try: debug_path.write_text(content, encoding="utf-8")
        except Exception as _e: print(f"[warn] failed to write LLM raw output: {debug_path} — {_e}", file=sys.stderr)
        try:
            raw_outfile = debug_path.parent / "llm_raw.json"
            raw_outfile.write_text(str(content), encoding="utf-8")
            full_outfile = debug_path.parent / "llm_response_full.json"
            resp = json.loads(content); full_outfile.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[LLM Response saved] raw -> {raw_outfile}, parsed -> {full_outfile}")
        except Exception as e:
            print(f"[LLM Response save error] {e}")
        try:
            preview = content
            try: preview = json.dumps(json.loads(content))
            except Exception: pass
            if len(preview) > 600: preview = preview[:600] + "...(truncated)"
            print(f"[LLM Response preview] {provider}={model}: {preview}")
        except Exception as _e:
            print(f"[warn] failed to print LLM preview: {_e}", file=sys.stderr)

    try:
        obj = json.loads(content); shots_obj = obj.get("shots") or []
        shots: list[Shot] = []
        for i, s in enumerate(shots_obj, 1):
            text_s = str(s.get("text") or "").strip() or "..."
            prompt_s = str(s.get("prompt") or "").strip()
            cam = str(s.get("camera_move") or choose_camera_move(i-1)).strip()
            chars = s.get("characters") or []
            scene = str(s.get("scene") or "")
            # optional enrich
            extra_bits = []
            for k in ("action","emotion","time_of_day","props","weather"):
                v = str(s.get(k) or "").strip()
                if v: extra_bits.append(v)
            if extra_bits: prompt_s = f"{prompt_s}, " + ", ".join(extra_bits)
            # character cards
            if character_cards:
                for name in list(chars):
                    desc = character_cards.get(str(name).strip())
                    if desc: prompt_s = f"{desc}, {prompt_s}".strip(", ")
            if style_suffix: prompt_s = f"{prompt_s}, {style_suffix}".strip(", ")
            shots.append(Shot(idx=i, text=text_s, duration=max(1.5, float(seconds_per_sentence)),
                              camera_move=cam if cam in CAMERA_MOVES else choose_camera_move(i-1),
                              scene=scene, characters=list(map(str, chars)), prompt=prompt_s))
        return shots or sentences_to_shots(split_into_sentences(chapter_text), seconds_per_sentence)
    except Exception as e:
        print(f"[LLM JSON parse failed] {e}", file=sys.stderr)
        return sentences_to_shots(split_into_sentences(chapter_text), seconds_per_sentence)