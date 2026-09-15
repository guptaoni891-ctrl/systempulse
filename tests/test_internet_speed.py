from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from unittest.mock import Mock

import httpx
import pytest

import systempulse.internet_speed as internet_speed
from systempulse.internet_speed import InternetSpeedTestError, run_internet_speedtest


class FakeResponse:
    def __init__(
        self,
        size: int = 0,
        *,
        headers: Mapping[str, str] | None = None,
        error: Exception | None = None,
        malformed: bool = False,
        on_iter_bytes: Callable[[], None] | None = None,
        http_version: str = "HTTP/2",
    ) -> None:
        self.size = size
        self.headers = headers or {}
        self.error = error
        self.malformed = malformed
        self.on_iter_bytes = on_iter_bytes
        self.http_version = http_version
        self.closed = False
        self.iter_bytes_calls = 0

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def iter_bytes(self, chunk_size: int) -> Iterable[bytes]:
        self.iter_bytes_calls += 1
        if self.on_iter_bytes is not None:
            self.on_iter_bytes()
        size = self.size - 1 if self.malformed and self.size else self.size
        while size:
            chunk = min(size, chunk_size)
            yield bytes(chunk)
            size -= chunk

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeRequest:
    method: str
    url: str
    kwargs: dict[str, object]


class FakeClient:
    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        failure: BaseException | None = None,
        response_error: Exception | None = None,
        malformed_download: bool = False,
        http_version: str = "HTTP/2",
    ) -> None:
        self.headers = headers if headers is not None else {"CF-Ray": "0123456789abcdef-DXB"}
        self.failure = failure
        self.response_error = response_error
        self.malformed_download = malformed_download
        self.http_version = http_version
        self.requests: list[FakeRequest] = []
        self.send_calls: list[tuple[FakeRequest, bool]] = []
        self.upload_sizes: list[int] = []
        self.responses: list[FakeResponse] = []
        self.closed = False

    def _fail(self) -> None:
        if self.failure is not None:
            raise self.failure

    def build_request(self, method: str, url: str, **kwargs: object) -> FakeRequest:
        request = FakeRequest(method=method, url=url, kwargs=kwargs)
        self.requests.append(request)
        return request

    def send(self, request: object, *, stream: bool = False) -> FakeResponse:
        self._fail()
        assert isinstance(request, FakeRequest)
        self.send_calls.append((request, stream))
        if request.method == "POST":
            payload = request.kwargs["content"]
            self.upload_sizes.append(sum(len(chunk) for chunk in payload))
            size = 0
        else:
            size = int(request.url.rsplit("=", 1)[1])
        response = FakeResponse(
            size,
            headers=self.headers,
            error=self.response_error,
            malformed=self.malformed_download and request.method == "GET" and size > 0,
            http_version=self.http_version,
        )
        self.responses.append(response)
        return response

    def close(self) -> None:
        self.closed = True


class DurationClock:
    def __init__(self, durations: Iterable[float]) -> None:
        self._durations = iter(durations)
        self._now = 100.0
        self._started = False

    def __call__(self) -> float:
        if not self._started:
            self._started = True
            return self._now
        self._now += next(self._durations)
        self._started = False
        return self._now


LATENCIES = [0.01, 0.03, 0.02, 0.04, 0.02] * 4
DOWNLOAD_DURATIONS = [0.02] * 10 + [0.1] * 8 + [1.0] * 6
UPLOAD_DURATIONS = [0.04] * 8 + [0.2] * 6 + [1.0] * 4
EXPECTED_DOWNLOAD_SIZES = [100_000] * 10 + [1_000_000] * 8 + [10_000_000] * 6
EXPECTED_UPLOAD_SIZES = [100_000] * 8 + [1_000_000] * 6 + [10_000_000] * 4


def _successful_clock() -> DurationClock:
    return DurationClock([*LATENCIES, *DOWNLOAD_DURATIONS, *UPLOAD_DURATIONS])


