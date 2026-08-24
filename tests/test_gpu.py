import subprocess

import pytest

import systempulse.gpu as gpu
from systempulse.gpu import collect_gpu_stats, get_gpu_stats, parse_nvidia_smi_output
from systempulse.models import DiagnosticKind


def test_parse_nvidia_smi_output():
    output = "NVIDIA GeForce GTX 1650, 17, 43, 718, 4096, 21.61"
    gpus = parse_nvidia_smi_output(output)

    assert len(gpus) == 1
    assert gpus[0].name == "NVIDIA GeForce GTX 1650"
    assert gpus[0].usage_percent == 17
    assert gpus[0].temperature_celsius == 43
    assert gpus[0].vram_used_mib == 718
    assert gpus[0].power_watts == 21.61


def test_parse_multiple_gpus_and_missing_power():
    output = "GPU One, 10, 40, 100, 1000, N/A\nGPU Two, 20, 50, 200, 2000, 25.0"
    gpus = parse_nvidia_smi_output(output)

    assert len(gpus) == 2
    assert gpus[0].power_watts is None
    assert gpus[1].power_watts == 25.0


def test_get_gpu_stats_returns_empty_when_nvidia_smi_is_missing(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(gpu.subprocess, "run", missing)

    assert get_gpu_stats() == ()


def test_get_gpu_stats_returns_empty_on_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 3.0)

    monkeypatch.setattr(gpu.subprocess, "run", timeout)

    assert get_gpu_stats() == ()


def test_get_gpu_stats_returns_empty_on_non_zero_exit(monkeypatch):
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "nvidia-smi")

    monkeypatch.setattr(gpu.subprocess, "run", failed)

    assert get_gpu_stats() == ()


@pytest.mark.parametrize(
    "output",
    [
        "not,enough,fields",
        "GPU, invalid, 40, 100, 1000, 20",
        "GPU, 10, N/A, 100, 1000, 20",
    ],
)
def test_get_gpu_stats_returns_empty_for_malformed_or_unavailable_required_values(
    monkeypatch, output
):
    completed = subprocess.CompletedProcess("nvidia-smi", 0, stdout=output, stderr="")
    monkeypatch.setattr(gpu.subprocess, "run", lambda *args, **kwargs: completed)

    assert get_gpu_stats() == ()


def test_get_gpu_stats_returns_empty_for_empty_output(monkeypatch):
    completed = subprocess.CompletedProcess("nvidia-smi", 0, stdout="\n", stderr="")
    monkeypatch.setattr(gpu.subprocess, "run", lambda *args, **kwargs: completed)

    assert get_gpu_stats() == ()


def test_get_gpu_stats_executes_expected_query_and_parses_single_gpu(monkeypatch):
    completed = subprocess.CompletedProcess(
        "nvidia-smi",
        0,
        stdout="NVIDIA RTX Test, 35, 52, 2048, 8192, 75.5\n",
        stderr="",
    )
    run_calls = []

    def run(command, **kwargs):
        run_calls.append((command, kwargs))
        return completed

    monkeypatch.setattr(gpu.subprocess, "run", run)

    result = get_gpu_stats(timeout=1.25)

    assert len(result) == 1
    assert result[0].name == "NVIDIA RTX Test"
    assert result[0].power_watts == 75.5
    assert run_calls == [
        (
            [
                "nvidia-smi",
                f"--query-gpu={gpu.QUERY_FIELDS}",
                "--format=csv,noheader,nounits",
            ],
            {
                "capture_output": True,
                "text": True,
                "check": True,
                "timeout": 1.25,
            },
        )
    ]


def test_get_gpu_stats_parses_multiple_gpus(monkeypatch):
    output = "GPU One, 10, 40, 100, 1000, N/A\nGPU Two, 20, 50, 200, 2000, 25.0"
    completed = subprocess.CompletedProcess("nvidia-smi", 0, stdout=output, stderr="")
    monkeypatch.setattr(gpu.subprocess, "run", lambda *args, **kwargs: completed)

    result = get_gpu_stats()

    assert [item.name for item in result] == ["GPU One", "GPU Two"]
    assert result[0].power_watts is None
    assert result[1].power_watts == 25.0


def test_parse_nvidia_smi_output_rejects_malformed_row():
    with pytest.raises(ValueError, match="Unexpected nvidia-smi row"):
        parse_nvidia_smi_output("GPU, 10, 40")


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (FileNotFoundError("nvidia-smi"), DiagnosticKind.COMMAND_MISSING),
        (subprocess.TimeoutExpired("nvidia-smi", 3.0), DiagnosticKind.TIMEOUT),
        (subprocess.CalledProcessError(2, "nvidia-smi"), DiagnosticKind.EXECUTION_FAILED),
        (OSError("permission denied"), DiagnosticKind.EXECUTION_FAILED),
    ],
)
def test_structured_gpu_execution_diagnostics(monkeypatch, error, kind):
    def failed(*args, **kwargs):
        raise error

    monkeypatch.setattr(gpu.subprocess, "run", failed)

    result = collect_gpu_stats()

    assert result.gpus == ()
    assert result.diagnostics[0].collector == "gpu"
    assert result.diagnostics[0].kind is kind


@pytest.mark.parametrize("output", ["", "not,enough,fields"])
def test_structured_gpu_malformed_result_diagnostic(monkeypatch, output):
    completed = subprocess.CompletedProcess("nvidia-smi", 0, stdout=output, stderr="")
    monkeypatch.setattr(gpu.subprocess, "run", lambda *args, **kwargs: completed)

    result = collect_gpu_stats()

    assert result.gpus == ()
    assert result.diagnostics[0].kind is DiagnosticKind.MALFORMED_RESULT
