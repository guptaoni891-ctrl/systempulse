from __future__ import annotations

import math
import statistics
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from systempulse import __version__

BITS_PER_MEGABIT = 1_000_000.0
DOWNLOAD_URL = "https://speed.cloudflare.com/__down"
UPLOAD_URL = "https://speed.cloudflare.com/__up"
PROVIDER = "Cloudflare"
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 30.0
LATENCY_SAMPLES = 20
MINIMUM_LATENCY_SAMPLES = 10
DOWNLOAD_MEASUREMENT_SETS = (
    (100_000, 10),
    (1_000_000, 8),
    (10_000_000, 6),
    (25_000_000, 4),
)
MINIMUM_BANDWIDTH_SAMPLES = 2
UPLOAD_MEASUREMENT_SETS = (
    (100_000, 8),
    (1_000_000, 6),
    (10_000_000, 4),
    (25_000_000, 4),
    (50_000_000, 3),
)
MINIMUM_UPLOAD_SAMPLES = 3
MINIMUM_TRANSFER_SECONDS = 0.01
BANDWIDTH_STABLE_DURATION_SECONDS = 1.0
MINIMUM_EFFECTIVE_DURATION_SECONDS = 1e-6
STREAM_CHUNK_BYTES = 64 * 1024
USER_AGENT = f"SystemPulse/{__version__} internet-speed-test"
REQUEST_HEADERS = {
    "Accept-Encoding": "identity",
    "User-Agent": USER_AGENT,
}
LATENCY_REQUEST_HEADERS = {
    **REQUEST_HEADERS,
    "Cache-Control": "no-cache",
}

MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class InternetSpeedResult:
    """Validated Cloudflare internet benchmark result in decimal networking units."""

    download_mbps: float
    upload_mbps: float
    latency_ms: float
    jitter_ms: float | None
    provider: str = PROVIDER
    edge_colo: str | None = None
    http_version: str | None = None


class InternetSpeedTestError(RuntimeError):
    """Raised when an internet speed test cannot produce a valid result."""


class HTTPResponse(Protocol):
    headers: Mapping[str, str]
    http_version: str

    def raise_for_status(self) -> None: ...

    def iter_bytes(self, chunk_size: int) -> Iterable[bytes]: ...

    def close(self) -> None: ...


class HTTPClient(Protocol):
    def build_request(self, method: str, url: str, **kwargs: object) -> object: ...

    def send(self, request: object, *, stream: bool = False) -> HTTPResponse: ...

    def close(self) -> None: ...


class _UploadPayload:
    """Sized iterable that reuses one buffer while HTTPX streams the body."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._chunk = bytes(min(size, STREAM_CHUNK_BYTES))

    def __len__(self) -> int:
        return self._size

    def __iter__(self) -> Iterable[bytes]:
        full_chunks, remainder = divmod(self._size, len(self._chunk))
        for _ in range(full_chunks):
            yield self._chunk
        if remainder:
            yield self._chunk[:remainder]


def run_internet_speedtest(
    client: HTTPClient | None = None,
    *,
    monotonic: MonotonicClock | None = None,
) -> InternetSpeedResult:
    """Measure internet performance against Cloudflare's routed edge endpoints."""
    http_client = (
        client
        if client is not None
        else cast(
            HTTPClient,
            httpx.Client(
                http2=True,
                timeout=httpx.Timeout(
                    READ_TIMEOUT_SECONDS,
                    connect=CONNECT_TIMEOUT_SECONDS,
                ),
                follow_redirects=True,
                trust_env=True,
            ),
        )
    )
    owns_client = client is None
    clock = monotonic or time.perf_counter

    try:
        latencies_ms, edge_colo, latency_http_version = _measure_latency(http_client, clock)
        download_samples, download_edge, download_http_version = _measure_download(
            http_client, clock
        )
        upload_samples, upload_edge, upload_http_version = _measure_upload(http_client, clock)
        return InternetSpeedResult(
            download_mbps=_bandwidth_percentile(download_samples, "download"),
            upload_mbps=_bandwidth_percentile(upload_samples, "upload"),
            latency_ms=statistics.median(latencies_ms),
            jitter_ms=_jitter(latencies_ms),
            provider=PROVIDER,
            edge_colo=edge_colo or download_edge or upload_edge,
            http_version=(latency_http_version or download_http_version or upload_http_version),
        )
    except InternetSpeedTestError:
        raise
    except httpx.TimeoutException as error:
        raise InternetSpeedTestError(
            "Unable to complete the test: a Cloudflare request timed out."
        ) from error
    except httpx.ConnectError as error:
        raise InternetSpeedTestError(
            "Unable to complete the test: could not connect to Cloudflare "
            "because of a DNS, TLS, or network error."
        ) from error
    except (httpx.RequestError, httpx.HTTPStatusError) as error:
        detail = str(error).strip() or error.__class__.__name__
        raise InternetSpeedTestError(
            f"Unable to complete the test: Cloudflare endpoint unavailable ({detail})."
        ) from error
    except OSError as error:
        detail = str(error).strip() or error.__class__.__name__
        raise InternetSpeedTestError(
            f"Unable to complete the test: network error while contacting Cloudflare ({detail})."
        ) from error
    except (AttributeError, TypeError, ValueError) as error:
        raise InternetSpeedTestError(
            "Unable to complete the test: Cloudflare returned a malformed response."
        ) from error
    finally:
        if owns_client:
            http_client.close()


