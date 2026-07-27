from systempulse.utils import format_bytes, format_rate


def test_format_bytes():
    assert format_bytes(1024) == "1.00 KiB"
    assert format_bytes(1024**2) == "1.00 MiB"
    assert format_bytes(1024**3) == "1.00 GiB"


def test_format_rate():
    assert format_rate(1024) == "1.00 KiB/s"
