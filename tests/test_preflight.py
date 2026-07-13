import subprocess

from ffx import preflight


def _which(paths: dict):
    return lambda name: paths.get(name)


def test_check_is_silent_when_everything_is_present(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight.shutil, "which", _which({"ffmpeg": "/usr/local/bin/ffmpeg", "ffprobe": "/usr/local/bin/ffprobe"})
    )
    assert preflight.check() is True
    assert capsys.readouterr().out == ""


def test_check_guides_manual_install_when_brew_missing(monkeypatch, capsys):
    monkeypatch.setattr(preflight.shutil, "which", _which({}))
    assert preflight.check() is False
    out = capsys.readouterr().out
    assert "brew.sh" in out
    assert "brew install ffmpeg" in out


def test_check_offers_and_runs_brew_install(monkeypatch, capsys):
    calls = []

    def fake_which(name):
        if name == "brew":
            return "/opt/homebrew/bin/brew"
        # Missing until "installed" by the fake brew run below.
        return "/opt/homebrew/bin/ffmpeg" if calls and name in ("ffmpeg", "ffprobe") else None

    monkeypatch.setattr(preflight.shutil, "which", fake_which)
    monkeypatch.setattr(preflight.prompts, "ask_confirm", lambda *a, **k: True)

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    assert preflight.check() is True
    assert calls == [["/opt/homebrew/bin/brew", "install", "ffmpeg"]]
    assert "installed" in capsys.readouterr().out


def test_check_respects_decline_to_install(monkeypatch, capsys):
    monkeypatch.setattr(preflight.shutil, "which", _which({"brew": "/opt/homebrew/bin/brew"}))
    monkeypatch.setattr(preflight.prompts, "ask_confirm", lambda *a, **k: False)
    assert preflight.check() is False
    assert "brew install ffmpeg" in capsys.readouterr().out


def test_check_reports_failure_when_brew_install_fails(monkeypatch, capsys):
    monkeypatch.setattr(preflight.shutil, "which", _which({"brew": "/opt/homebrew/bin/brew"}))
    monkeypatch.setattr(preflight.prompts, "ask_confirm", lambda *a, **k: True)
    monkeypatch.setattr(
        preflight.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 1)
    )
    assert preflight.check() is False
    assert "didn't finish cleanly" in capsys.readouterr().out
