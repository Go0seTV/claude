"""Calcul des macros d'une recette : kcal, protéines, glucides, lipides.

Tout se fait sur le PC, sans internet : chaque ligne d'ingrédient est lue (« 200 g de
farine », « 2 œufs », « 1 c. à soupe d'huile »), convertie en grammes, puis reconnue dans la
table d'aliments ci-dessous (valeurs moyennes pour 100 g d'aliment cru, arrondies, d'après les
tables de composition courantes comme Ciqual). C'est une estimation : compte ± 15 %.
"""

import re
import unicodedata


class Food:
    __slots__ = ("name", "kcal", "prot", "gluc", "lip", "piece", "density", "neutral")

    def __init__(self, name, kcal, prot, gluc, lip, piece=None, density=1.0, neutral=False):
        self.name = name
        self.kcal, self.prot, self.gluc, self.lip = kcal, prot, gluc, lip
        self.piece = piece        # poids d'une pièce en g (1 œuf, 1 oignon…), si ça a un sens
        self.density = density    # g par ml, pour les cuillères, verres, cl…
        self.neutral = neutral    # sel, épices, eau : ne compte pas, et n'est pas « oublié »


# (noms séparés par « | », kcal, protéines, glucides, lipides pour 100 g, pièce en g, g/ml)
_TABLE = [
    # Œufs et produits laitiers
    ("oeuf|oeufs|oeuf entier", 140, 12.7, 0.7, 9.8, 50),
    ("jaune d'oeuf|jaunes d'oeufs|jaune|jaunes", 320, 16, 0.5, 28, 18),
    ("blanc d'oeuf|blancs d'oeufs|blanc d'oeufs|blanc|blancs", 47, 10.5, 0.7, 0.2, 32),
    ("lait|lait demi-ecreme|lait demi ecreme", 46, 3.3, 4.8, 1.6, None, 1.03),
    ("lait entier", 64, 3.3, 4.7, 3.6, None, 1.03),
    ("lait ecreme", 34, 3.4, 4.9, 0.1, None, 1.03),
    ("lait de coco", 190, 1.9, 3, 19),
    ("creme de coco", 330, 3, 6, 33),
    ("lait d'amande|boisson amande", 24, 0.5, 3, 1.1),
    ("lait d'avoine|boisson avoine", 45, 0.8, 7, 1.4),
    ("lait de soja|boisson soja", 40, 3.3, 2.5, 1.8),
    ("lait concentre sucre", 330, 8, 55, 8.5, None, 1.3),
    ("creme|creme fraiche|creme liquide|creme entiere|creme epaisse|creme fleurette|"
     "creme fraiche epaisse|creme fraiche liquide", 292, 2.4, 3, 30),
    ("creme legere|creme allegee|creme 15|creme fraiche legere", 160, 2.7, 4, 15),
    ("beurre|beurre doux|beurre demi-sel|beurre fondu|beurre mou", 745, 0.7, 0.6, 82, None, 0.95),
    ("margarine", 700, 0.2, 0.5, 78, None, 0.95),
    ("yaourt|yaourt nature|yaourts|yogourt", 61, 4.3, 5.5, 2.1, 125),
    ("yaourt grec|yaourt a la grecque", 120, 5, 4, 9.5, 150),
    ("skyr", 63, 11, 4, 0.2, 150),
    ("fromage blanc", 75, 7.5, 4, 3),
    ("faisselle", 60, 6, 4, 2.5, 100),
    ("mascarpone", 435, 4.5, 3.5, 44),
    ("ricotta", 150, 9, 3.5, 11),
    ("mozzarella|mozza", 250, 18, 1, 19, 125),
    ("burrata", 300, 15, 1, 27, 125),
    ("parmesan|parmigiano|grana padano", 400, 35, 0, 29),
    ("emmental|gruyere|comte|fromage rape|beaufort", 380, 28, 0.5, 29, None, 0.4),
    ("cheddar", 400, 25, 1, 33),
    ("chevre|fromage de chevre|buche de chevre", 300, 18, 1, 25),
    ("feta", 260, 15, 1.5, 21),
    ("camembert|brie", 300, 20, 0.5, 24, 250),
    ("reblochon|raclette|fromage a raclette", 330, 22, 0.5, 27),
    ("roquefort|bleu|gorgonzola", 360, 20, 0.5, 31),
    ("fromage frais|philadelphia|cream cheese|st moret|saint moret|kiri", 250, 6, 4, 23),
    ("fromage", 350, 23, 1, 28),
    # Viandes, poissons, protéines végétales
    ("poulet|blanc de poulet|blancs de poulet|escalope de poulet|filet de poulet|"
     "filets de poulet|aiguillettes de poulet", 121, 23, 0, 2.5, 130),
    ("cuisse de poulet|cuisses de poulet|haut de cuisse", 190, 18, 0, 13, 150),
    ("dinde|escalope de dinde|blanc de dinde", 110, 24, 0, 1.5, 120),
    ("boeuf hache|steak hache|viande hachee|hache", 175, 19, 0, 10, 125),
    ("boeuf|steak|bavette|rumsteck|faux-filet|boeuf a braiser|paleron|basse cote", 150, 21, 0,
     7, 150),
    ("entrecote|cote de boeuf", 200, 20, 0, 13, 250),
    ("veau|escalope de veau", 120, 21, 0, 4, 120),
    ("porc|filet mignon|cote de porc|echine|roti de porc", 150, 20, 0, 8, 150),
    ("lardons|lardon|poitrine fumee|poitrine de porc", 270, 16, 0.5, 23),
    ("bacon", 230, 18, 0.5, 17, 15),
    ("jambon|jambon blanc|jambon cuit", 115, 20, 1, 3.5, 40),
    ("jambon cru|jambon de parme|jambon serrano|prosciutto", 240, 27, 0.5, 15, 15),
    ("chorizo", 450, 24, 2, 38),
    ("saucisse|saucisses|chipolata|chipolatas", 270, 15, 1, 23, 70),
    ("merguez", 290, 15, 1, 25, 50),
    ("agneau|gigot|epaule d'agneau", 230, 18, 0, 17, 150),
    ("canard|magret|magret de canard", 200, 19, 0, 14, 350),
    ("saumon|pave de saumon|paves de saumon|filet de saumon|filets de saumon", 200, 20, 0, 13,
     125),
    ("saumon fume", 180, 22, 0, 10, 25),
    ("thon|thon au naturel|thon en boite", 115, 26, 0, 1, None),
    ("cabillaud|colin|lieu|merlu|poisson blanc|dos de cabillaud|filet de cabillaud", 80, 18, 0,
     0.7, 125),
    ("crevettes|crevette|gambas", 95, 20, 0, 1.5, 15),
    ("moules", 85, 12, 3, 2),
    ("surimi", 100, 8, 15, 1, 15),
    ("sardines|sardine", 210, 24, 0, 13, 25),
    ("tofu", 125, 13, 1.5, 7.5),
    ("tofu soyeux", 55, 5, 1.5, 3),
    # Féculents, céréales, légumineuses (crus sauf mention)
    ("pates|spaghetti|spaghettis|tagliatelles|tagliatelle|penne|linguine|macaroni|"
     "coquillettes|fusilli|farfalle|rigatoni|lasagnes|feuilles de lasagne|vermicelles|"
     "orzo|pates seches", 355, 12.5, 70, 1.5),
    ("pates fraiches|tortellini|ravioli", 280, 11, 50, 3),
    ("nouilles|nouilles de riz|vermicelles de riz|nouilles chinoises|udon|ramen", 360, 6, 80,
     1),
    ("riz|riz basmati|riz thai|riz complet|riz rond|riz arborio|riz a risotto", 350, 7, 78,
     0.6, None, 0.85),
    ("riz cuit", 130, 2.7, 28, 0.3),
    ("quinoa", 370, 14, 64, 6, None, 0.85),
    ("semoule|couscous|graine de couscous", 360, 12, 73, 1.5, None, 0.75),
    ("boulgour", 350, 12, 70, 1.5, None, 0.8),
    ("lentilles|lentilles corail|lentilles vertes", 330, 24, 50, 1.5, None, 0.85),
    ("pois chiches|pois chiche", 150, 8, 20, 2.6),
    ("haricots rouges", 115, 8, 16, 0.5),
    ("haricots blancs|flageolets", 110, 7.5, 15, 0.5),
    ("pomme de terre|pommes de terre|patate|patates|pdt", 80, 2, 17, 0.1, 150),
    ("patate douce|patates douces", 86, 1.6, 20, 0.1, 250),
    ("farine|farine de ble|farine t45|farine t55|farine t65", 345, 10, 72, 1.2, None, 0.55),
    ("farine complete|farine t80|farine t110|farine de seigle|farine d'epeautre", 330, 12, 62,
     2, None, 0.55),
    ("farine de riz", 360, 6, 80, 1.4, None, 0.6),
    ("maizena|fecule|fecule de mais|amidon", 350, 0.3, 87, 0.1, None, 0.6),
    ("flocons d'avoine|avoine|porridge", 370, 13, 58, 7, None, 0.4),
    ("pain|baguette|pain de campagne|pain complet", 260, 9, 50, 1.5, 250),
    ("pain de mie", 270, 8.5, 48, 4.5, 25),
    ("pain burger|pains burger|pain a burger|pains a burger|buns|bun|pain hamburger", 280, 9,
     49, 5, 60),
    ("tortilla|tortillas|wrap|wraps|galette de ble", 300, 8, 50, 7, 40),
    ("pate feuilletee", 400, 5.5, 37, 25, 230),
    ("pate brisee", 420, 6, 45, 24, 230),
    ("pate sablee", 450, 6, 55, 22, 230),
    ("pate a pizza", 260, 8, 48, 3.5, 260),
    ("pate filo|feuilles de brick|brick", 300, 9, 60, 2, 10),
    ("chapelure|panure", 380, 12, 72, 4, None, 0.45),
    ("gnocchi|gnocchis", 150, 3.5, 32, 0.5),
    ("biscuits|biscuit|speculoos|petits beurre|petit beurre|sables", 460, 6.5, 73, 15, 8),
    ("boudoirs|biscuits a la cuillere", 390, 8, 82, 3.5, 5),
    ("cereales|corn flakes", 380, 7, 84, 1),
    # Sucres et produits sucrés
    ("sucre|sucre en poudre|sucre blanc|cassonade|sucre roux|vergeoise|sucre de canne|"
     "sucre complet|rapadura|sucre de coco", 400, 0, 100, 0, None, 0.85),
    ("sucre glace", 400, 0, 100, 0, None, 0.5),
    ("sucre vanille", 400, 0, 100, 0, 7.5),
    ("miel", 330, 0.4, 82, 0, None, 1.4),
    ("sirop d'erable", 260, 0, 67, 0.1, None, 1.32),
    ("sirop d'agave|agave", 310, 0, 76, 0, None, 1.35),
    ("chocolat|chocolat noir|chocolat patissier|pepites de chocolat|chocolat dessert", 550, 7,
     40, 38, 5),
    ("chocolat au lait", 540, 7, 57, 31, 5),
    ("chocolat blanc", 550, 6, 58, 33, 5),
    ("cacao|cacao en poudre|cacao non sucre|poudre de cacao", 290, 20, 20, 14, None, 0.45),
    ("confiture", 250, 0.5, 60, 0.2, None, 1.3),
    ("nutella|pate a tartiner", 540, 6, 57, 31, None, 1.2),
    ("caramel|sauce caramel", 400, 2, 70, 13, None, 1.3),
    ("levure|levure chimique|poudre a lever|levure boulangere", 150, 0, 37, 0, 11),
    ("gelatine|feuilles de gelatine|feuille de gelatine", 340, 85, 0, 0, 2),
    # Oléagineux, graines, fruits secs
    ("amandes|amande|poudre d'amande|poudre d'amandes|amandes effilees|amande en poudre",
     600, 25, 7, 52, 1.2, 0.45),
    ("noisettes|noisette|poudre de noisette|poudre de noisettes", 640, 15, 7, 61, 1, 0.45),
    ("noix|cerneaux de noix|noix de grenoble", 700, 15, 7, 65, 5),
    ("noix de cajou|cajou", 590, 18, 27, 46, 1.5),
    ("noix de coco|coco rapee|noix de coco rapee", 650, 6.5, 7, 62, None, 0.35),
    ("pistaches|pistache", 600, 21, 17, 49, 1),
    ("noix de pecan|pecan", 700, 9, 4, 72, 4),
    ("cacahuetes|cacahuete|arachides", 600, 26, 12, 49, 1),
    ("beurre de cacahuete|beurre de cacahuetes|beurre d'arachide|peanut butter", 620, 25, 14,
     50, None, 1.05),
    ("puree d'amande|puree d'amandes|beurre d'amande", 620, 21, 8, 54, None, 1.05),
    ("tahini|tahin|puree de sesame|creme de sesame", 640, 18, 9, 58, None, 1.05),
    ("graines de chia|chia", 440, 17, 8, 31, None, 0.65),
    ("graines de sesame|sesame", 600, 18, 10, 50, None, 0.6),
    ("graines de courge", 570, 30, 7, 46, None, 0.55),
    ("graines de lin|lin", 510, 18, 2, 42, None, 0.6),
    ("raisins secs|raisins sec", 300, 3, 70, 0.5, None, 0.65),
    ("dattes|datte|dattes medjool", 300, 2.5, 67, 0.3, 10),
    ("abricots secs|abricot sec", 260, 3, 60, 0.5, 8),
    # Matières grasses, sauces, condiments
    ("huile|huile d'olive|huile de tournesol|huile de colza|huile neutre|huile de coco|"
     "huile de sesame|huile vegetale|huile de friture", 900, 0, 0, 100, None, 0.92),
    ("mayonnaise|mayo", 700, 1.5, 1.5, 76, None, 0.95),
    ("ketchup", 110, 1.2, 25, 0.2, None, 1.1),
    ("moutarde|moutarde a l'ancienne", 150, 7, 5, 11, None, 1.05),
    ("sauce soja|soja sale|sauce soja salee|tamari", 60, 8, 6, 0.5, None, 1.15),
    ("sauce soja sucree", 250, 5, 55, 0.5, None, 1.25),
    ("vinaigre|vinaigre de vin|vinaigre de cidre|vinaigre de riz", 20, 0, 1, 0),
    ("vinaigre balsamique|balsamique|creme de balsamique", 120, 0.5, 25, 0, None, 1.2),
    ("pesto", 450, 5, 5, 45, None, 1.0),
    ("sauce tomate|coulis de tomate|coulis de tomates|passata|tomates concassees|"
     "pulpe de tomate|pulpe de tomates|tomates pelees|puree de tomate|puree de tomates", 35,
     1.3, 5, 0.5),
    ("concentre de tomate|concentre de tomates|double concentre", 85, 4, 14, 0.5, None, 1.1),
    ("sauce barbecue|sauce bbq", 170, 1, 40, 0.5, None, 1.2),
    ("sauce sriracha|sriracha", 100, 2, 20, 1),
    ("bouillon|cube de bouillon|bouillon cube|fond de volaille|fond de veau|bouillon de "
     "volaille|bouillon de legumes", 8, 0.5, 0.5, 0.4, 10),
    ("vin|vin blanc|vin rouge", 70, 0.1, 1, 0),
    ("biere", 40, 0.4, 3, 0),
    ("rhum|cognac|calvados|amaretto|liqueur", 230, 0, 5, 0, None, 0.95),
    # Légumes (crus)
    ("oignon|oignons|oignon rouge|oignons rouges|oignon jaune|oignon blanc", 40, 1.2, 7.5, 0.2,
     100),
    ("oignon nouveau|oignons nouveaux|oignons verts|cebette", 30, 1.5, 5, 0.2, 20),
    ("echalote|echalotes", 70, 2.5, 14, 0.1, 30),
    ("ail|gousse d'ail|gousses d'ail|ail en poudre", 130, 6, 25, 0.5, 5),
    ("tomate|tomates|tomates fraiches", 18, 0.9, 3, 0.2, 120),
    ("tomates cerises|tomate cerise|tomates cerise", 25, 1, 4, 0.3, 12),
    ("tomates sechees|tomate sechee", 210, 5, 25, 10, 5),
    ("carotte|carottes", 37, 0.8, 7, 0.3, 90),
    ("courgette|courgettes", 17, 1.2, 2, 0.4, 250),
    ("aubergine|aubergines", 22, 1, 3.5, 0.2, 300),
    ("poivron|poivrons|poivron rouge|poivron vert|poivron jaune", 28, 1, 5, 0.3, 160),
    ("concombre|concombres", 13, 0.6, 2, 0.1, 300),
    ("champignons|champignon|champignons de paris|champignon de paris|shiitake|pleurotes", 22,
     2.7, 1, 0.3, 20),
    ("epinards|pousses d'epinards|epinard", 25, 2.8, 1.5, 0.5),
    ("brocoli|brocolis", 34, 3, 3.5, 0.4, 400),
    ("chou-fleur|chou fleur", 25, 2, 3, 0.3, 600),
    ("chou|chou blanc|chou rouge|chou vert|chou chinois", 25, 1.3, 4, 0.2, 800),
    ("poireau|poireaux", 30, 1.5, 4.5, 0.3, 150),
    ("salade|laitue|roquette|mache|mesclun|jeunes pousses|batavia|iceberg", 15, 1.4, 1.5, 0.3,
     300),
    ("avocat|avocats", 205, 1.8, 2, 20, 150),
    ("petits pois", 70, 5, 10, 0.5),
    ("haricots verts", 30, 1.9, 4, 0.2),
    ("grains de mais|mais en boite|mais doux", 100, 3, 18, 1.5),
    ("butternut|courge|potiron|potimarron|citrouille", 35, 1, 7, 0.1, 1000),
    ("celeri|celeri branche|branche de celeri", 15, 0.7, 2.5, 0.2, 40),
    ("radis", 15, 0.8, 2.5, 0.1, 10),
    ("betterave|betteraves", 45, 1.6, 8, 0.1, 150),
    ("olives|olive|olives noires|olives vertes", 150, 1, 1, 15, 4),
    ("cornichons|cornichon", 15, 0.5, 2, 0.2, 10),
    ("fenouil", 20, 1.2, 3, 0.2, 250),
    ("asperges|asperge", 20, 2.2, 2, 0.1, 20),
    ("gingembre", 80, 1.8, 15, 0.8, 10),
    ("capres", 25, 2, 2, 0.9),
    # Fruits
    ("pomme|pommes|pomme golden|pommes golden", 52, 0.3, 12, 0.2, 150),
    ("poire|poires", 55, 0.4, 12, 0.2, 150),
    ("banane|bananes", 90, 1.1, 20, 0.3, 120),
    ("fraises|fraise", 32, 0.7, 6, 0.3, 15),
    ("framboises|framboise", 45, 1.2, 5, 0.6, 4),
    ("myrtilles|myrtille", 57, 0.7, 12, 0.3),
    ("fruits rouges|fruits des bois", 40, 1, 7, 0.4),
    ("citron|citrons|citron vert|citrons verts", 30, 0.9, 3, 0.3, 100),
    ("jus de citron|jus de citron vert", 22, 0.4, 7, 0.2),
    ("jus d'un citron|jus d'un demi citron|jus de 1 citron", 22, 0.4, 7, 0.2, 40),
    ("zeste|zestes|zeste de citron|zeste d'orange", 50, 1.5, 5, 0.3, 2),
    ("orange|oranges", 45, 0.9, 9, 0.2, 180),
    ("jus d'orange", 45, 0.7, 10, 0.2),
    ("mangue|mangues", 65, 0.8, 14, 0.4, 300),
    ("ananas", 52, 0.5, 12, 0.1, 1000),
    ("kiwi|kiwis", 60, 1, 11, 0.6, 75),
    ("peche|peches|nectarine|nectarines", 40, 0.8, 9, 0.2, 150),
    ("abricot|abricots", 48, 1, 10, 0.1, 45),
    ("cerises|cerise", 60, 1, 14, 0.2, 7),
    ("raisin|raisins", 70, 0.7, 16, 0.2),
    ("compote|compote de pommes", 65, 0.3, 15, 0.2, 100),
    ("lait de coco leger", 75, 0.8, 2, 7),
]

