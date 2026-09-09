"""NSFW wrapper: class weighting and the mocked classifier used everywhere else."""

from __future__ import annotations

from core.config import NsfwConfig
from core.nsfw import NudeNetClassifier, StubClassifier, get_classifier


def test_stub_classifier_takes_the_max(tmp_path):
    classifier = StubClassifier(default=0.1, scores={"spam.jpg": 0.93})
    a = tmp_path / "clean.jpg"
    b = tmp_path / "spam.jpg"
    a.touch()
    b.touch()
    assert classifier.score_images([a, b]) == 0.93


def test_stub_ignores_broken_images(tmp_path):
    class Broken(StubClassifier):
        def score_image(self, path):
            raise RuntimeError("corrupt")

    assert Broken().score_images([tmp_path / "x.jpg"]) == 0.0


def test_factory_honours_env(monkeypatch):
    monkeypatch.setenv("TGGUARD_NSFW_BACKEND", "stub")
    assert isinstance(get_classifier(NsfwConfig()), StubClassifier)


def test_nudenet_class_weighting(monkeypatch, tmp_path):
    """Detections are weighted per class and filtered by min_detection_score."""
    config = NsfwConfig(
        unsafe_classes={"FEMALE_BREAST_EXPOSED": 0.95, "BELLY_EXPOSED": 0.2},
        min_detection_score=0.35,
        max_photos=3,
    )
    classifier = NudeNetClassifier(config)

    class FakeDetector:
        def detect(self, path):
            return [
                {"class": "FACE_FEMALE", "score": 0.99},          # not unsafe
                {"class": "BELLY_EXPOSED", "score": 0.90},        # weak class
                {"class": "FEMALE_BREAST_EXPOSED", "score": 0.80},
                {"class": "FEMALE_BREAST_EXPOSED", "score": 0.20},  # below cutoff
            ]

    monkeypatch.setattr(classifier, "_get_detector", lambda: FakeDetector())
    # A real, decodable file: unreadable ones short-circuit to 0.0 by design.
    from PIL import Image

    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (128, 128), (120, 90, 70)).save(photo)
    assert abs(classifier.score_image(photo) - 0.76) < 1e-6


def test_normalize_image_reencodes_and_downscales(tmp_path):
    from PIL import Image

    from core.nsfw import MAX_SIDE, normalize_image

    source = tmp_path / "big.png"
    Image.new("RGBA", (2000, 1200), (10, 20, 30, 255)).save(source)

    normalized = normalize_image(source)
    try:
        assert normalized is not None and normalized.exists()
        with Image.open(normalized) as image:
            assert image.format == "JPEG"
            assert image.mode == "RGB"
            assert max(image.size) <= MAX_SIDE
    finally:
        normalized.unlink(missing_ok=True)


def test_normalize_image_rejects_non_images(tmp_path):
    """Video avatars and truncated downloads arrive with a .jpg name."""
    from core.nsfw import normalize_image

    broken = tmp_path / "video_avatar.jpg"
    broken.write_bytes(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 64)
    assert normalize_image(broken) is None

    missing = tmp_path / "nope.jpg"
    assert normalize_image(missing) is None


def test_unreadable_image_never_reaches_the_detector(tmp_path, monkeypatch):
    """OpenCV returns None for these and NudeNet then crashes on .shape."""
    classifier = NudeNetClassifier(NsfwConfig())

    def _boom():
        raise AssertionError("detector must not be called for an unreadable file")

    monkeypatch.setattr(classifier, "_get_detector", _boom)
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    assert classifier.score_image(broken) == 0.0
