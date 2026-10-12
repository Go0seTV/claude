import os

from livrecuisine.store import (Store, empty_recipe, ingredients_to_text, text_to_ingredients,
                                text_to_steps)


def test_put_query_reload(tmp_path):
    s = Store(str(tmp_path))
    s.put(empty_recipe(id="A1", title="Crème brûlée", category="Dessert",
                       ingredients=[{"group": "", "items": ["50 cl de crème"]}]))
    s.put(empty_recipe(id="B2", title="Paysage", is_recipe=False))
    rid = s.put(empty_recipe(title="Poulet curry", category="Plat", favorite=True))
    assert rid.startswith("manuel-")

    assert [r["id"] for r in s.query("creme")] == ["A1"]  # sans accent
    assert [r["id"] for r in s.query("brulee creme")] == ["A1"]
    assert [r["title"] for r in s.query()] == ["Crème brûlée", "Poulet curry"]
    assert [r["id"] for r in s.query(show="others")] == ["B2"]
    assert [r["title"] for r in s.query(favorites=True)] == ["Poulet curry"]
    assert [r["title"] for r in s.query(category="Dessert")] == ["Crème brûlée"]
    assert s.categories() == ["Dessert", "Plat"]

    s2 = Store(str(tmp_path))
    assert s2.has("A1") and s2.get("A1")["title"] == "Crème brûlée"
    assert len(s2.all()) == 3


def test_delete_removes_photos(tmp_path, make_jpeg):
    s = Store(str(tmp_path / "livre"))
    photo = s.photo_path("X_1.jpg")
    os.replace(make_jpeg(), photo)
    s.put(empty_recipe(id="X", photos=["X_1.jpg"]))
    s.delete("X")
    assert not s.has("X")
    assert not os.path.exists(photo)
    assert not Store(str(tmp_path / "livre")).has("X")


def test_ingredients_text_round_trip():
    groups = [{"group": "", "items": ["200 g de farine", "1 œuf"]},
              {"group": "Pour la sauce", "items": ["sel", "poivre"]}]
    text = ingredients_to_text(groups)
    assert text == "200 g de farine\n1 œuf\n\nPour la sauce :\nsel\npoivre"
    assert text_to_ingredients(text) == groups
    assert text_to_ingredients("Pour la pâte :\n- 100 g de beurre") == [
        {"group": "Pour la pâte", "items": ["100 g de beurre"]}]


def test_steps_from_text():
    assert text_to_steps("1. Mélanger\n\n2) Cuire 10 min\n- Servir") == [
        "Mélanger", "Cuire 10 min", "Servir"]