# Ne comptent pas (ou presque) : on ne les signale pas comme « oubliés ».
_NEUTRAL = ("sel|fleur de sel|poivre|epices|epice|cumin|paprika|curry|curcuma|cannelle|muscade|"
            "herbes|herbes de provence|persil|basilic|coriandre|ciboulette|thym|laurier|romarin|"
            "menthe|origan|aneth|estragon|sauge|piment|piment d'espelette|vanille|gousse de "
            "vanille|extrait de vanille|arome|eau|eau tiede|eau froide|eau chaude|glacons|"
            "bicarbonate|cardamome|clou de girofle|clous de girofle|badiane|anis|garam masala|"
            "ras el hanout|cinq epices|tabasco|sauce worcestershire|colorant|agar-agar|agar agar|"
            "levure de biere|ail semoule")


_PRETTY = {
    "oeuf": "œuf", "jaune d'oeuf": "jaune d'œuf", "blanc d'oeuf": "blanc d'œuf",
    "creme": "crème", "creme legere": "crème légère", "creme de coco": "crème de coco",
    "pates": "pâtes", "pates fraiches": "pâtes fraîches", "pate feuilletee": "pâte feuilletée",
    "pate brisee": "pâte brisée", "pate sablee": "pâte sablée", "pate a pizza": "pâte à pizza",
    "pate filo": "pâte filo", "fecule": "fécule", "maizena": "maïzena",
    "pomme de terre": "pomme de terre", "patate douce": "patate douce", "boeuf": "bœuf",
    "boeuf hache": "bœuf haché", "entrecote": "entrecôte", "echalote": "échalote",
    "epinards": "épinards", "celeri": "céleri", "chevre": "chèvre", "gruyere": "gruyère",
    "emmental": "emmental / gruyère", "lait ecreme": "lait écrémé",
    "lait concentre sucre": "lait concentré sucré", "sucre vanille": "sucre vanillé",
    "sirop d'erable": "sirop d'érable", "cacahuetes": "cacahuètes",
    "beurre de cacahuete": "beurre de cacahuète", "puree d'amande": "purée d'amande",
    "graines de sesame": "graines de sésame", "concentre de tomate": "concentré de tomate",
    "biere": "bière", "peche": "pêche", "mais": "maïs", "grains de mais": "maïs",
    "saumon fume": "saumon fumé", "chou-fleur": "chou-fleur", "biscuits": "biscuits",
    "lardons": "lardons", "riz cuit": "riz cuit", "tomates sechees": "tomates séchées",
    "cereales": "céréales", "fromage frais": "fromage frais", "dattes": "dattes",
}


