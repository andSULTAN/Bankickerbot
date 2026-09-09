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


def test_nudenet_class_weighting(monkeypatch):
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
    assert abs(classifier.score_image("x.jpg") - 0.76) < 1e-6
