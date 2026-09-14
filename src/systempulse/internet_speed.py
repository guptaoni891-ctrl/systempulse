from __future__ import annotations

import importlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

BITS_PER_MEGABIT = 1_000_000.0
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class InternetSpeedResult:
    """Validated internet benchmark result in decimal networking units."""

    download_mbps: float
    upload_mbps: float
    ping_ms: float
    server_name: str | None = None
    server_sponsor: str | None = None
    server_country: str | None = None
    server_id: str | None = None


class InternetSpeedTestError(RuntimeError):
    """Raised when an internet speed test cannot produce a valid result."""


class _SpeedtestResults(Protocol):
    ping: object


class _SpeedtestBackend(Protocol):
    results: _SpeedtestResults

    def get_best_server(self) -> Mapping[str, object]: ...

    def download(self) -> object: ...

    def upload(self, *, pre_allocate: bool) -> object: ...


class SpeedtestFactory(Protocol):
    def __call__(self, *, secure: bool, timeout: float) -> _SpeedtestBackend: ...


def _default_speedtest_factory(*, secure: bool, timeout: float) -> _SpeedtestBackend:
    try:
        module = importlib.import_module("speedtest")
        constructor = module.Speedtest
    except (AttributeError, ImportError) as error:
        raise InternetSpeedTestError(
            "Unable to complete the test: the speedtest-cli dependency is unavailable."
        ) from error
    return cast(_SpeedtestBackend, constructor(secure=secure, timeout=timeout))


def run_internet_speedtest(
    speedtest_factory: SpeedtestFactory | None = None,
) -> InternetSpeedResult:
    """Run the replaceable speedtest-cli backend and return a validated result."""
    factory = speedtest_factory or _default_speedtest_factory
    try:
        backend = factory(secure=True, timeout=DEFAULT_TIMEOUT_SECONDS)
        server = backend.get_best_server()
        download_mbps = _validated_number(backend.download(), "download") / BITS_PER_MEGABIT
        upload_mbps = (
            _validated_number(backend.upload(pre_allocate=False), "upload") / BITS_PER_MEGABIT
        )
        ping_ms = _validated_number(backend.results.ping, "ping")
    except InternetSpeedTestError:
        raise
    except Exception as error:
        detail = str(error).strip() or error.__class__.__name__
        raise InternetSpeedTestError(f"Unable to complete the test: {detail}") from error

    metadata = server if isinstance(server, Mapping) else {}
    return InternetSpeedResult(
        download_mbps=download_mbps,
        upload_mbps=upload_mbps,
        ping_ms=ping_ms,
        server_name=_optional_text(metadata.get("name")),
        server_sponsor=_optional_text(metadata.get("sponsor")),
        server_country=_optional_text(metadata.get("country")),
        server_id=_optional_text(metadata.get("id")),
    )


def _validated_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InternetSpeedTestError(f"Unable to complete the test: {name} result was not numeric.")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise InternetSpeedTestError(
            f"Unable to complete the test: {name} result was not finite and non-negative."
        )
    return result


def _optional_text(value: object) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None
