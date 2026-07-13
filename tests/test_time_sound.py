from ffx.operations.time import _atempo_chain
from ffx.operations.sound import output_extension


def _product(stages: list[str]) -> float:
    product = 1.0
    for stage in stages:
        product *= float(stage.split("=")[1])
    return product


def test_atempo_chain_within_native_range_is_single_stage():
    stages = _atempo_chain(1.5)
    assert stages == ["atempo=1.5"]


def test_atempo_chain_decomposes_large_factors():
    for factor in (3.0, 4.0, 8.0, 20.0, 0.25, 0.1):
        stages = _atempo_chain(factor)
        assert all(0.5 <= float(s.split("=")[1]) <= 2.0 for s in stages)
        assert abs(_product(stages) - factor) < 1e-6


def test_sound_output_extension_only_set_for_extract():
    assert output_extension({"mode": "extract", "codec": "mp3"}) == "mp3"
    assert output_extension({"mode": "mute"}) is None
    assert output_extension({"mode": "volume", "method": "gain", "gain_db": 0}) is None
