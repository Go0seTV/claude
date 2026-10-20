import pytest

from livrecuisine import nutrition
from livrecuisine.nutrition import analyse_line, compute, portions_of


@pytest.mark.parametrize("line, food, grams", [
    ("400 g de pâtes", "pâtes", 400),
    ("1 kg de pommes de terre", "pomme de terre", 1000),
    ("20 cl de crème", "crème", 200),
    ("2 blancs de poulet", "poulet", 260),
    ("3 œufs", "œuf", 150),
    ("3 blancs", "blanc d'œuf", 96),
    ("1 c. à soupe d'huile d'olive", "huile", 13.8),
    ("1 cuillère à café de sucre", "sucre", 4.25),
    ("2 cs de miel", "miel", 42),
    ("2 pots de sucre", "sucre", 212.5),       # gâteau au yaourt : le pot sert de mesure
    ("1 pot de yaourt", "yaourt", 125),
    ("½ citron", "citron", 50),
    ("1/2 oignon", "oignon", 50),
    ("2 à 3 carottes", "carotte", 225),
    ("Poulet (500 g)", "poulet", 500),
    ("2 boîtes de pois chiches (400 g)", "pois chiches", 800),
    ("1 sachet de levure chimique", "levure", 11),
    ("1 sachet de sucre vanillé", "sucre vanillé", 7.5),
    ("1 noisette de beurre", "beurre", 5),
    ("2 noix de beurre", "beurre", 20),
    ("1 filet d'huile d'olive", "huile", 4.6),
    ("2 filets de cabillaud", "cabillaud", 250),
    ("4 tranches de jambon", "jambon", 160),
    ("1 pâte feuilletée", "pâte feuilletée", 230),
    ("100 g de lait de coco", "lait de coco", 100),  # le nom le plus long gagne
    ("une gousse d'ail", "ail", 5),
    ("1,5 l de lait", "lait", 1545),
])
def test_quantities(line, food, grams):
    r = analyse_line(line)
    assert r["status"] == "ok", r
    assert r["food"] == food
    assert r["grams"] == pytest.approx(grams, rel=0.01)


def test_neutral_unknown_and_missing_quantity():
    assert analyse_line("Sel, poivre")["status"] == "neutre"
    assert analyse_line("une pincée de sel")["status"] == "neutre"
    assert analyse_line("quelques feuilles de basilic")["status"] == "neutre"
    assert analyse_line("parmesan")["status"] == "quantite"
    assert analyse_line("200 g de truc bizarre")["status"] == "inconnu"


def test_values():
    r = analyse_line("200 g de farine")
    assert r["kcal"] == pytest.approx(690)
    assert r["prot"] == pytest.approx(20) and r["gluc"] == pytest.approx(144)
    assert r["lip"] == pytest.approx(2.4)


def test_portions():
    assert portions_of("4 personnes") == 4
    assert portions_of("4 à 6 parts") == 5
    assert portions_of("") is None and portions_of("beaucoup") is None


def test_compute_recipe():
    rec = {"servings": "4 personnes", "ingredients": [
        {"group": "", "items": ["400 g de pâtes", "2 blancs de poulet", "20 cl de crème"]},
        {"group": "Pour la sauce", "items": ["1 gousse d'ail", "parmesan", "sel"]}]}
    m = compute(rec)
    assert m["counted"] == 4 and m["portions"] == 4
    assert m["total"]["kcal"] == pytest.approx(1420 + 314.6 + 584 + 6.5, rel=0.01)
    assert m["per_portion"]["kcal"] == pytest.approx(m["total"]["kcal"] / 4)
    assert [l["line"] for l in m["missing"]] == ["parmesan"]
    assert nutrition.summary(m["per_portion"]).startswith("581 kcal · Protéines")


def test_compute_without_servings_or_ingredients():
    assert compute({"ingredients": [{"group": "", "items": ["2 œufs"]}]})["per_portion"] is None
    assert compute({})["counted"] == 0


def test_every_food_is_sane():
    for food in set(nutrition._INDEX.values()):
        if food.neutral or food.name in ("vin", "bière", "rhum"):  # kcal de l'alcool
            continue
        atwater = 4 * food.prot + 4 * food.gluc + 9 * food.lip
        assert food.prot + food.gluc + food.lip <= 101, food.name
        # les kcal annoncées collent aux macros (à l'alcool et aux fibres près)
        assert abs(atwater - food.kcal) <= max(45, 0.2 * food.kcal), (food.name, atwater)