def _measure_latency(
    client: HTTPClient,
    clock: MonotonicClock,
) -> tuple[list[float], str | None, str | None]:
    _, edge_colo, http_version = _latency_request(client, None)
    samples: list[float] = []
    for _ in range(LATENCY_SAMPLES):
        latency_ms, sample_edge, sample_http_version = _latency_request(client, clock)
        edge_colo = edge_colo or sample_edge
        http_version = http_version or sample_http_version
        if latency_ms is not None and math.isfinite(latency_ms) and latency_ms >= 0:
            samples.append(latency_ms)

    if len(samples) < MINIMUM_LATENCY_SAMPLES:
        raise InternetSpeedTestError(
            "Unable to complete the test: insufficient valid latency samples."
        )
    return samples, edge_colo, http_version


def _latency_request(
    client: HTTPClient,
    clock: MonotonicClock | None,
) -> tuple[float | None, str | None, str | None]:
    request = client.build_request(
        "GET",
        f"{DOWNLOAD_URL}?bytes=0",
        headers=LATENCY_REQUEST_HEADERS,
    )
    started = clock() if clock is not None else None
    response = client.send(request, stream=True)
    try:
        headers_received = clock() if clock is not None else None
        response.raise_for_status()
        if headers_received is None or started is None:
            latency_ms = None
        else:
            raw_ttfb_ms = (headers_received - started) * 1000.0
            server_processing_ms = _server_processing_ms(response.headers)
            latency_ms = (
                max(0.0, raw_ttfb_ms - server_processing_ms)
                if server_processing_ms is not None
                and math.isfinite(raw_ttfb_ms)
                and raw_ttfb_ms >= 0.0
                else raw_ttfb_ms
            )
        edge_colo = _edge_from_headers(response.headers)
        http_version = _http_version(response)
        for _chunk in response.iter_bytes(chunk_size=STREAM_CHUNK_BYTES):
            pass
        return latency_ms, edge_colo, http_version
    finally:
        response.close()


def _measure_download(
    client: HTTPClient,
    clock: MonotonicClock,
) -> tuple[list[float], str | None, str | None]:
    selected_samples: list[float] = []
    edge_colo: str | None = None
    http_version: str | None = None
    for size, repetitions in DOWNLOAD_MEASUREMENT_SETS:
        set_samples: list[float] = []
        set_durations: list[float] = []
        for _ in range(repetitions):
            request = client.build_request(
                "GET",
                f"{DOWNLOAD_URL}?bytes={size}",
                headers=REQUEST_HEADERS,
            )
            started = clock()
            response = client.send(request, stream=True)
            try:
                response.raise_for_status()
                edge_colo = edge_colo or _edge_from_headers(response.headers)
                http_version = http_version or _http_version(response)
                transferred = 0
                for chunk in response.iter_bytes(chunk_size=STREAM_CHUNK_BYTES):
                    if not isinstance(chunk, bytes):
                        raise InternetSpeedTestError(
                            "Unable to complete the test: Cloudflare returned malformed "
                            "download data."
                        )
                    transferred += len(chunk)
                elapsed = clock() - started
                effective_duration = _effective_network_duration(elapsed, response.headers)
            finally:
                response.close()

            if transferred != size:
                raise InternetSpeedTestError(
                    "Unable to complete the test: Cloudflare returned malformed download data "
                    f"({transferred} of {size} bytes)."
                )
            if _usable_transfer_duration(effective_duration):
                set_durations.append(effective_duration)
                set_samples.append(_megabits_per_second(transferred, effective_duration))

        if len(set_samples) >= MINIMUM_BANDWIDTH_SAMPLES:
            selected_samples = set_samples
            if any(duration >= BANDWIDTH_STABLE_DURATION_SECONDS for duration in set_durations):
                break

    if len(selected_samples) < MINIMUM_BANDWIDTH_SAMPLES:
        raise InternetSpeedTestError(
            "Unable to complete the test: insufficient valid download speed samples."
        )
    return selected_samples, edge_colo, http_version