def fold(text):
    text = (text or "").lower().replace("œ", "oe").replace("æ", "ae").replace("’", "'")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def _build():
    index = {}
    for row in _TABLE:
        names, kcal, prot, gluc, lip = row[:5]
        piece = row[5] if len(row) > 5 else None
        density = row[6] if len(row) > 6 else 1.0
        first = names.split("|")[0]
        food = Food(_PRETTY.get(first, first), kcal, prot, gluc, lip, piece, density)
        for n in names.split("|"):
            index[fold(n)] = food
    neutral = Food("épices / sel / eau", 0, 0, 0, 0, 1, 1.0, neutral=True)
    for n in _NEUTRAL.split("|"):
        index.setdefault(fold(n), neutral)
    keys = sorted(index, key=len, reverse=True)
    pattern = re.compile(r"(?<![a-z])(" + "|".join(re.escape(k) for k in keys) + r")(?![a-z])")
    return index, pattern


_INDEX, _FOOD_RE = _build()

_WORD_NUMBERS = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6,
                 "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "douze": 12, "demi": 0.5,
                 "demie": 0.5, "quelques": 3}
_FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
_NUM = (r"(?:\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?|[½¼¾⅓⅔⅛]|(?:une|un|deux|trois|quatre|cinq|six|"
        r"sept|huit|neuf|dix|douze|demie?|quelques)(?![a-zà-ÿ]))")