def test_success_uses_cloudflare_endpoints_and_official_reduction_methodology():
    client = FakeClient()

    result = run_internet_speedtest(client, monotonic=_successful_clock())

    assert result.download_mbps == pytest.approx(80.0)
    assert result.upload_mbps == pytest.approx(80.0)
    assert result.latency_ms == pytest.approx(20.0)
    assert result.jitter_ms == pytest.approx(310.0 / 19.0)
    assert result.provider == "Cloudflare"
    assert result.edge_colo == "DXB"
    assert result.http_version == "HTTP/2"
    assert client.requests[0].url == f"{internet_speed.DOWNLOAD_URL}?bytes=0"
    latency_calls = [request for request in client.requests if request.url.endswith("?bytes=0")]
    assert len(latency_calls) == internet_speed.LATENCY_SAMPLES + 1
    download_requests = [request for request in client.requests if request.method == "GET"][21:]
    assert [request.url for request in download_requests] == [
        f"{internet_speed.DOWNLOAD_URL}?bytes={size}" for size in EXPECTED_DOWNLOAD_SIZES
    ]
    post_requests = [request for request in client.requests if request.method == "POST"]
    assert [request.url for request in post_requests] == [internet_speed.UPLOAD_URL] * len(
        EXPECTED_UPLOAD_SIZES
    )
    assert client.upload_sizes == EXPECTED_UPLOAD_SIZES
    assert all(response.closed for response in client.responses)


def test_httpx_requests_use_expected_headers_and_streaming_modes():
    client = FakeClient()

    run_internet_speedtest(client, monotonic=_successful_clock())

    for request in client.requests:
        headers = request.kwargs["headers"]
        assert headers["Accept-Encoding"] == "identity"
        assert headers["User-Agent"].startswith("SystemPulse/2.1.0")
    assert all(stream is True for request, stream in client.send_calls if request.method == "GET")
    assert all(stream is False for request, stream in client.send_calls if request.method == "POST")
    upload_requests = [request for request in client.requests if request.method == "POST"]
    assert all(
        isinstance(request.kwargs["content"], internet_speed._UploadPayload)
        for request in upload_requests
    )
    assert [request.kwargs["headers"]["Content-Length"] for request in upload_requests] == [
        str(size) for size in EXPECTED_UPLOAD_SIZES
    ]
    latency_requests = [request for request in client.requests if request.url.endswith("?bytes=0")]
    assert all(
        request.kwargs["headers"]["Cache-Control"] == "no-cache" for request in latency_requests
    )


class ManualClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class HeaderTimedClient:
    def __init__(
        self,
        clock: ManualClock,
        header_delays: Iterable[float],
        *,
        headers: Mapping[str, str] | None = None,
        body_delay: float = 0.0,
        http_version: str = "HTTP/2",
    ) -> None:
        self.clock = clock
        self.header_delays = iter(header_delays)
        self.headers = headers or {}
        self.body_delay = body_delay
        self.http_version = http_version
        self.responses: list[FakeResponse] = []
        self.requests: list[FakeRequest] = []

    def build_request(self, method: str, url: str, **kwargs: object) -> FakeRequest:
        request = FakeRequest(method=method, url=url, kwargs=kwargs)
        self.requests.append(request)
        return request

    def send(self, request: object, *, stream: bool = False) -> FakeResponse:
        assert isinstance(request, FakeRequest)
        assert stream is True
        self.clock.advance(next(self.header_delays))
        response = FakeResponse(
            size=1,
            headers=self.headers,
            on_iter_bytes=lambda: self.clock.advance(self.body_delay),
            http_version=self.http_version,
        )
        self.responses.append(response)
        return response

    def close(self) -> None:
        pass


def test_latency_stops_at_headers_then_drains_and_closes_response():
    clock = ManualClock()
    client = HeaderTimedClient(clock, [0.005], body_delay=30.0)

    latency_ms, _, http_version = internet_speed._latency_request(client, clock)

    assert latency_ms == pytest.approx(5.0)
    assert http_version == "HTTP/2"
    assert clock.now == pytest.approx(130.005)
    assert client.responses[0].closed is True
    assert client.responses[0].iter_bytes_calls == 1


