from livrecuisine.parse import clean_caption, guess_category, hashtags, parse_caption

STRUCTURED = """🍝 One pot pasta crémeuse au poulet 🔥
Ultra rapide, prête en 20 min !

🛒 Ingrédients (pour 4 personnes) :
- 400 g de pâtes
- 2 blancs de poulet
- 20 cl de crème
Pour la sauce :
- 1 gousse d'ail
- parmesan

👩‍🍳 Préparation :
1️⃣ Coupe le poulet en dés et fais-le dorer.
2️⃣ Ajoute les pâtes, l'eau et la crème.
3️⃣ Laisse cuire 12 min en remuant.

💡 Astuce : ajoute des épinards.
.
.
#recette #pasta #onepot @chef"""


def test_structured_caption():
    r = parse_caption(STRUCTURED, "chef")
    assert r["title"] == "One pot pasta crémeuse au poulet"
    assert r["category"] == "Plat"
    assert r["servings"] == "4 personnes"
    assert r["ingredients"] == [
        {"group": "", "items": ["400 g de pâtes", "2 blancs de poulet", "20 cl de crème"]},
        {"group": "Pour la sauce", "items": ["1 gousse d'ail", "parmesan"]},
    ]
    assert r["steps"] == ["Coupe le poulet en dés et fais-le dorer.",
                          "Ajoute les pâtes, l'eau et la crème.",
                          "Laisse cuire 12 min en remuant."]
    assert r["tips"] == "ajoute des épinards."
    assert r["tags"] == ["recette", "pasta", "onepot"]
    assert r["is_recipe"]


def test_caption_without_headers():
    cap = """Cookies moelleux 🍪
• 200 g de farine
• 100 g de beurre
• 1 œuf
• 80 g de sucre
1. Mélange le beurre et le sucre.
2. Ajoute l'œuf puis la farine.
3. Enfourne 10 min à 180°C."""
    r = parse_caption(cap)
    assert r["title"] == "Cookies moelleux"
    assert r["category"] == "Dessert"
    assert len(r["ingredients"][0]["items"]) == 4
    assert len(r["steps"]) == 3
    assert r["is_recipe"]


def test_times():
    r = parse_caption("Quiche lorraine\nPréparation : 15 min\nCuisson : 35 min\n"
                      "Ingrédients :\n1 pâte brisée\n3 œufs\n200 g de lardons")
    assert r["prep_time"] == "15 min"
    assert r["cook_time"] == "35 min"
    assert r["ingredients"][0]["items"] == ["1 pâte brisée", "3 œufs", "200 g de lardons"]


def test_not_a_recipe():
    r = parse_caption("Trop beau coucher de soleil 🌅 #vacances #plage")
    assert not r["is_recipe"]


def test_reel_with_short_caption_is_not_guessed_as_recipe():
    r = parse_caption("La recette en vidéo 👆 Tu testes ? #food", "cheffe")
    assert r["ingredients"] == []
    assert r["title"].startswith("La recette en vidéo")


def test_clean_caption_removes_hashtag_lines_and_dots():
    text = clean_caption("Salade de lentilles\n.\n.\n.\n#salade #healthy #vegan")
    assert text == "Salade de lentilles"


def test_hashtags_unique():
    assert hashtags("#Pasta #pasta #italie") == ["pasta", "italie"]


def test_category_prefers_title():
    assert guess_category("Poulet rôti", "servi avec une sauce") == "Plat"
    assert guess_category("Pesto de basilic", "") == "Sauce"
    assert guess_category("Bidule", "") == "Autre"
