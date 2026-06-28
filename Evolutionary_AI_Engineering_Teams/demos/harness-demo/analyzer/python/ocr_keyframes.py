"""
OCR sidecar — invoked by the TypeScript analyzer as a subprocess.

Usage:
    python ocr_keyframes.py <keyframes_dir>

Reads every `frame-NNNN-tMS.png` under <keyframes_dir>, runs Apple Vision via
`ocrmac`, and prints a single JSON document to stdout:

    [
      { "frame": 12, "tMs": 24000, "ocr": [{"text": "Clusters", "conf": 0.99, "box": [x, y, w, h]}, ...] },
      ...
    ]

Box coordinates from ocrmac are normalised (0-1) and use the lower-left
origin convention; we leave them as-is and let the TS curator handle conversion.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from ocrmac import ocrmac
except ImportError as e:  # pragma: no cover
    print(json.dumps({"error": f"ocrmac not installed: {e}"}), file=sys.stderr)
    sys.exit(1)


FRAME_RE = re.compile(r"frame-(\d+)-(\d+)\.png$")


def ocr_one(png: Path) -> list[dict]:
    """Return a list of {text, conf, box} for one keyframe."""
    annotations = ocrmac.OCR(str(png)).recognize()
    out = []
    for entry in annotations:
        # ocrmac returns (text, confidence, [x, y, w, h]).
        if len(entry) != 3:
            continue
        text, conf, box = entry
        if not text:
            continue
        out.append({"text": text, "conf": float(conf), "box": list(box)})
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ocr_keyframes.py <keyframes_dir>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1])
    if not root.is_dir():
        print(json.dumps({"error": f"not a directory: {root}"}), file=sys.stderr)
        return 1

    pngs = sorted(root.glob("frame-*.png"))
    if not pngs:
        print(json.dumps([]))
        return 0

    out: list[dict] = []
    for png in pngs:
        m = FRAME_RE.search(png.name)
        if not m:
            continue
        frame_idx, t_ms = int(m.group(1)), int(m.group(2))
        try:
            ocr = ocr_one(png)
        except Exception as e:  # noqa: BLE001
            ocr = []
            print(f"[ocr_keyframes] {png.name}: {e}", file=sys.stderr)
        out.append({"frame": frame_idx, "tMs": t_ms, "ocr": ocr})

    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