def _measure_upload(
    client: HTTPClient,
    clock: MonotonicClock,
) -> tuple[list[float], str | None, str | None]:
    selected_samples: list[float] = []
    edge_colo: str | None = None
    http_version: str | None = None
    for size, repetitions in UPLOAD_MEASUREMENT_SETS:
        set_samples: list[float] = []
        set_durations: list[float] = []
        for _ in range(repetitions):
            payload = _UploadPayload(size)
            request = client.build_request(
                "POST",
                UPLOAD_URL,
                content=payload,
                headers={
                    **REQUEST_HEADERS,
                    "Content-Length": str(size),
                    "Content-Type": "application/octet-stream",
                },
            )
            started = clock()
            response = client.send(request)
            try:
                elapsed = clock() - started
                response.raise_for_status()
                edge_colo = edge_colo or _edge_from_headers(response.headers)
                http_version = http_version or _http_version(response)
                effective_duration = _effective_network_duration(elapsed, response.headers)
            finally:
                response.close()

            if _usable_transfer_duration(effective_duration):
                set_durations.append(effective_duration)
                set_samples.append(_megabits_per_second(size, effective_duration))

        if len(set_samples) >= MINIMUM_UPLOAD_SAMPLES:
            selected_samples = set_samples
            if any(duration >= BANDWIDTH_STABLE_DURATION_SECONDS for duration in set_durations):
                break

    if len(selected_samples) < MINIMUM_UPLOAD_SAMPLES:
        raise InternetSpeedTestError(
            "Unable to complete the test: insufficient valid upload speed samples."
        )
    return selected_samples, edge_colo, http_version


def _effective_network_duration(elapsed_seconds: float, headers: object) -> float:
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0.0:
        return elapsed_seconds
    server_processing_ms = _server_processing_ms(headers)
    if server_processing_ms is None:
        return elapsed_seconds
    return max(
        MINIMUM_EFFECTIVE_DURATION_SECONDS,
        elapsed_seconds - server_processing_ms / 1000.0,
    )


def _usable_transfer_duration(elapsed_seconds: float) -> bool:
    return math.isfinite(elapsed_seconds) and elapsed_seconds >= MINIMUM_TRANSFER_SECONDS


def _megabits_per_second(transferred_bytes: int, elapsed_seconds: float) -> float:
    if transferred_bytes < 0:
        raise InternetSpeedTestError(
            "Unable to complete the test: transferred byte count was negative."
        )
    if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0.0:
        raise InternetSpeedTestError(
            "Unable to complete the test: transfer duration was not finite and positive."
        )
    return transferred_bytes * 8.0 / elapsed_seconds / BITS_PER_MEGABIT


def _bandwidth_percentile(samples: Iterable[float], direction: str) -> float:
    validated = [_validated_number(sample, direction) for sample in samples]
    if len(validated) < MINIMUM_BANDWIDTH_SAMPLES:
        raise InternetSpeedTestError(
            f"Unable to complete the test: insufficient valid {direction} speed samples."
        )
    return _percentile(validated, 0.9)


def _percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be between zero and one")
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _jitter(latencies_ms: Iterable[float]) -> float | None:
    values = list(latencies_ms)
    if len(values) < 2:
        return None
    return statistics.mean(
        abs(current - previous) for previous, current in zip(values, values[1:], strict=False)
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


def _edge_from_headers(headers: object) -> str | None:
    if not isinstance(headers, Mapping):
        return None
    ray = next(
        (
            value
            for key, value in headers.items()
            if isinstance(key, str) and key.casefold() == "cf-ray"
        ),
        None,
    )
    if not isinstance(ray, str) or "-" not in ray:
        return None
    colo = ray.rsplit("-", 1)[1].strip()
    if not colo or len(colo) > 32 or any(character.isspace() for character in colo):
        return None
    return colo


def _http_version(response: object) -> str | None:
    value = getattr(response, "http_version", None)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 32 or any(character.isspace() for character in value):
        return None
    return value


def _server_processing_ms(headers: object) -> float | None:
    if not isinstance(headers, Mapping):
        return None
    header = next(
        (
            value
            for key, value in headers.items()
            if isinstance(key, str) and key.casefold() == "server-timing"
        ),
        None,
    )
    if not isinstance(header, str):
        return None

    for metric in _split_quoted(header, ","):
        fields = _split_quoted(metric, ";")
        if not fields or fields[0].strip().casefold() != "cfrequestduration":
            continue
        for parameter in fields[1:]:
            name, separator, raw_value = parameter.partition("=")
            if not separator or name.strip().casefold() != "dur":
                continue
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1].strip()
            try:
                duration_ms = float(value)
            except ValueError:
                continue
            if math.isfinite(duration_ms) and duration_ms >= 0.0:
                return duration_ms
    return None


def _split_quoted(value: str, delimiter: str) -> list[str]:
    fields: list[str] = []
    start = 0
    quoted = False
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
        elif quoted and character == "\\":
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif character == delimiter and not quoted:
            fields.append(value[start:index])
            start = index + 1
    fields.append(value[start:])
    return fields
