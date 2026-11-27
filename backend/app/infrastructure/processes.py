"""Bounded, cancellation-aware subprocess lifecycle shared by media adapters."""

import os
import signal
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress


def terminate_process(process: subprocess.Popen[str], grace_seconds: float = 5) -> None:
    """Reap the process and its session children, including uncooperative decoders."""

    def send(sig: signal.Signals) -> None:
        with suppress(ProcessLookupError):
            if os.name == "posix":
                os.killpg(process.pid, sig)
            else:
                process.send_signal(sig)

    if process.poll() is None:
        send(signal.SIGTERM)
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            send(signal.SIGKILL)
            process.wait()
    # The leader may exit while a child continues to hold a pipe open.
    if os.name == "posix":
        send(signal.SIGKILL)


def capture_process(
    command: list[str], *, timeout: float, check_stop: Callable[[], None]
) -> subprocess.CompletedProcess[str]:
    check_stop()
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name == "posix",
    ) as process:
        try:
            while True:
                check_stop()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    check_stop()
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            terminate_process(process)
