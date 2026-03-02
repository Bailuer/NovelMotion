from __future__ import annotations
import dataclasses, re, textwrap
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Dict, Any

CAMERA_MOVES = ["static", "push", "pull", "pan-left", "pan-right", "tilt-up", "tilt-down"]
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s+|\n+")

@dataclass
class Shot:
    idx: int
    text: str
    duration: float = 5.0
    camera_move: str = "static"
    scene: str = ""
    characters: List[str] = field(default_factory=list)
    prompt: str = ""
    def to_dict(self) -> Dict[str, Any]: return dataclasses.asdict(self)

@dataclass
class Storyboard:
    chapter_title: str
    orientation: str  # 'portrait' | 'landscape'
    width: int
    height: int
    shots: List[Shot]
    @property
    def total_duration(self) -> float: return float(sum(s.duration for s in self.shots))
    def to_dict(self) -> Dict[str, Any]:
        return {"chapter_title": self.chapter_title, "orientation": self.orientation,
                "width": self.width, "height": self.height,
                "total_duration": self.total_duration,
                "shots": [s.to_dict() for s in self.shots]}

def split_into_sentences(text: str) -> List[str]:
    t = re.sub(r"\s+", " ", text.strip())
    if not t: return []
    parts = [p.strip() for p in re.split(SENTENCE_SPLIT_RE, t) if p and p.strip()]
    return parts

def choose_camera_move(i: int) -> str: return CAMERA_MOVES[i % len(CAMERA_MOVES)]

def build_prompt_from_sentence(sentence: str) -> str:
    return "Anime style, dramatic lighting, rich background, cinematic composition, " + sentence[:160]

def sentences_to_shots(sentences: List[str], seconds_per_sentence: float) -> List[Shot]:
    return [Shot(idx=i, text=s, duration=max(1.5, float(seconds_per_sentence)),
                 camera_move=choose_camera_move(i-1),
                 prompt=build_prompt_from_sentence(s)) for i, s in enumerate(sentences, 1)]

def smooth_camera_moves(shots: List[Shot]) -> None:
    for i in range(2, len(shots)):
        a,b,c = shots[i-2].camera_move, shots[i-1].camera_move, shots[i].camera_move
        if a == b == c: shots[i].camera_move = "static"

def infer_dimensions(orientation: str) -> tuple[int,int]:
    return (1080,1920) if orientation=="portrait" else (1920,1080)