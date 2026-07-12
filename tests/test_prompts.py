from ffx.ui.prompts import clean_path_input


def test_strips_single_quotes_from_finder_copy_as_pathname():
    assert clean_path_input("'/Users/jake/My Movie.mp4'") == "/Users/jake/My Movie.mp4"


def test_strips_double_quotes():
    assert clean_path_input('"/Users/jake/My Movie.mp4"') == "/Users/jake/My Movie.mp4"


def test_unescapes_backslash_escaped_spaces_from_drag_and_drop():
    assert clean_path_input(r"/Users/jake/My\ Movie.mp4") == "/Users/jake/My Movie.mp4"


def test_leaves_plain_path_untouched():
    assert clean_path_input("/Users/jake/movie.mp4") == "/Users/jake/movie.mp4"


def test_strips_surrounding_whitespace():
    assert clean_path_input("  /Users/jake/movie.mp4  ") == "/Users/jake/movie.mp4"
