from ffx.ui import prompts


def _answer(value):
    """A render() callable that just answers with `value` (never back)."""
    return lambda: (value, False)


def _back():
    """A render() callable that reports the user pressed back."""
    return lambda: (None, True)


def test_run_wizard_returns_value_when_never_backed(monkeypatch):
    def fn():
        a = prompts._step(_answer("a"))
        b = prompts._step(_answer("b"))
        return (a, b)

    assert prompts.run_wizard(fn) == ("a", "b")


def test_run_wizard_returns_none_when_back_on_first_question():
    def fn():
        return prompts._step(_back())

    assert prompts.run_wizard(fn) is None


def test_back_reasks_only_the_popped_step():
    # Simulates a 3-question flow: all three get answered, then the user
    # backs out of Q3, is re-asked Q2 (answering differently), then Q3
    # again - Q1's answer must replay from history, not re-prompt.
    render_sequence = iter(
        [
            ("codec-h264", False),
            ("container-mp4", False),
            (None, True),  # back on q3
            ("container-mov", False),  # q2 re-rendered after the pop
            ("final", False),  # q3 answered for real this time
        ]
    )
    seen = []

    def render_step(name):
        def _render():
            seen.append(name)
            return next(render_sequence)
        return _render

    def fn():
        q1 = prompts._step(render_step("q1"))
        q2 = prompts._step(render_step("q2"))
        q3 = prompts._step(render_step("q3"))
        return (q1, q2, q3)

    result = prompts.run_wizard(fn)
    assert result == ("codec-h264", "container-mov", "final")
    # q1 was only ever rendered once (its answer replayed from history on
    # the second pass instead of being re-prompted).
    assert seen.count("q1") == 1
    assert seen.count("q2") == 2
    assert seen.count("q3") == 2


def test_nested_run_wizard_has_independent_back_stack():
    def inner():
        return prompts._step(_answer("inner-answer"))

    def outer():
        first = prompts._step(_answer("outer-first"))
        nested_result = prompts.run_wizard(inner)
        second = prompts._step(_answer("outer-second"))
        return (first, nested_result, second)

    assert prompts.run_wizard(outer) == ("outer-first", "inner-answer", "outer-second")


def test_run_wizard_without_active_wizard_just_runs_once():
    # prompts._step() falls back to a plain call when there's no active
    # run_wizard() - e.g. Step 1's input picker, which has nothing to
    # back into.
    assert prompts._step(_answer("x")) == "x"