def test_warmup_is_excluded_and_twenty_measured_samples_keep_original_order():
    clock = ManualClock()
    measured_seconds = [value / 1000.0 for value in range(1, 21)]
    client = HeaderTimedClient(clock, [9.0, *measured_seconds])

    samples, _, _ = internet_speed._measure_latency(client, clock)

    assert samples == pytest.approx(list(range(1, 21)))
    assert len(client.requests) == internet_speed.LATENCY_SAMPLES + 1
    assert statistics.median(samples) == pytest.approx(10.5)
    assert internet_speed._jitter(samples) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("headers", "header_delay", "expected_ms"),
    [
        ({"Server-Timing": "cfRequestDuration;dur=3.25"}, 0.01, 6.75),
        (
            {
                "server-timing": (
                    'cache;desc="hit, local", other;dur=99, CFREQUESTDURATION;desc="edge";dur="4.5"'
                )
            },
            0.01,
            5.5,
        ),
        ({"Server-Timing": "cfRequestDuration;dur=not-a-number"}, 0.01, 10.0),
        ({"Server-Timing": "cfRequestDuration;dur=25"}, 0.01, 0.0),
        ({}, 0.01, 10.0),
    ],
)
def test_server_timing_subtraction_and_fallback(headers, header_delay, expected_ms):
    clock = ManualClock()
    client = HeaderTimedClient(clock, [header_delay], headers=headers)

    latency_ms, _, _ = internet_speed._latency_request(client, clock)

    assert latency_ms == pytest.approx(expected_ms)


def test_upload_repeats_measurement_sets_and_adaptively_skips_larger_sizes():
    durations = [0.02] * 8 + [0.2] * 6 + [1.2] * 4
    client = FakeClient()

    samples, _, _ = internet_speed._measure_upload(client, DurationClock(durations))

    assert samples == pytest.approx([80.0 / 1.2] * 4)
    assert client.upload_sizes == EXPECTED_UPLOAD_SIZES
    assert 25_000_000 not in client.upload_sizes
    assert 50_000_000 not in client.upload_sizes


def test_early_tiny_high_speed_upload_samples_do_not_inflate_final_p90():
    durations = [0.01] * 8 + [0.02] * 6 + [2.0] * 4
    client = FakeClient()

    samples, _, _ = internet_speed._measure_upload(client, DurationClock(durations))

    assert internet_speed._bandwidth_percentile(samples, "upload") == pytest.approx(40.0)


def test_p90_is_reduced_within_the_selected_stable_set():
    durations = [0.02] * 8 + [0.2] * 6 + [1.0, 1.25, 2.0, 4.0]
    client = FakeClient()

    samples, _, _ = internet_speed._measure_upload(client, DurationClock(durations))

    assert samples == pytest.approx([80.0, 64.0, 40.0, 20.0])
    assert internet_speed._bandwidth_percentile(samples, "upload") == pytest.approx(75.2)


def test_upload_uses_largest_completed_valid_set_when_no_set_reaches_one_second():
    request_count = sum(repetitions for _, repetitions in internet_speed.UPLOAD_MEASUREMENT_SETS)
    client = FakeClient()

    samples, _, _ = internet_speed._measure_upload(client, DurationClock([0.5] * request_count))

    assert samples == pytest.approx([800.0] * 3)
    assert client.upload_sizes[-3:] == [50_000_000] * 3


def test_upload_samples_shorter_than_ten_milliseconds_are_excluded():
    request_count = sum(repetitions for _, repetitions in internet_speed.UPLOAD_MEASUREMENT_SETS)
    client = FakeClient()

    with pytest.raises(InternetSpeedTestError, match="insufficient valid upload speed samples"):
        internet_speed._measure_upload(client, DurationClock([0.001] * request_count))

    assert len(client.send_calls) == request_count


