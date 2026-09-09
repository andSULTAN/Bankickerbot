"""Pick the thresholds from labelled examples instead of from single photos.

Feed it two folders of profile pictures - the spam ones and the ones belonging
to real subscribers - and it reports, for every candidate threshold, how much
spam is caught and how many real people would be hit. Then it recommends the
values to put in `config/scoring.yaml`.

    python scripts/calibrate.py --spam samples/spam --real samples/real
    python scripts/calibrate.py --spam samples/spam --real samples/real --csv out.csv

Collect the samples with `tgguard scan --save-photos samples/all --limit 500`
and sort that folder into `spam/` and `real/` by eye. 50-100 photos of each
are plenty; they describe YOUR channel, which no public dataset does.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ScoringConfig, get_scoring_config  # noqa: E402
from core.nsfw import get_classifier  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
STEPS = [round(0.05 * i, 2) for i in range(4, 20)]  # 0.20 .. 0.95


def collect(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)


def photo_scores(paths: list[Path], classifier, cfg: ScoringConfig) -> list[tuple[Path, float]]:
    """Score every image the way a profile with only that photo would be scored."""
    weight = cfg.weights.get("nsfw_photo", 1.0)
    scored = []
    for index, path in enumerate(paths, start=1):
        nsfw = classifier.score_image(path)
        scored.append((path, min(1.0, nsfw * weight)))
        print(f"\r  {index}/{len(paths)}", end="", flush=True)
    print("\r" + " " * 20 + "\r", end="")
    return scored


def describe(name: str, scores: list[float]) -> None:
    if not scores:
        print(f"{name}: (bo'sh)")
        return
    ordered = sorted(scores)
    middle = ordered[len(ordered) // 2]
    print(
        f"{name:<10} n={len(scores):<4} eng past={ordered[0]:.2f}  "
        f"o'rtacha={sum(scores) / len(scores):.2f}  mediana={middle:.2f}  "
        f"eng yuqori={ordered[-1]:.2f}"
    )


def sweep(spam: list[float], real: list[float]) -> list[dict]:
    rows = []
    for threshold in STEPS:
        caught = sum(1 for value in spam if value >= threshold)
        false_positives = sum(1 for value in real if value >= threshold)
        rows.append(
            {
                "threshold": threshold,
                "caught": caught,
                "missed": len(spam) - caught,
                "recall": caught / len(spam) if spam else 0.0,
                "false_positives": false_positives,
                "fp_rate": false_positives / len(real) if real else 0.0,
            }
        )
    return rows


def recommend(rows: list[dict]) -> tuple[float | None, float | None]:
    """Ban: the lowest threshold that still hits nobody real. Review: the
    lowest threshold whose false-positive rate stays under 10%."""
    clean = [row for row in rows if row["false_positives"] == 0]
    ban = min((row["threshold"] for row in clean), default=None)
    tolerant = [row for row in rows if row["fp_rate"] <= 0.10]
    review = min((row["threshold"] for row in tolerant), default=None)
    return ban, review


def main() -> int:
    parser = argparse.ArgumentParser(description="Chegaralarni misollar asosida tanlash")
    parser.add_argument("--spam", type=Path, required=True, help="Spam profil rasmlari papkasi")
    parser.add_argument("--real", type=Path, required=True, help="Haqiqiy obunachi rasmlari")
    parser.add_argument("--config", type=Path, default=None, help="scoring.yaml yo'li")
    parser.add_argument("--csv", type=Path, default=None, help="Har bir rasm ballini CSV ga yozish")
    args = parser.parse_args()

    for folder in (args.spam, args.real):
        if not folder.is_dir():
            print(f"Papka topilmadi: {folder}", file=sys.stderr)
            return 2

    cfg = get_scoring_config(args.config) if args.config else get_scoring_config()
    classifier = get_classifier(cfg.nsfw)

    spam_paths, real_paths = collect(args.spam), collect(args.real)
    if not spam_paths or not real_paths:
        print("Ikkala papkada ham kamida bittadan rasm bo'lishi kerak.", file=sys.stderr)
        return 1

    print(f"Backend: {classifier.name}   spam={len(spam_paths)}  haqiqiy={len(real_paths)}\n")
    print("Spam rasmlari baholanmoqda...")
    spam_scored = photo_scores(spam_paths, classifier, cfg)
    print("Haqiqiy obunachi rasmlari baholanmoqda...")
    real_scored = photo_scores(real_paths, classifier, cfg)

    spam = [score for _, score in spam_scored]
    real = [score for _, score in real_scored]

    print()
    describe("SPAM", spam)
    describe("HAQIQIY", real)

    print(f"\n{'chegara':>8} {'tutildi':>9} {'qochdi':>7} {'xato ban':>9} {'xato %':>8}")
    print("-" * 46)
    rows = sweep(spam, real)
    for row in rows:
        print(
            f"{row['threshold']:>8.2f} {row['caught']:>9} {row['missed']:>7} "
            f"{row['false_positives']:>9} {row['fp_rate'] * 100:>7.0f}%"
        )

    ban, review = recommend(rows)
    best = next((row for row in rows if row["threshold"] == ban), None)
    print("\nTavsiya:")
    if ban is None:
        print("  Haqiqiy rasmlarga tegmaydigan chegara topilmadi — namunalarni ko'paytiring")
        print("  yoki `nsfw.unsafe_classes` vaznlarini pasaytiring.")
    elif best["caught"] == 0:
        # Every score is below the lowest step: the model found nothing at all.
        print("  Spam namunalarida model hech qanday belgi topmadi (barcha ballar 0 ga yaqin).")
        print("  Tekshiring: papkada haqiqiy profil rasmlari bormi? Skrinshot yoki")
        print("  juda kichik rasmlarda model ishlamaydi.")
    else:
        print(f"  thresholds.ban: {ban:.2f}   (spamning {best['recall'] * 100:.0f}% i tutiladi,")
        print("                        haqiqiy obunachilardan hech kim tegmaydi)")
        if best["missed"]:
            print(f"  {best['missed']} ta spam qochib qoladi — ular review oralig'iga tushadi.")
        if review is not None and review < ban:
            print(f"  thresholds.review: {review:.2f}")
        print("\n  Yuqoridagi qiymatlarni config/scoring.yaml ga yozing.")

    if args.csv:
        with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["label", "file", "score"])
            for path, score in spam_scored:
                writer.writerow(["spam", path, f"{score:.4f}"])
            for path, score in real_scored:
                writer.writerow(["real", path, f"{score:.4f}"])
        print(f"\nCSV yozildi: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
