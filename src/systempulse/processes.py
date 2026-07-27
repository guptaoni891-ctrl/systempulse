from __future__ import annotations

import time

import psutil

from systempulse.models import ProcessStats

PROCESS_ERRORS = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)


def get_top_processes(limit: int = 5, sample_interval: float = 1.0) -> list[ProcessStats]:
    tracked: list[psutil.Process] = []

    for process in psutil.process_iter(["pid", "name"]):
        try:
            process.cpu_percent(interval=None)
            tracked.append(process)
        except PROCESS_ERRORS:
            continue

    time.sleep(max(float(sample_interval), 0.1))
    results: list[ProcessStats] = []

    for process in tracked:
        try:
            results.append(
                ProcessStats(
                    pid=process.pid,
                    name=process.info.get("name") or "Unknown",
                    cpu_percent=float(process.cpu_percent(interval=None)),
                    memory_percent=float(process.memory_percent()),
                )
            )
        except PROCESS_ERRORS:
            continue

    results.sort(key=lambda item: (item.cpu_percent, item.memory_percent), reverse=True)
    return results[: max(int(limit), 1)]