_QTY_RE = re.compile(r"(?<![\w])(" + _NUM + r")(?:\s*(?:-|à|a|ou)\s*(" + _NUM + r"))?\s*", re.I)

# unité -> (genre, valeur) ; genre : « g » (grammes), « ml », ou « piece » (poids de l'aliment)
_UNITS = [
    (r"kg|kilos?", "g", 1000), (r"mg", "g", 0.001), (r"g|gr|grammes?", "g", 1),
    (r"cl", "ml", 10), (r"dl", "ml", 100), (r"ml", "ml", 1), (r"l|litres?", "ml", 1000),
    # les cuillères à café avant les cuillères à soupe, puis « cuillère » tout court
    (r"cuill?(?:e|è)res?\s+(?:a|à)\s+caf(?:e|é)|cuil\.?\s+(?:a|à)\s+caf(?:e|é)|"
     r"c\.?\s+(?:a|à)\s+caf(?:e|é)|c\.?\s?(?:a|à)\s?c\.?|càc|cac|cc|tsp", "ml", 5),
    (r"cuill?(?:e|è)res?\s+(?:a|à)\s+soupe|cuil\.?\s+(?:a|à)\s+soupe|c\.?\s+(?:a|à)\s+soupe|"
     r"c\.?\s?(?:a|à)\s?s\.?|càs|cas|cs|tbsp", "ml", 15),
    (r"cuill?(?:e|è)res?|cuil\.?", "ml", 15),
    (r"tasses?|cups?|mugs?", "ml", 240), (r"verres?", "ml", 200), (r"bols?", "ml", 350),
    (r"pinc(?:e|é)es?", "g", 0.5), (r"traits?", "ml", 5), (r"poign(?:e|é)es?", "g", 30),
    (r"bottes?|bouquets?", "g", 100), (r"sachets?", "sachet", 10), (r"pots?", "ml", 125),
    (r"bo(?:i|î)tes?|conserves?", "g", 400), (r"paquets?", "g", 250),
    (r"tranches?", "tranche", 30), (r"gousses?", "g", 5), (r"feuilles?", "piece", 2),
    (r"brins?|branches?", "g", 2), (r"morceaux?", "g", 20), (r"carr(?:e|é)s?", "g", 5),
    (r"rouleaux?", "g", 230), (r"pav(?:e|é)s?", "g", 125), (r"filets?", "filet", 0),
    (r"barquettes?", "g", 250), (r"briques?", "ml", 200), (r"tablettes?", "g", 100),
    (r"noix\s+de\s+beurre", "beurre", 10), (r"noisettes?\s+de\s+beurre", "beurre", 5),
]
_UNIT_RE = re.compile(r"(" + "|".join(f"(?:{u})" for u, _, _ in _UNITS) + r")(?![a-zà-ÿ])",
                      re.I)
