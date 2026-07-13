import io
import selectors
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ffx.runner import FFmpegCancelled, run, run_with_output


def test_keyboard_interrupt_kills_process_and_removes_partial_output(tmp_path):
    out_path = tmp_path / "out.mp4"
    out_path.write_bytes(b"partial data written before cancellation")
    argv = ["ffmpeg", "-y", "-i", "in.mp4", str(out_path)]

    fake_process = MagicMock()
    fake_process.stdout = io.StringIO("")
    fake_process.stderr = io.StringIO("")

    with patch("subprocess.Popen", return_value=fake_process), \
         patch.object(selectors.DefaultSelector, "register"), \
         patch.object(selectors.DefaultSelector, "select", side_effect=KeyboardInterrupt):
        try:
            run(argv, total_duration=10)
            assert False, "expected FFmpegCancelled to be raised"
        except FFmpegCancelled:
            pass

    fake_process.terminate.assert_called_once()
    assert not out_path.exists()


def test_keyboard_interrupt_force_kills_if_terminate_hangs(tmp_path):
    out_path = tmp_path / "out.mp4"
    out_path.write_bytes(b"partial")
    argv = ["ffmpeg", "-y", "-i", "in.mp4", str(out_path)]

    fake_process = MagicMock()
    fake_process.stdout = io.StringIO("")
    fake_process.stderr = io.StringIO("")
    fake_process.wait.side_effect = [subprocess.TimeoutExpired(cmd="ffmpeg", timeout=3), None]

    with patch("subprocess.Popen", return_value=fake_process), \
         patch.object(selectors.DefaultSelector, "register"), \
         patch.object(selectors.DefaultSelector, "select", side_effect=KeyboardInterrupt):
        try:
            run(argv, total_duration=10)
            assert False, "expected FFmpegCancelled"
        except FFmpegCancelled:
            pass

    fake_process.terminate.assert_called_once()
    fake_process.kill.assert_called_once()
    assert not out_path.exists()


def test_run_with_output_returns_captured_stderr_and_shows_progress():
    fake_process = MagicMock()
    stdout = io.StringIO("progress=end\n")
    stderr = io.StringIO("blackdetect stuff\nmore output\n")
    fake_process.stdout = stdout
    fake_process.stderr = stderr
    fake_process.wait.return_value = 0

    stdout_key = SimpleNamespace(fileobj=stdout, data="stdout")
    stderr_key = SimpleNamespace(fileobj=stderr, data="stderr")
    select_sequence = iter(
        [
            [(stdout_key, 1)],
            [(stderr_key, 1)],
            [(stderr_key, 1)],
            [(stdout_key, 1)],  # EOF for stdout
            [(stderr_key, 1)],  # EOF for stderr
        ]
    )

    with patch("subprocess.Popen", return_value=fake_process), \
         patch.object(selectors.DefaultSelector, "register"), \
         patch.object(selectors.DefaultSelector, "unregister"), \
         patch.object(selectors.DefaultSelector, "select", side_effect=lambda *a, **k: next(select_sequence)):
        result = run_with_output(
            ["ffmpeg", "-i", "in.mp4", "-f", "null", "-"], total_duration=10, description="Checking"
        )

    assert result == "blackdetect stuff\nmore output\n"


def test_run_with_output_raises_ffmpeg_cancelled_on_keyboard_interrupt():
    fake_process = MagicMock()
    fake_process.stdout = io.StringIO("")
    fake_process.stderr = io.StringIO("")

    with patch("subprocess.Popen", return_value=fake_process), \
         patch.object(selectors.DefaultSelector, "register"), \
         patch.object(selectors.DefaultSelector, "select", side_effect=KeyboardInterrupt):
        try:
            run_with_output(["ffmpeg", "-i", "in.mp4", "-f", "null", "-"], total_duration=10)
            assert False, "expected FFmpegCancelled"
        except FFmpegCancelled:
            pass

    fake_process.terminate.assert_called_once()
