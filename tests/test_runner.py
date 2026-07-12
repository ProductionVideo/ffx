import io
import selectors
import subprocess
from unittest.mock import MagicMock, patch

from ffx.runner import FFmpegCancelled, run


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