def test_upload_uses_full_request_duration_minus_server_processing_time():
    client = FakeClient(headers={"Server-Timing": "cfRequestDuration;dur=100"})

    samples, _, _ = internet_speed._measure_upload(client, DurationClock([1.11] * 8))

    assert samples == pytest.approx([0.8 / 1.01] * 8)
    assert client.upload_sizes == [100_000] * 8


def test_download_also_excludes_valid_server_processing_time():
    client = FakeClient(headers={"Server-Timing": "cfRequestDuration;dur=10"})

    samples, _, _ = internet_speed._measure_download(client, DurationClock([1.01] * 10))

    assert samples == pytest.approx([0.8] * 10)


def test_download_selects_final_stable_set_and_counts_actual_bytes():
    durations = [0.02] * 10 + [0.1] * 8 + [1.25] * 6
    client = FakeClient()

    samples, _, _ = internet_speed._measure_download(client, DurationClock(durations))

    assert samples == pytest.approx([64.0] * 6)
    download_sizes = [
        int(request.url.rsplit("=", 1)[1]) for request in client.requests if request.method == "GET"
    ]
    assert download_sizes == EXPECTED_DOWNLOAD_SIZES


def test_download_uses_largest_completed_set_when_stability_is_not_reached():
    request_count = sum(repetitions for _, repetitions in internet_speed.DOWNLOAD_MEASUREMENT_SETS)
    client = FakeClient()

    samples, _, _ = internet_speed._measure_download(client, DurationClock([0.5] * request_count))

    assert samples == pytest.approx([400.0] * 4)


def test_effective_duration_is_positive_but_too_short_to_qualify_after_clamping():
    duration = internet_speed._effective_network_duration(
        0.005, {"Server-Timing": "cfRequestDuration;dur=10"}
    )

    assert duration == internet_speed.MINIMUM_EFFECTIVE_DURATION_SECONDS
    assert internet_speed._usable_transfer_duration(duration) is False


@pytest.mark.parametrize("duration", [0.0, -1.0, math.nan, math.inf])
def test_invalid_effective_durations_are_preserved_for_validation(duration):
    result = internet_speed._effective_network_duration(
        duration, {"Server-Timing": "cfRequestDuration;dur=10"}
    )
    if math.isnan(duration):
        assert math.isnan(result)
    else:
        assert result == duration


def test_largest_upload_payload_reuses_a_bounded_chunk():
    payload = internet_speed._UploadPayload(50_000_000)
    chunks = iter(payload)
    first = next(chunks)
    second = next(chunks)

    assert len(payload) == 50_000_000
    assert len(first) == internet_speed.STREAM_CHUNK_BYTES
    assert first is second


@pytest.mark.parametrize(
    "header",
    [
        "cfRequestDuration;dur=-1",
        "cfRequestDuration;dur=nan",
        "cfRequestDuration;dur=inf",
        'cfRequestDuration;dur="broken',
    ],
)
def test_malformed_server_timing_values_are_ignored(header):
    assert internet_speed._server_processing_ms({"Server-Timing": header}) is None


def test_injected_client_is_reused_and_default_client_enables_http2(monkeypatch):
    injected = FakeClient()
    run_internet_speedtest(injected, monotonic=_successful_clock())
    assert injected.closed is False

    owned = FakeClient()
    constructor = Mock(return_value=owned)
    monkeypatch.setattr(internet_speed.httpx, "Client", constructor)
    run_internet_speedtest(monotonic=_successful_clock())
    assert owned.closed is True
    constructor.assert_called_once()
    options = constructor.call_args.kwargs
    assert options["http2"] is True
    assert options["follow_redirects"] is True
    assert options["trust_env"] is True
    assert options["timeout"].connect == 5.0
    assert options["timeout"].read == 30.0


