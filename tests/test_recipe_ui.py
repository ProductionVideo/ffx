from ffx import __main__ as ffx_main
from ffx import recipes
from ffx.models import OperationSettings, Recipe
from ffx.operations import get_operation
from ffx.ui import prompts


def _op(name, description):
    return OperationSettings(name=name, display_name=name.title(), description=description)


def test_save_recipe_generates_description_from_operations(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")
    monkeypatch.setattr(prompts, "ask_text", lambda *args, **kwargs: "My Recipe")

    ordered_ops = [
        (get_operation("convert"), {"container": "mp4"}),
        (get_operation("scale"), {"mode": "fit"}),
    ]
    operations = [
        _op("convert", "Convert to MP4, target ~25 MB (2-pass)"),
        _op("scale", "Scale to fit 1920x1080"),
    ]

    ffx_main._save_recipe(ordered_ops, operations)

    saved = recipes.list_recipes()
    assert len(saved) == 1
    assert saved[0].name == "My Recipe"
    assert saved[0].description == "Convert to MP4, target ~25 MB (2-pass) → Scale to fit 1920x1080"
    assert saved[0].operations == [
        {"name": "convert", "params": {"container": "mp4"}},
        {"name": "scale", "params": {"mode": "fit"}},
    ]


def test_pick_recipe_delete_option_does_not_load_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")
    saved_recipes = [Recipe(name="Old one", description="Convert to MP4", operations=[])]

    monkeypatch.setattr(prompts, "choose", lambda *args, **kwargs: ffx_main._DELETE_RECIPES)
    called = {}
    monkeypatch.setattr(ffx_main, "_delete_recipes", lambda recs: called.setdefault("recs", recs))

    result = ffx_main._pick_recipe(saved_recipes)

    assert result is None
    assert called["recs"] == saved_recipes


def test_delete_recipes_removes_confirmed_selection(monkeypatch, tmp_path):
    # multi_choose is mocked to return indexes, not Recipe objects - that's
    # the real calling convention (see the comment in _pick_recipe): a
    # dataclass round-tripped through InquirerPy's checkbox has been
    # confirmed to come back as a plain dict, not the original Recipe.
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")
    recipe_a = Recipe(name="A", description="", operations=[])
    recipe_b = Recipe(name="B", description="", operations=[])
    recipes.save(recipe_a)
    recipes.save(recipe_b)

    monkeypatch.setattr(prompts, "multi_choose", lambda *args, **kwargs: [0])
    monkeypatch.setattr(prompts, "ask_confirm", lambda *args, **kwargs: True)

    ffx_main._delete_recipes([recipe_a, recipe_b])

    remaining = {r.name for r in recipes.list_recipes()}
    assert remaining == {"B"}


def test_delete_recipes_noop_when_nothing_selected(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")
    recipe_a = Recipe(name="A", description="", operations=[])
    recipes.save(recipe_a)

    monkeypatch.setattr(prompts, "multi_choose", lambda *args, **kwargs: [])

    ffx_main._delete_recipes([recipe_a])

    assert len(recipes.list_recipes()) == 1


def test_delete_recipes_noop_when_confirm_declined(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")
    recipe_a = Recipe(name="A", description="", operations=[])
    recipes.save(recipe_a)

    monkeypatch.setattr(prompts, "multi_choose", lambda *args, **kwargs: [0])
    monkeypatch.setattr(prompts, "ask_confirm", lambda *args, **kwargs: False)

    ffx_main._delete_recipes([recipe_a])

    assert len(recipes.list_recipes()) == 1


def test_pick_recipe_loads_by_index(monkeypatch, tmp_path):
    # choose is mocked to return an index, not the Recipe object itself -
    # same reasoning as above, for the single-select "Which recipe?" menu.
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")
    recipe_a = Recipe(name="A", description="", operations=[{"name": "cut", "params": {"mode": "from_start"}}])
    recipe_b = Recipe(name="B", description="", operations=[])

    monkeypatch.setattr(prompts, "choose", lambda *args, **kwargs: 0)

    ordered_ops = ffx_main._pick_recipe([recipe_a, recipe_b])

    assert len(ordered_ops) == 1
    module, params = ordered_ops[0]
    assert module.name == "cut"
    assert params == {"mode": "from_start"}
