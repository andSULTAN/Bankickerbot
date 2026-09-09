"""NSFW image classification wrapper (NudeNet, local, CPU by default).

The rest of the code only ever sees the `NsfwClassifier` protocol, so tests can
inject a stub and CI never has to download the model.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from PIL import Image, UnidentifiedImageError

from core.config import NsfwConfig
from core.logging import get_logger

log = get_logger(__name__)

# NudeNet reads images through OpenCV, which silently returns None for anything
# it cannot decode (animated avatars, truncated downloads, unusual JPEG
# flavours) and then crashes with "NoneType has no attribute shape". Pillow is
# far more tolerant, so every image is re-encoded to a plain RGB JPEG first.
MAX_SIDE = 1024


def combine_contributions(values, strategy: str = "noisy_or") -> float:
    """Fold per-class contributions into one probability in [0, 1].

    `max` keeps only the strongest signal. `noisy_or` (default) treats the
    signals as independent evidence: 1 - PROD(1 - value). A bikini photo fires
    several mild classes at once and only the second form catches that, while
    an already-explicit single detection stays where it was.
    """
    contributions = [max(0.0, min(1.0, value)) for value in values]
    if not contributions:
        return 0.0
    if strategy == "max":
        return max(contributions)
    product = 1.0
    for value in contributions:
        product *= 1.0 - value
    return min(1.0, 1.0 - product)


def normalize_image(path: str | Path) -> Path | None:
    """Re-encode to a plain RGB JPEG. Returns None if this is not an image."""
    try:
        with Image.open(path) as image:
            image.load()
            rgb = image.convert("RGB")
            rgb.thumbnail((MAX_SIDE, MAX_SIDE))
            handle, target = tempfile.mkstemp(prefix="tgguard_img_", suffix=".jpg")
            os.close(handle)
            rgb.save(target, format="JPEG", quality=90)
            return Path(target)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        log.debug("image_unreadable", path=str(path), error=str(exc))
        return None


@runtime_checkable
class NsfwClassifier(Protocol):
    """Anything that can turn an image file into an NSFW probability in [0, 1]."""

    name: str

    def score_image(self, path: str | Path) -> float: ...

    def score_images(self, paths: list[str | Path]) -> float: ...

    def score_image_details(self, path: str | Path) -> tuple[float, list[tuple[str, float]]]: ...


class _BaseClassifier:
    name = "base"

    def score_image(self, path: str | Path) -> float:  # pragma: no cover - interface
        raise NotImplementedError

    def score_image_details(self, path: str | Path) -> tuple[float, list[tuple[str, float]]]:
        """Score plus the raw (class, probability) pairs, for `/test` replies."""
        return self.score_image(path), []

    def score_images(self, paths: list[str | Path]) -> float:
        """Max score across a user's photos (the strongest photo decides)."""
        best = 0.0
        for path in paths:
            try:
                best = max(best, self.score_image(path))
            except Exception as exc:  # a broken image must not kill a scan
                log.warning("nsfw_score_failed", path=str(path), error=str(exc))
            if best >= 0.999:
                break
        return best


class NudeNetClassifier(_BaseClassifier):
    """NudeNet v3 detector; unsafe detections are weighted per class via YAML."""

    name = "nudenet"

    def __init__(self, config: NsfwConfig) -> None:
        self.config = config
        self._detector = None

    def _get_detector(self):
        if self._detector is None:
            from nudenet import NudeDetector  # imported lazily: heavy + optional

            self._detector = NudeDetector()
            log.info("nsfw_model_loaded", backend=self.name)
        return self._detector

    def score_image(self, path: str | Path) -> float:
        return self.score_image_details(path)[0]

    def score_image_details(self, path: str | Path) -> tuple[float, list[tuple[str, float]]]:
        normalized = normalize_image(path)
        if normalized is None:
            # Not a decodable image (e.g. a video avatar): no photo signal.
            return 0.0, []
        try:
            detections = self._get_detector().detect(str(normalized))
        finally:
            normalized.unlink(missing_ok=True)

        found: list[tuple[str, float]] = []
        explicit = set(self.config.explicit_classes)
        # Per class, because two detections of the same class (e.g. both
        # breasts) are one piece of evidence, not two.
        per_class: dict[str, float] = {}
        for detection in detections or []:
            label = detection.get("class") or detection.get("label") or ""
            raw = float(detection.get("score", 0.0))
            if raw < self.config.min_detection_score:
                continue
            found.append((label, raw))
            multiplier = self.config.unsafe_classes.get(label)
            if multiplier is None:
                continue
            if label in explicit and raw >= self.config.explicit_min_score:
                # An exposed private part is the evidence; a 0.51 detection of
                # it does not make the photo "half explicit".
                contribution = multiplier
            else:
                contribution = min(1.0, raw * multiplier)
            per_class[label] = max(per_class.get(label, 0.0), contribution)

        found.sort(key=lambda item: item[1], reverse=True)
        return combine_contributions(per_class.values(), self.config.combine), found


class StubClassifier(_BaseClassifier):
    """Deterministic stand-in used by tests and by `TGGUARD_NSFW_BACKEND=stub`.

    Returns `default` for every image, unless the filename is registered in
    `scores` (handy for fixtures like `spam_profile.jpg`).
    """

    name = "stub"

    def __init__(self, default: float = 0.0, scores: dict[str, float] | None = None) -> None:
        self.default = default
        self.scores = scores or {}

    def score_image(self, path: str | Path) -> float:
        return self.scores.get(Path(path).name, self.default)

    def score_image_details(self, path: str | Path) -> tuple[float, list[tuple[str, float]]]:
        score = self.score_image(path)
        return score, [("STUB_CLASS", score)] if score else []


def get_classifier(config: NsfwConfig) -> NsfwClassifier:
    """Factory honouring `TGGUARD_NSFW_BACKEND` (`nudenet` | `stub`)."""
    backend = os.getenv("TGGUARD_NSFW_BACKEND", "nudenet").lower()
    if backend == "stub":
        return StubClassifier()
    return NudeNetClassifier(config)