_EXPLICIT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|gr|grammes?|cl|ml|l|litres?)(?![a-z])",
                          re.I)
_CONTAINERS = re.compile(r"^\s*(\d+)\s*(?:bo(?:i|î)tes?|pots?|sachets?|paquets?|barquettes?|"
                         r"conserves?)", re.I)


def _number(text):
    text = text.strip().lower()
    if text in _FRACTIONS:
        return _FRACTIONS[text]
    if text in _WORD_NUMBERS:
        return _WORD_NUMBERS[text]
    if "/" in text:
        a, b = text.split("/", 1)
        try:
            return float(a.replace(",", ".")) / float(b)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _unit_of(text):
    m = _UNIT_RE.match(text)
    if not m:
        return None, None, 0
    word = m.group(1)
    for pattern, kind, value in _UNITS:
        if re.fullmatch(pattern, word, re.I):
            return kind, value, m.end()
    return None, None, 0


def find_food(line):
    """Aliment reconnu dans une ligne, en préférant le nom le plus long (« lait de coco »)."""
    text = fold(line)
    if re.search(r"(?:noix|noisettes?) de beurre", text):
        return _INDEX["beurre"]
    matches = [m.group(1) for m in _FOOD_RE.finditer(text)]
    if not matches:
        return None
    best = max(matches, key=len)
    return _INDEX[best]


