# 📖 Livre de cuisine

Un logiciel Windows qui va chercher les recettes que tu as **enregistrées sur Instagram**
et les range dans un vrai livre de cuisine sur ton PC :

- une liste de toutes tes recettes, avec **recherche** (« poulet », « creme » trouve
  « crème »), **catégories** (Entrée, Plat, Dessert…) et **favoris** ;
- chaque recette bien présentée : photo, ingrédients, étapes, astuces, lien vers le post ;
- **tes notes** sur chaque recette (« moins de sucre », « à refaire ») ;
- tu peux **corriger** une recette, ou en **ajouter** une à la main ;
- **impression / PDF** d'une recette ou de tout le livre, avec sommaire.

Tout reste sur ton PC, dans le dossier `Mes recettes`. Ça marche même sans internet une fois
les recettes importées.

---

## Installation (une seule fois)

1. Installe **Python** depuis [python.org](https://www.python.org/downloads/) en cochant bien
   **« Add python.exe to PATH »**. Si tu as déjà RangeMusique, c'est déjà fait.
2. Télécharge ce dossier `LivreCuisine` sur ton PC. Sur GitHub : bouton **Code →
   Download ZIP**, puis décompresse le fichier.
3. Double-clique sur **`Lancer Livre de cuisine.bat`**. La première fois, il installe les
   composants nécessaires (Instaloader, Pillow, Anthropic), ce qui demande une connexion
   internet.

---

## Importer tes recettes

Onglet **⬇ Importer depuis Instagram** :

### 1. Se connecter
Le plus fiable : **Copier la connexion du navigateur…**. Instagram refuse souvent la connexion
par mot de passe depuis un logiciel comme celui-ci, et il bloque aussi un simple cookie qui
arrive sans le reste de la connexion : il croit alors à un appareil inconnu, sans rien
t'envoyer sur ton téléphone.
1. Dans Chrome ou Edge, ouvre instagram.com et vérifie que tu es connecté.
2. Appuie sur **F12**, puis va dans l'onglet **Réseau** (ou **Network**).
3. Appuie sur **F5** pour recharger la page.
4. Tout en haut de la liste, fais un clic droit sur la ligne **www.instagram.com**, puis
   **Copier → Copier en tant que cURL (bash)**. Le choix « (cmd) » marche aussi.
5. Dans le logiciel, clique sur **Copier la connexion du navigateur…**, colle tout (Ctrl+V)
   et clique sur **Se connecter**.

Ça copie tous les cookies et l'identité de ton navigateur : Instagram reconnaît la connexion
comme la tienne. Ce texte permet d'accéder à ton compte : ne le colle nulle part ailleurs.
Si tu te déconnectes d'Instagram dans le navigateur, il ne marche plus : recommence alors
ces étapes.

Autres possibilités :
- **Firefox** : connecte-toi à instagram.com dans Firefox, puis clique sur **Utiliser ma
  connexion Firefox** ;
- **mot de passe** : entre ton identifiant et ton mot de passe, puis clique sur **Se
  connecter**. Si tu as la vérification en deux étapes, l'appli te demande le code. Si
  Instagram demande de vérifier que c'est toi, confirme « C'était moi » sur ton téléphone. Ne
  réessaie pas trop de fois de suite.

Le mot de passe **n'est jamais enregistré**. Seule la session est gardée, dans le dossier
`session_instagram`, pour que tu n'aies pas à te reconnecter à chaque fois.

### 2. Choisir ta collection
Le plus simple : **Coller le lien de ma collection…**.
1. Sur instagram.com, ouvre ton profil → **Enregistrements** → ta collection de recettes.
2. Copie l'adresse de la page (Ctrl+L puis Ctrl+C). Elle ressemble à
   `https://www.instagram.com/ton_nom/saved/recettes/17912345678901234/`.
3. Dans le logiciel, clique sur **Coller le lien de ma collection…** et colle-la.

Le bouton **Charger mes collections** donne aussi la liste. Instagram ne fournit plus toujours
le nom des collections : elles s'appellent alors « Collection 1 (nom inconnu) »… Dans ce cas,
colle plutôt le lien.

> Instagram ne permet plus de lire une collection directement. Le logiciel parcourt donc tous
> tes posts enregistrés et garde ceux de ta collection. C'est un peu plus long, et le journal
> affiche où il en est.

### 3. Importer
Clique sur **Importer les nouvelles recettes**. Pour chaque post, l'appli :
- télécharge les photos ;
- lit la légende ;
- pour les vidéos (Reels) : **écoute la vidéo** pour récupérer la recette dite à l'oral
  (voir *Transcription* plus bas) ;
- range la recette : titre, catégorie, ingrédients, étapes, temps, nombre de parts.

Les posts qui ne ressemblent pas à des recettes sont mis de côté, et non supprimés. Tu les
retrouves avec le filtre **« Pas des recettes »** dans l'onglet Mes recettes.

Tu peux cliquer sur **Arrêter** quand tu veux. La prochaine fois, seules les **nouvelles**
recettes sont importées. Relance donc l'import de temps en temps, après avoir enregistré de
nouvelles recettes sur Instagram.

> ⏱ L'appli fait une pause de 4 secondes entre deux posts, pour ne pas se faire bloquer par
> Instagram. Compte environ **10 minutes pour 100 recettes** sans transcription, et plus
> avec (la transcription d'une vidéo prend de 10 secondes à une minute selon ton PC).

**Importer des liens…** : tu peux aussi coller des liens de posts (Partager → Copier le
lien), par exemple une recette qu'on t'a envoyée.

---

## Les deux options pour les vidéos et les recettes mal écrites

Onglet **⚙ Réglages**.

### 🎤 Transcription des vidéos (gratuite)
Clique sur **Installer la transcription**, une seule fois (environ 300 Mo). Ensuite, l'appli
écoute chaque vidéo **sur ton PC**, sans internet ni frais, et garde ce qui est dit. Le texte
apparaît dans la recette, sous « Ce qui est dit dans la vidéo ».

Précision : `base` (rapide), `small` (conseillé), `medium` (plus précis, mais lent).

### ✨ Mise en forme par Claude (facultative, payante)
Sans cette option, l'appli découpe la légende toute seule. Ça marche bien quand la recette
est écrite proprement sous le post (« Ingrédients : … Préparation : … »). En revanche, quand
la recette est **seulement dite dans la vidéo** ou **écrite à l'écran / sur les photos**, il
faut cette option pour qu'elle soit rangée en ingrédients et en étapes.

Avec une **clé API Anthropic**, Claude lit la légende, la transcription, les photos du post et
quelques images de la vidéo. Il écrit ensuite la recette proprement, en français, et traduit
si le post est en anglais.

1. Crée un compte sur [console.anthropic.com](https://console.anthropic.com), ajoute un peu
   de crédit (5 $ suffisent pour commencer), puis crée une clé (bouton **Créer une clé…**).
2. Colle-la dans Réglages, clique sur **Tester la clé**, puis sur **Enregistrer les
   réglages**.

Coût : **quelques centimes par recette**, un peu plus pour une vidéo, car il y a plus
d'images à lire.

Pour une recette déjà importée sans Claude, ouvre-la et clique sur **✨ Mise en forme
Claude**.

---

## Utiliser le livre

Onglet **📖 Mes recettes** :

| Je veux… | Je fais… |
|---|---|
| Trouver une recette | Je tape un mot dans 🔍 (titre, ingrédient, mot-clé, @compte) |
| Voir seulement les desserts | Je choisis la catégorie dans la liste |
| Garder mes préférées | **☆ Favori**, puis la case « Seulement mes favoris » |
| Corriger une recette | **✏ Modifier**, ou double-clic dans la liste |
| Ajouter une recette de mamie | **+ Nouvelle recette** |
| Noter mes modifications | Le cadre **Mes notes**, puis **Enregistrer** |
| Revoir la vidéo | **Instagram** ouvre le post dans le navigateur |
| Imprimer ou faire un PDF | **🖨 Imprimer** (une recette) ou **Exporter la liste** (toutes les recettes affichées). La page s'ouvre dans le navigateur : Ctrl+P → « Enregistrer au format PDF » |
| Voir les autres photos du post | ◀ ▶ au-dessus de la recette |

Dans le formulaire **Modifier** : un ingrédient par ligne, et une ligne qui finit par « : »
démarre un groupe (« Pour la sauce : »). Une étape par ligne.

---

## Fichiers
- `Mes recettes\recettes.json` : toutes tes recettes, avec une copie de secours
  `recettes.json.bak`. Tu peux choisir un autre dossier dans Réglages, par exemple un dossier
  OneDrive pour le sauvegarder ;
- `Mes recettes\photos\` : les photos ;
- `Mes recettes\Exports\` : les pages à imprimer ;
- `config.json` : tes réglages, dont la clé Claude ;
- `session_instagram\` : ta session Instagram. Supprime ce dossier, ou clique sur
  **Se déconnecter**, pour l'effacer ;
- `modeles_whisper\` : le modèle de transcription ;
- `LivreCuisine.log` : le détail des erreurs éventuelles.

## Bon à savoir
- L'appli passe par **Instaloader**, un outil non officiel. Instagram peut changer son
  fonctionnement du jour au lendemain. Si l'import ne marche plus, mets à jour les
  composants avec `py -m pip install --user -U instaloader`.
- Les recettes et photos sont copiées sur ton PC : elles restent même si le post disparaît
  d'Instagram.
- Supprimer une recette du livre ne la retire pas de ta collection Instagram : elle
  reviendra au prochain import. Pour qu'elle ne revienne pas, retire-la de ta collection,
  ou garde-la et décoche « C'est une recette ».

## Pour les curieux
- Code : dossier `livrecuisine\`. Tests : `python -m pytest tests` (il faut pytest ; `av` et
  `numpy` pour les tests vidéo).
