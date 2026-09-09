"""Run the NSFW classifier over a local folder of images.

Use this to validate thresholds on real examples BEFORE touching Telegram:

    python scripts/sample_scan.py ./samples
    python scripts/sample_scan.py ./samples --json out.json

Every row shows the NSFW probability and what the scoring engine would decide
for a user whose *only* signal is that photo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import get_scoring_config
from core.nsfw import get_classifier
from core.scoring import UserProfile, score_user

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def main() -> int:
    parser = argparse.ArgumentParser(description="NSFW threshold sanity check")
    parser.add_argument("folder", type=Path, help="Rasmlar joylashgan papka")
    parser.add_argument("--config", type=Path, default=None, help="scoring.yaml yo'li")
    parser.add_argument("--json", type=Path, default=None, help="Natijani JSON ga yozish")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"Papka topilmadi: {args.folder}", file=sys.stderr)
        return 2

    cfg = get_scoring_config(args.config)
    classifier = get_classifier(cfg.nsfw)

    images = sorted(p for p in args.folder.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        print("Papkada rasm topilmadi.", file=sys.stderr)
        return 1

    print(f"Backend: {classifier.name}   Rasmlar: {len(images)}")
    print(
        f"Chegaralar: ban >= {cfg.thresholds.ban}, review >= {cfg.thresholds.review}\n"
    )
    print(f"{'fayl':<45} {'nsfw':>6} {'ball':>6}  qaror")
    print("-" * 78)

    rows = []
    for image in images:
        nsfw = classifier.score_image(image)
        profile = UserProfile(telegram_id=1_000_000_001, username="u", has_photo=True)
        result = score_user(profile, cfg, nsfw_score=nsfw)
        rows.append(
            {
                "file": str(image),
                "nsfw": round(nsfw, 4),
                "score": round(result.score, 4),
                "verdict": result.verdict.value,
            }
        )
        name = image.name if len(image.name) <= 44 else image.name[:41] + "..."
        print(f"{name:<45} {nsfw:>6.2f} {result.score:>6.2f}  {result.verdict.value}")

    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON yozildi: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
