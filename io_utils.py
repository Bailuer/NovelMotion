from __future__ import annotations
import json, textwrap, csv
from pathlib import Path
from datetime import timedelta
from storyboard import Storyboard

def export_storyboard_json(sb: Storyboard, out_path: Path) -> None:
    out_path.write_text(json.dumps(sb.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

def _seconds_to_srt_ts(seconds: float) -> str:
    total_ms = int(timedelta(seconds=float(seconds)).total_seconds() * 1000)
    hh = total_ms // 3_600_000; rem = total_ms % 3_600_000
    mm = rem // 60_000; rem %= 60_000
    ss = rem // 1000; ms = rem % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

def export_srt(sb: Storyboard, out_path: Path) -> None:
    t = 0.0; lines = []
    for shot in sb.shots:
        start, end = t, t + shot.duration; t = end
        lines += [str(shot.idx), f"{_seconds_to_srt_ts(start)} --> {_seconds_to_srt_ts(end)}",
                  textwrap.fill(shot.text, width=28), ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")

def export_shots_csv(sb: Storyboard, out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["idx","text","prompt","camera_move","scene","characters","duration"])
        for s in sb.shots:
            w.writerow([s.idx, s.text, s.prompt, s.camera_move, s.scene, "|".join(s.characters), f"{s.duration:.2f}"])