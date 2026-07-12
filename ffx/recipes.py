from __future__ import annotations

import json
import re
from pathlib import Path

from ffx.models import Recipe

RECIPES_DIR = Path.home() / ".config" / "ffx" / "recipes"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "recipe"


def _path_for(name: str) -> Path:
    return RECIPES_DIR / f"{_slug(name)}.json"


def save(recipe: Recipe) -> Path:
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(recipe.name)
    path.write_text(json.dumps(recipe.to_dict(), indent=2))
    return path


def list_recipes() -> list[Recipe]:
    if not RECIPES_DIR.exists():
        return []
    recipes = []
    for path in sorted(RECIPES_DIR.glob("*.json")):
        try:
            recipes.append(Recipe.from_dict(json.loads(path.read_text())))
        except (json.JSONDecodeError, KeyError):
            continue
    return recipes


def delete(name: str) -> None:
    _path_for(name).unlink(missing_ok=True)
