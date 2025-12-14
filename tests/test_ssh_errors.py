from __future__ import annotations

from merlya.tools.core.ssh_errors import explain_ssh_error


def test_explain_ssh_error_detects_circuit_breaker_open() -> None:
    err = RuntimeError(
        "🔌 Circuit breaker open for 192.168.1.5. Too many failures. Retry in 12.3s or use reset_circuit()"
    )
    info = explain_ssh_error(err, host="192.168.1.5")
    assert "circuit breaker open" in info.symptom.lower()
    assert "wait" in info.suggestion.lower()


def test_explain_ssh_error_detects_channel_open_failed() -> None:
    err = RuntimeError("SSH failed: open failed")
    info = explain_ssh_error(err, host="192.168.1.5")
    assert "channel open failed" in info.symptom.lower()
