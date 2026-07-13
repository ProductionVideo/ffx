from pathlib import Path

from ffx import analyse
from ffx.runner import FFmpegCancelled


def test_run_qc_black_passes_duration_and_description(monkeypatch):
    captured = {}

    def fake_run_with_output(args, *, total_duration, console, description):
        captured["total_duration"] = total_duration
        captured["description"] = description
        return "black_start:1.0 black_end:2.0 black_duration:1.0\n"

    monkeypatch.setattr(analyse, "run_with_output", fake_run_with_output)
    findings = analyse.run_qc(Path("in.mp4"), ["black"], duration=42.0, console=None)

    assert captured["total_duration"] == 42.0
    assert captured["description"] == "Checking for black sections"
    assert findings.black_sections == [(1.0, 2.0, 1.0)]


def test_run_qc_silence_and_freeze_descriptions(monkeypatch):
    descriptions = []

    def fake_run_with_output(args, *, total_duration, console, description):
        descriptions.append(description)
        return ""

    monkeypatch.setattr(analyse, "run_with_output", fake_run_with_output)
    analyse.run_qc(Path("in.mp4"), ["silence", "freeze"], duration=10.0, console=None)

    assert descriptions == ["Checking for silent sections", "Checking for frozen sections"]


def test_run_filter_cancel_raises_plain_keyboard_interrupt(monkeypatch):
    # Ctrl+C should mean "bail out of the whole app" everywhere in ffx,
    # not a special-cased behavior just for this scan.
    def raise_cancelled(*a, **k):
        raise FFmpegCancelled("cancelled by user")

    monkeypatch.setattr(analyse, "run_with_output", raise_cancelled)
    try:
        analyse._run_filter(Path("in.mp4"), 10.0, None, "Checking", vf="blackdetect=d=0.1")
        assert False, "expected KeyboardInterrupt"
    except FFmpegCancelled:
        assert False, "FFmpegCancelled should not escape _run_filter"
    except KeyboardInterrupt:
        pass