def grams_of(line, food):
    """Poids en grammes de l'ingrédient, ou None si on ne peut pas le savoir."""
    text = line.strip()
    explicit = _EXPLICIT_RE.search(text)
    if explicit:
        value = float(explicit.group(1).replace(",", "."))
        unit = explicit.group(2).lower()
        factor = {"kg": 1000, "g": 1, "gr": 1, "cl": 10, "ml": 1, "l": 1000}.get(
            unit, 1000 if unit.startswith("l") else 1)
        grams = value * factor * (food.density if unit in ("cl", "ml", "l") or
                                  unit.startswith("litre") else 1)
        count = _CONTAINERS.match(text)
        if count and explicit.start() > count.end():
            grams *= float(count.group(1))  # « 2 boîtes de pois chiches (400 g) »
        return grams

    m = _QTY_RE.search(text)
    if not m:
        return None
    qty = _number(m.group(1))
    if qty is None:
        return None
    if m.group(2):
        high = _number(m.group(2))
        if high:
            qty = (qty + high) / 2  # « 2 à 3 » -> 2,5
    rest = text[m.end():]
    kind, value, _ = _unit_of(rest)
    if kind == "g":
        return qty * value
    if kind == "ml":
        return qty * value * food.density
    if kind == "beurre":
        return qty * value
    if kind == "sachet":
        return qty * (food.piece if food.piece and food.piece <= 15 else value)
    if kind == "tranche":
        return qty * (food.piece if food.piece and food.piece <= 60 else value)
    if kind == "filet":
        if food.piece is None:  # un filet d'huile, de vinaigre, de miel…
            return qty * 5 * food.density
        return qty * food.piece  # des filets de poisson, de poulet
    if kind == "piece":
        return qty * (food.piece or value)
    if food.piece:
        return qty * food.piece
    return None


