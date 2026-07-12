from ffx import recipes
from ffx.models import Recipe


def test_save_and_list_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")

    recipe = Recipe(
        name="Web MP4 + 1080p",
        description="Convert to web MP4 and scale to 1080p",
        operations=[
            {"name": "convert", "params": {"container": "mp4", "vcodec": "h264"}},
            {"name": "scale", "params": {"mode": "fit", "width": 1920, "height": 1080}},
        ],
    )

    path = recipes.save(recipe)
    assert path.exists()

    loaded = recipes.list_recipes()
    assert len(loaded) == 1
    assert loaded[0].name == recipe.name
    assert loaded[0].operations == recipe.operations


def test_list_recipes_empty_when_no_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "does-not-exist")
    assert recipes.list_recipes() == []


def test_delete_removes_file(monkeypatch, tmp_path):
    monkeypatch.setattr(recipes, "RECIPES_DIR", tmp_path / "recipes")
    recipe = Recipe(name="Temp", description="", operations=[])
    recipes.save(recipe)
    assert len(recipes.list_recipes()) == 1

    recipes.delete("Temp")
    assert len(recipes.list_recipes()) == 0
