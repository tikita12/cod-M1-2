import json
from functools import lru_cache
from app.config import ROOT


@lru_cache(maxsize=1)
def agricultural_categories():
    data = json.loads((ROOT / "data/config/item_categories.json").read_text(encoding="utf-8"))
    return {name: category for category, names in data["included_categories"].items() for name in names}