def analyse_line(line):
    """-> dict(line, food, grams, kcal, prot, gluc, lip, status) ; status : ok, neutre,
    inconnu (aliment pas reconnu) ou quantite (aliment reconnu, quantité inconnue)."""
    food = find_food(line)
    out = {"line": line, "food": food.name if food else None, "grams": None,
           "kcal": 0.0, "prot": 0.0, "gluc": 0.0, "lip": 0.0}
    if food is None:
        out["status"] = "inconnu"
        return out
    if food.neutral:
        out["status"] = "neutre"
        return out
    grams = grams_of(line, food)
    if grams is None:
        out["status"] = "quantite"
        return out
    out["grams"] = grams
    for key in ("kcal", "prot", "gluc", "lip"):
        out[key] = getattr(food, key) * grams / 100
    out["status"] = "ok"
    return out


def portions_of(servings):
    """« 4 personnes » -> 4 ; « 4 à 6 » -> 5 ; rien -> None."""
    m = re.search(r"(\d+)(?:\s*(?:-|à|a)\s*(\d+))?", servings or "")
    if not m:
        return None
    low = int(m.group(1))
    high = int(m.group(2)) if m.group(2) else low
    n = (low + high) / 2
    return n if n > 0 else None


def compute(recipe):
    """Macros d'une recette : totaux, par portion, détail par ingrédient, oublis."""
    lines = [analyse_line(item) for g in recipe.get("ingredients", []) for item in
             g.get("items", [])]
    total = {k: sum(l[k] for l in lines) for k in ("kcal", "prot", "gluc", "lip")}
    portions = portions_of(recipe.get("servings"))
    per = {k: v / portions for k, v in total.items()} if portions else None
    counted = sum(1 for l in lines if l["status"] == "ok")
    missing = [l for l in lines if l["status"] in ("inconnu", "quantite")]
    return {"lines": lines, "total": total, "portions": portions, "per_portion": per,
            "counted": counted, "missing": missing}


def summary(values):
    return (f"{values['kcal']:.0f} kcal · Protéines {values['prot']:.0f} g · "
            f"Glucides {values['gluc']:.0f} g · Lipides {values['lip']:.0f} g")
