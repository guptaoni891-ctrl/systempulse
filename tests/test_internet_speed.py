from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import systempulse.internet_speed as internet_speed
from systempulse.internet_speed import InternetSpeedTestError, run_internet_speedtest


class FakeSpeedtest:
    def __init__(
        self,
        *,
        download: object = 800_000_000.0,
        upload: object = 200_000_000.0,
        ping: object = 8.5,
        server: Mapping[str, object] | None = None,
    ) -> None:
        self._download = download
        self._upload = upload
        self._server = server or {}
        self.results = SimpleNamespace(ping=ping)
        self.calls: list[object] = []

    def get_best_server(self) -> Mapping[str, object]:
        self.calls.append("best")
        return self._server

    def download(self) -> object:
        self.calls.append("download")
        return self._download

    def upload(self, *, pre_allocate: bool) -> object:
        self.calls.append(("upload", pre_allocate))
        return self._upload


def _run(backend: FakeSpeedtest):
    factory_calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> FakeSpeedtest:
        factory_calls.append(kwargs)
        return backend

    result = run_internet_speedtest(factory)
    return result, factory_calls


def test_success_converts_decimal_bits_per_second_and_uses_safe_backend_options():
    backend = FakeSpeedtest()

    result, factory_calls = _run(backend)

    assert result.download_mbps == 800.0
    assert result.upload_mbps == 200.0
    assert result.ping_ms == 8.5
    assert factory_calls == [{"secure": True, "timeout": 10.0}]
    assert backend.calls == ["best", "download", ("upload", False)]


def test_best_server_metadata_is_captured():
    backend = FakeSpeedtest(
        server={
            "name": "Dubai",
            "sponsor": "du",
            "country": "United Arab Emirates",
            "id": "12345",
        }
    )

    result, _ = _run(backend)

    assert result.server_name == "Dubai"
    assert result.server_sponsor == "du"
    assert result.server_country == "United Arab Emirates"
    assert result.server_id == "12345"


def test_missing_or_empty_optional_server_metadata_is_safe():
    backend = FakeSpeedtest(server={"name": "  ", "id": 12345, "ignored": object()})

    result, _ = _run(backend)

    assert result.server_name is None
    assert result.server_sponsor is None
    assert result.server_country is None
    assert result.server_id == "12345"


def test_legitimate_zero_results_are_accepted():
    result, _ = _run(FakeSpeedtest(download=0, upload=0.0, ping=0))

    assert (result.download_mbps, result.upload_mbps, result.ping_ms) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("download", "upload", "ping", "field"),
    [
        (-1.0, 1.0, 1.0, "download"),
        (1.0, float("nan"), 1.0, "upload"),
        (1.0, 1.0, float("inf"), "ping"),
    ],
)
def test_negative_nan_and_infinity_are_rejected(download, upload, ping, field):
    with pytest.raises(InternetSpeedTestError, match=field):
        _run(FakeSpeedtest(download=download, upload=upload, ping=ping))


def test_non_numeric_result_is_rejected():
    with pytest.raises(InternetSpeedTestError, match="download result was not numeric"):
        _run(FakeSpeedtest(download="fast"))


def test_backend_network_failure_becomes_domain_error():
    def unavailable_factory(**kwargs: object) -> FakeSpeedtest:
        raise OSError("network unavailable")

    with pytest.raises(InternetSpeedTestError, match="Unable to complete.*network unavailable"):
        run_internet_speedtest(unavailable_factory)


def test_keyboard_interrupt_is_not_converted_to_domain_error():
    def interrupted_factory(**kwargs: object) -> FakeSpeedtest:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_internet_speedtest(interrupted_factory)


def test_default_factory_loads_speedtest_dependency_without_real_network(monkeypatch):
    backend = FakeSpeedtest()
    constructor = Mock(return_value=backend)
    importer = Mock(return_value=SimpleNamespace(Speedtest=constructor))
    monkeypatch.setattr(internet_speed.importlib, "import_module", importer)

    result = run_internet_speedtest()

    assert result.download_mbps == 800.0
    importer.assert_called_once_with("speedtest")
    constructor.assert_called_once_with(secure=True, timeout=10.0)


def test_missing_speedtest_dependency_becomes_domain_error(monkeypatch):
    monkeypatch.setattr(
        internet_speed.importlib,
        "import_module",
        Mock(side_effect=ImportError("missing")),
    )

    with pytest.raises(InternetSpeedTestError, match="speedtest-cli dependency is unavailable"):
        run_internet_speedtest()
