from ffx import hardware

_SAMPLE_FILTERS_OUTPUT = """Filters:
  T.. drawtext           V->V       Draw text on top of video frames using libfreetype library.
  ... crop               V->V       Crop the input video.
  .S. scale              V->V       Scale the input video size and/or convert the image format.
"""


def test_detect_parses_filter_names(monkeypatch):
    hardware.detect.cache_clear()

    def fake_run(args):
        if "-filters" in args:
            return _SAMPLE_FILTERS_OUTPUT
        return ""

    monkeypatch.setattr(hardware, "_run", fake_run)
    caps = hardware.detect()

    assert caps.has_filter("drawtext")
    assert caps.has_filter("crop")
    assert not caps.has_filter("lut3d")
    hardware.detect.cache_clear()
