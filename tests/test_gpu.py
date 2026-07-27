from systempulse.gpu import parse_nvidia_smi_output


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