def test_http11_protocol_fallback_is_accepted_without_changing_results():
    result = run_internet_speedtest(
        FakeClient(http_version="HTTP/1.1"), monotonic=_successful_clock()
    )

    assert result.http_version == "HTTP/1.1"
    assert result.download_mbps == pytest.approx(80.0)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"cf-ray": "id-LHR"}, "LHR"),
        ({"CF-Ray": "id-東京"}, "東京"),
        ({"CF-Ray": "invalid"}, None),
        ({}, None),
    ],
)
def test_optional_edge_colo_is_safe_and_unicode_capable(headers, expected):
    result = run_internet_speedtest(
        FakeClient(headers=headers),
        monotonic=_successful_clock(),
    )
    assert result.edge_colo == expected


def test_legitimate_zero_values_are_preserved():
    assert internet_speed._megabits_per_second(0, 1.0) == 0.0
    assert internet_speed._validated_number(0.0, "download") == 0.0
    assert internet_speed._jitter([0.0, 0.0, 0.0]) == 0.0


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_invalid_negative_nan_and_infinite_bandwidth_values_are_rejected(value):
    with pytest.raises(InternetSpeedTestError, match="download"):
        internet_speed._bandwidth_percentile([1.0, value], "download")


def test_bandwidth_uses_interpolated_ninetieth_percentile():
    assert internet_speed._bandwidth_percentile([10.0, 40.0, 20.0, 30.0], "download") == 37.0


def test_jitter_requires_two_latency_samples():
    assert internet_speed._jitter([12.0]) is None


def test_jitter_uses_consecutive_original_order_samples():
    assert internet_speed._jitter([1.0, 10.0, 2.0]) == pytest.approx(8.5)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (httpx.TimeoutException("slow"), "timed out"),
        (httpx.ConnectError("offline"), "DNS, TLS, or network error"),
        (OSError("network unavailable"), "network error while contacting Cloudflare"),
    ],
)
def test_network_failures_become_clean_domain_errors(failure, message):
    with pytest.raises(InternetSpeedTestError, match=message):
        run_internet_speedtest(FakeClient(failure=failure), monotonic=_successful_clock())


def test_http_non_success_status_becomes_provider_error():
    request = httpx.Request("GET", internet_speed.DOWNLOAD_URL)
    response = httpx.Response(503, request=request)
    client = FakeClient(
        response_error=httpx.HTTPStatusError(
            "503 Service Unavailable", request=request, response=response
        )
    )
    with pytest.raises(InternetSpeedTestError, match="Cloudflare endpoint unavailable.*503"):
        run_internet_speedtest(client, monotonic=_successful_clock())
    assert client.responses[0].closed is True


def test_malformed_download_response_is_rejected():
    client = FakeClient(malformed_download=True)
    with pytest.raises(InternetSpeedTestError, match="malformed download data"):
        run_internet_speedtest(client, monotonic=_successful_clock())


def test_insufficient_latency_samples_are_rejected():
    clock = DurationClock([-1.0, math.nan, math.inf, -2.0, math.nan] * 4)
    with pytest.raises(InternetSpeedTestError, match="insufficient valid latency samples"):
        run_internet_speedtest(FakeClient(), monotonic=clock)


def test_short_transfers_do_not_create_speed_samples():
    request_count = sum(repetitions for _, repetitions in internet_speed.DOWNLOAD_MEASUREMENT_SETS)
    clock = DurationClock([*LATENCIES, *([0.001] * request_count)])
    with pytest.raises(InternetSpeedTestError, match="insufficient valid download speed samples"):
        run_internet_speedtest(FakeClient(), monotonic=clock)


def test_malformed_response_object_becomes_domain_error():
    client = Mock()
    client.build_request.return_value = object()
    client.send.return_value = object()
    with pytest.raises(InternetSpeedTestError, match="malformed response"):
        run_internet_speedtest(client, monotonic=_successful_clock())


def test_keyboard_interrupt_is_not_converted_or_swallowed():
    with pytest.raises(KeyboardInterrupt):
        run_internet_speedtest(
            FakeClient(failure=KeyboardInterrupt()),
            monotonic=_successful_clock(),
        )
