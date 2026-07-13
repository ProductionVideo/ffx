from pathlib import Path

from ffx.operations import composite as composite_op


def test_watermark_video_has_no_loop_arg():
    op = composite_op.build(
        {"mode": "watermark", "overlay_path": "logo.mp4", "position": "bottom-right", "opacity": 0.8}, None, None
    )
    assert op.extra_inputs == [Path("logo.mp4")]
    assert op.extra_input_args == [[]]
    assert op.filter_complex == (
        "[{in0}]format=rgba,colorchannelmixer=aa=0.8[wm];"
        "[0:v][wm]overlay=main_w-overlay_w-20:main_h-overlay_h-20:shortest=1[outv]"
    )
    assert op.output_args == ["-map", "[outv]", "-map", "0:a?"]


def test_watermark_image_gets_loop_arg():
    op = composite_op.build(
        {"mode": "watermark", "overlay_path": "logo.png", "position": "center", "opacity": 1.0}, None, None
    )
    assert op.extra_input_args == [["-loop", "1"]]
    assert "(main_w-overlay_w)/2" in op.filter_complex


def test_pip_scales_by_percent():
    op = composite_op.build(
        {"mode": "pip", "overlay_path": "cam.mp4", "position": "top-left", "scale_percent": 25}, None, None
    )
    assert op.filter_complex == (
        "[{in0}]scale=iw*0.25:ih*0.25[pip];[0:v][pip]overlay=20:20:shortest=1[outv]"
    )


def test_stack_horizontal_uses_modern_scale_not_deprecated_scale2ref():
    op = composite_op.build({"mode": "stack", "second_path": "b.mp4", "direction": "horizontal"}, None, None)
    assert op.filter_complex == "[{in0}][0:v]scale=w=-2:h=rh[ov];[0:v][ov]hstack=inputs=2[outv]"
    assert "scale2ref" not in op.filter_complex


def test_stack_vertical():
    op = composite_op.build({"mode": "stack", "second_path": "b.mp4", "direction": "vertical"}, None, None)
    assert op.filter_complex == "[{in0}][0:v]scale=w=rw:h=-2[ov];[0:v][ov]vstack=inputs=2[outv]"


def test_chromakey_scales_background_to_match_foreground():
    op = composite_op.build(
        {"mode": "chromakey", "background_path": "bg.png", "color": "0x00FF00", "similarity": 0.25, "blend": 0.05},
        None,
        None,
    )
    assert op.filter_complex == (
        "[{in0}][0:v]scale=w=rw:h=rh[bg];"
        "[0:v]chromakey=0x00FF00:0.25:0.05[fg];"
        "[bg][fg]overlay=shortest=1[outv]"
    )
    assert op.extra_input_args == [["-loop", "1"]]
