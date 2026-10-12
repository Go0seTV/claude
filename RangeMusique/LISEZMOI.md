# 🎵 RangeMusique

Une application Windows pour :

1. **Taguer correctement** ta musique (artiste, titre, album, n° de piste, année, pochette),
   même quand un fichier s'appelle n'importe comment (`track07.mp3`). Le morceau est
   reconnu **à l'écoute**, grâce à son empreinte audio.
2. **Ranger** toute ta bibliothèque dans un nouveau dossier propre :

```
Musique rangée\
├── Berlin\
│   └── Top Gun - Original Motion Picture Soundtrack\
│       ├── 03 - Take My Breath Away.flac
│       └── cover.jpg
├── David Guetta\
│   └── Nothing but the Beat\
│       └── 02 - Titanium.m4a          (tag artiste : « David Guetta feat. Sia »)
├── _Doublons\                          (les moins bonnes copies, à vider toi-même)
├── _À vérifier\                        (morceaux non reconnus + _suggestions.csv)
└── _Journal\                           (pour pouvoir tout annuler)
```

Formats gérés : MP3, FLAC, M4A/AAC/ALAC, OGG, Opus, WMA, WAV, AIFF, APE, WavPack, MPC.

---

## Installation (une seule fois)

1. Télécharge ce dossier `RangeMusique` sur ton PC. Sur GitHub : bouton **Code →
   Download ZIP**, puis décompresse le fichier.
2. Mets **`fpcalc.exe`** dans le dossier `RangeMusique`, à côté de `app.pyw`. Il sera
   trouvé tout seul. Tu peux aussi le laisser où il est et indiquer son emplacement dans
   l'onglet **Réglages**.
3. Double-clique sur **`Lancer RangeMusique.bat`**. La première fois, il installe le
   composant `mutagen`, ce qui demande une connexion internet.
4. Dans l'onglet **Réglages** :
   - colle ta **clé d'application AcoustID**, puis clique sur **Tester la clé** ;
   - vérifie **fpcalc** avec **Tester fpcalc** ;
   - clique sur **Enregistrer les réglages**.

---

## Utilisation

### Étape 1 : Analyser et taguer
1. Choisis le **dossier de ta musique** et clique sur **Analyser**.
2. Pour chaque morceau, l'appli :
   - lit les tags existants, le nom du fichier et le nom des dossiers ;
   - **écoute le morceau** (empreinte AcoustID) pour savoir ce que c'est ;
   - à défaut, cherche sur MusicBrainz avec le titre et l'artiste connus ;
   - choisit le bon album. Elle préfère l'album d'origine ou la **BO** à une compilation
     comme « Now 80s », garde l'album indiqué dans les tags ou dans le nom du dossier,
     et regroupe les morceaux d'un même album rippé.
3. Les couleurs du tableau :
   - 🟩 **Reconnu** : sûr ;
   - 🟦 **Tags / nom fichier** : pas trouvé en ligne, mais l'artiste et le titre sont connus
     grâce aux tags du fichier et à son nom ;
   - 🟧 **À vérifier** / 🟥 **Inconnu** : double-clique pour corriger. Tu peux **▶ écouter**
     le morceau et choisir une suggestion.
4. Bouton facultatif : **Écrire les tags dans les fichiers (sans les déplacer)**, si tu veux
   seulement corriger les tags.

> ⏱ MusicBrainz limite les requêtes à une par seconde. Compte environ **1 à 2 heures pour
> 5 000 morceaux** la première fois. Tu peux cliquer sur **Arrêter** quand tu veux : tout
> est gardé en mémoire (`cache_musique.sqlite`), et la prochaine analyse reprend presque
> instantanément là où tu t'étais arrêté.
> L'option **Analyse rapide** saute la vérification en ligne pour les fichiers qui ont déjà
> un artiste, un titre et un album.

### Étape 2 : Ranger
1. Choisis un **nouveau dossier de destination**, par exemple `D:\Musique rangée`.
2. Clique sur **Préparer l'aperçu** : tu vois ligne par ligne l'emplacement actuel et le
   nouvel emplacement de chaque fichier. Rien n'est encore déplacé.
3. Clique sur **Lancer le rangement**. L'appli :
   - déplace chaque morceau dans `Artiste\Album\01 - Titre.ext` ;
   - écrit les tags corrigés et la pochette, avec un `cover.jpg` dans chaque album ;
   - **doublons** : garde la meilleure qualité (sans perte > meilleur débit) et met les
     autres copies dans `_Doublons` ;
   - **non reconnus** : les met dans `_À vérifier`, avec un fichier `_suggestions.csv` qui
     s'ouvre dans Excel ;
   - **supprime les anciens dossiers devenus vides**, y compris les dossiers
     intermédiaires comme `Top Gun\Berlin\`. Les fichiers inutiles (`Thumbs.db`,
     `desktop.ini`, `.m3u`, `.nfo`…) sont supprimés avec eux. Un dossier qui contient
     encore autre chose (photo, PDF…) est laissé en place.
4. Si quelque chose ne te plaît pas, clique sur **Annuler le dernier rangement** : chaque
   fichier retourne à sa place, avec ses anciens tags.

### Ensuite
- Écoute ce qu'il y a dans `_Doublons`, puis supprime-le quand tu es sûr.
- Pour les morceaux de `_À vérifier` : choisis ce dossier `_À vérifier` comme **dossier de
  ta musique**, analyse-le, corrige les morceaux d'un double-clic, puis range-les en gardant
  `Musique rangée` comme destination.
- Tu peux aussi **réanalyser tout le dossier rangé** pour compléter les tags. Choisis
  `Musique rangée` à la fois comme dossier de ta musique et comme destination. Les fichiers
  déjà bien placés ne bougent pas, et le dossier `_Doublons` est ignoré.

---

## Règles de rangement

| Cas | Résultat |
|---|---|
| Morceau d'une BO (Top Gun) | `Berlin\Top Gun - …\03 - Take My Breath Away` |
| « David Guetta feat. Sia » | dossier `David Guetta`, tag artiste complet conservé |
| Même chanson présente sur une compilation et sur l'album original | l'album original |
| Album sur plusieurs CD | `1-01 - Titre`, `2-01 - Titre`… dans un seul dossier |
| « BERLIN » et « Berlin » | un seul dossier |
| Morceau inconnu en ligne (sketch, rareté) avec tags incomplets | complété avec le nom du fichier : `François Pérusse - Horscope.mp3` → artiste + titre |
| Pas d'album connu | `Artiste\Divers\Titre` |
| Version live / remix (durée différente) | pas considérée comme un doublon |
| Caractères interdits par Windows (`AC/DC`, `:`) | remplacés (`AC-DC`) |

Le tag « artiste de l'album » reçoit l'artiste principal. Ainsi, ton lecteur (Windows Media
Player, foobar, MusicBee…) range ta musique exactement comme tes dossiers.

---

## Fichiers créés à côté de l'application
- `config.json` : tes réglages ;
- `cache_musique.sqlite` et `cache_pochettes\` : la mémoire des recherches (tu peux les
  supprimer sans risque) ;
- `RangeMusique.log` : le détail des erreurs éventuelles.

## Pour les curieux
- Code : dossier `rangemusique\`. Tests : `python -m pytest tests` (il faut ffmpeg et
  pytest).
- Sources des données : [AcoustID](https://acoustid.org), [MusicBrainz](https://musicbrainz.org),
  [Cover Art Archive](https://coverartarchive.org).
