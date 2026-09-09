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

    # max: only the strongest class counts -> 0.80 * 0.95
    classifier.config.combine = "max"
    assert abs(classifier.score_image(photo) - 0.76) < 1e-6

    # noisy_or: the weak BELLY_EXPOSED signal adds on top -> 1 - 0.24 * 0.82
    classifier.config.combine = "noisy_or"
    assert abs(classifier.score_image(photo) - 0.8032) < 1e-4


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


# Real detections from a bikini profile photo of this spam wave, as returned
# by NudeNet. Any single one of them is mild; together they are the signature.
BIKINI_DETECTIONS = [
    {"class": "FACE_FEMALE", "score": 0.87},
    {"class": "FEMALE_BREAST_COVERED", "score": 0.81},
    {"class": "FEMALE_GENITALIA_COVERED", "score": 0.81},
    {"class": "BELLY_EXPOSED", "score": 0.80},
    {"class": "FEMALE_BREAST_COVERED", "score": 0.79},
    {"class": "ARMPITS_EXPOSED", "score": 0.66},
]


def _classifier_with(detections, config, monkeypatch, tmp_path):
    from PIL import Image

    classifier = NudeNetClassifier(config)

    class FakeDetector:
        def detect(self, path):
            return detections

    monkeypatch.setattr(classifier, "_get_detector", lambda: FakeDetector())
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (128, 128), (100, 100, 100)).save(photo)
    return classifier, photo


def test_combine_contributions_strategies():
    from core.nsfw import combine_contributions

    values = [0.45, 0.36, 0.20]
    assert combine_contributions(values, "max") == 0.45
    # Independent evidence: clearly above the strongest single signal.
    assert combine_contributions(values, "noisy_or") > 0.70
    assert combine_contributions([], "noisy_or") == 0.0
    assert combine_contributions([0.99, 0.99], "noisy_or") <= 1.0


def test_bikini_photo_is_banned_on_the_photo_alone(cfg, monkeypatch, tmp_path):
    """Taking only the strongest class scored this 0.45 and let it through."""
    classifier, photo = _classifier_with(BIKINI_DETECTIONS, cfg.nsfw, monkeypatch, tmp_path)

    score, detections = classifier.score_image_details(photo)

    assert detections[0][0] == "FACE_FEMALE"  # sorted by raw probability
    photo_score = score * cfg.weights["nsfw_photo"]
    assert photo_score >= cfg.thresholds.ban


def test_borderline_swimwear_only_goes_to_review(cfg, monkeypatch, tmp_path):
    """One or two moderate signals must stay a human decision, not a ban."""
    borderline = [
        {"class": "FEMALE_BREAST_COVERED", "score": 0.85},
        {"class": "BELLY_EXPOSED", "score": 0.80},
        {"class": "ARMPITS_EXPOSED", "score": 0.70},
    ]
    classifier, photo = _classifier_with(borderline, cfg.nsfw, monkeypatch, tmp_path)

    photo_score = classifier.score_image(photo) * cfg.weights["nsfw_photo"]
    assert cfg.thresholds.review <= photo_score < cfg.thresholds.ban


def test_duplicate_classes_count_once(cfg, monkeypatch, tmp_path):
    """Two detections of the same class are one piece of evidence."""
    single = [{"class": "FEMALE_BREAST_COVERED", "score": 0.81}]
    doubled = single * 3

    one, _ = _classifier_with(single, cfg.nsfw, monkeypatch, tmp_path)
    many, photo = _classifier_with(doubled, cfg.nsfw, monkeypatch, tmp_path)
    assert one.score_image(photo) == many.score_image(photo)


def test_everyday_photos_stay_clean(cfg, monkeypatch, tmp_path):
    beach = [
        {"class": "MALE_BREAST_EXPOSED", "score": 0.90},
        {"class": "BELLY_EXPOSED", "score": 0.85},
        {"class": "ARMPITS_EXPOSED", "score": 0.70},
        {"class": "FEET_EXPOSED", "score": 0.60},
    ]
    classifier, photo = _classifier_with(beach, cfg.nsfw, monkeypatch, tmp_path)
    assert classifier.score_image(photo) * cfg.weights["nsfw_photo"] < cfg.thresholds.review


def test_explicit_photo_still_bans(cfg, monkeypatch, tmp_path):
    explicit = [
        {"class": "FEMALE_BREAST_EXPOSED", "score": 0.95},
        {"class": "FEMALE_GENITALIA_EXPOSED", "score": 0.88},
    ]
    classifier, photo = _classifier_with(explicit, cfg.nsfw, monkeypatch, tmp_path)
    assert classifier.score_image(photo) * cfg.weights["nsfw_photo"] >= cfg.thresholds.ban


# A rear-view swimwear photo: the detector only reports the buttocks, and only
# with ~0.5 confidence, although the photo is unambiguous.
REAR_VIEW_DETECTIONS = [
    {"class": "FACE_FEMALE", "score": 0.78},
    {"class": "ARMPITS_EXPOSED", "score": 0.66},
    {"class": "BUTTOCKS_EXPOSED", "score": 0.51},
]


def test_exposed_class_counts_by_presence(cfg, monkeypatch, tmp_path):
    """Scaling by confidence scored this 0.47 (clean) - the class itself is
    the evidence, the confidence only says whether it is really there."""
    classifier, photo = _classifier_with(REAR_VIEW_DETECTIONS, cfg.nsfw, monkeypatch, tmp_path)

    photo_score = classifier.score_image(photo) * cfg.weights["nsfw_photo"]
    assert photo_score >= cfg.thresholds.ban


def test_single_explicit_detection_is_enough(cfg, monkeypatch, tmp_path):
    detections = [{"class": "FEMALE_BREAST_EXPOSED", "score": 0.47}]
    classifier, photo = _classifier_with(detections, cfg.nsfw, monkeypatch, tmp_path)
    assert classifier.score_image(photo) * cfg.weights["nsfw_photo"] >= cfg.thresholds.ban


def test_explicit_below_the_confidence_floor_falls_back_to_scaling(cfg, monkeypatch, tmp_path):
    """Under `explicit_min_score` the detection is treated as unreliable."""
    detections = [
        {"class": "BUTTOCKS_EXPOSED", "score": 0.40},
        {"class": "FACE_FEMALE", "score": 0.90},
    ]
    classifier, photo = _classifier_with(detections, cfg.nsfw, monkeypatch, tmp_path)
    assert classifier.score_image(photo) * cfg.weights["nsfw_photo"] < cfg.thresholds.review
