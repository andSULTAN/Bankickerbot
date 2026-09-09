"""Threshold recommendation from labelled samples."""

from __future__ import annotations

from scripts.calibrate import recommend, sweep


def test_sweep_counts_catches_and_false_positives():
    spam = [0.91, 0.62]
    real = [0.10, 0.74]

    rows = {row["threshold"]: row for row in sweep(spam, real)}

    assert rows[0.90]["caught"] == 1 and rows[0.90]["false_positives"] == 0
    assert rows[0.60]["caught"] == 2 and rows[0.60]["false_positives"] == 1
    assert rows[0.60]["missed"] == 0
    assert rows[0.90]["recall"] == 0.5


def test_recommendation_protects_real_subscribers():
    """The ban threshold must sit above every real subscriber's photo."""
    spam = [0.91, 0.88, 0.95, 0.62, 0.90, 0.55]
    real = [0.10, 0.00, 0.26, 0.29, 0.74, 0.05]

    ban, _ = recommend(sweep(spam, real))

    assert ban is not None
    assert ban > max(real)
    caught = sum(1 for value in spam if value >= ban)
    assert caught >= 4  # still catches most of the spam


def test_no_safe_threshold_is_reported():
    """A real photo scoring higher than every spam photo leaves no safe cut."""
    ban, _ = recommend(sweep([0.30], [0.99]))
    assert ban is None
