import pytest

from systempulse.status import classify, classify_temperature


def test_classify_boundaries():
    assert classify(59.9, 60, 80) == "Normal"
    assert classify(60, 60, 80) == "High"
    assert classify(79.9, 60, 80) == "High"
    assert classify(80, 60, 80) == "Critical"


def test_temperature_uses_hot_label():
    assert classify_temperature(70, 70, 85) == "Hot"
    assert classify_temperature(85, 70, 85) == "Critical"


def test_invalid_thresholds_raise():
    with pytest.raises(ValueError):
        classify(50, 80, 60)
