from livrecuisine.export import export_html
from livrecuisine.store import Store, empty_recipe


def test_export(tmp_path, make_jpeg):
    import os
    s = Store(str(tmp_path))
    os.replace(make_jpeg(), s.photo_path("A_1.jpg"))
    a = empty_recipe(id="A", title="Tarte <aux> pommes", category="Dessert", photos=["A_1.jpg"],
                     ingredients=[{"group": "Pâte", "items": ["200 g de farine"]}],
                     steps=["Étaler", "Cuire"], source_url="https://www.instagram.com/p/A/",
                     author="mamie")
    b = empty_recipe(id="B", title="Soupe", category="Entrée", caption="Texte brut du post")
    path = export_html(s, [a, b], str(tmp_path / "Exports" / "livre.html"))
    page = open(path, encoding="utf-8").read()
    assert "Tarte &lt;aux&gt; pommes" in page
    assert "data:image/jpeg;base64," in page
    assert "<li>Étaler</li>" in page and "<h4>Pâte</h4>" in page
    assert "Texte brut du post" in page        # recette pas découpée : texte d'origine
    assert page.index("<article id=\"r0\"") < page.index("<article id=\"r1\"")  # Dessert, puis Entrée
    assert "@mamie" in page
