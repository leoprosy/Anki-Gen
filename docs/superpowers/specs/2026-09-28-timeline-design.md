# Ankigen — Frises chronologiques

Date : 2026-09-28
Branche : `feat/timeline-spec`, depuis `origin/main` (`b9ad8c5`, contrat de runtime fusionné)
Contrat : [prompt de la fonctionnalité](../prompts/2026-09-28-timeline-feature.md)
Plan : [plan d'implémentation](../plans/2026-09-28-timeline.md)

## Objet

Le prompt de la fonctionnalité est le contrat : parcours, format JSON `ankigen.timeline/1`,
dates, moteur de mise en page, rendus, exports, cartes, stockage, routes, interface, tests et
phases. Ce document ne le recopie pas. Il consigne :

1. les résultats des spikes de la phase 0, mesurés sur cette machine ;
2. la réponse à chaque **Décision** du prompt, et les amendements que les spikes imposent ;
3. les points où le prompt contredisait une convention du dépôt, avec la résolution retenue.

Ce qui n'est pas mentionné ici s'applique tel quel.

## Contexte mesuré

- **Environnement.** Python 3.13.14, Pillow 12.2.0 (FreeType 2.14.3, WebP présent, **raqm
  absent**), Node 24.13. WebView2 153.0.4234.48 (Edg/153), écran à `devicePixelRatio` 1,5.
- **Suite de départ.** 199 tests `unittest` et 5 tests `node --test`, tous verts.
- **Projet de référence.** `CH1_ La dynamique de la mondialisation économique` : 33 chunks,
  65 562 caractères de texte de prompt, 3 tableaux, 186 mentions d'années (113 années
  distinctes, de 1492 à 2023). Ses deux chapitres de niveau 3 font 30 489 et 35 024 caractères.
  Le plus long chunk fait 11 879 caractères, la médiane 1 254. Le deck racine est le préfixe
  historique `*ESH*`.

## Résultats des spikes

| # | Question | Méthode | Résultat |
|---|---|---|---|
| S1 | Pillow + Inter dans le venv | `ImageFont.truetype` sur les TTF statiques Inter 4.1, texte accentué, ancres `ls`/`ms`/`rs`, suréchantillonnage ×3 puis `LANCZOS`, `save` en PNG, JPEG, WebP (avec et sans perte) et PDF | Tout passe. PDF `%PDF-1.4` à 300 dpi, titre et auteur en métadonnées. |
| S2 | Même chose dans l'exe gelé | `pyinstaller --noconfirm flask-server.spec` depuis `b9ad8c5` (runtime 1), puis `dist\flask-server.exe --self-check --app-dir <payload>` avec une sonde `timeline_raster` ajoutée à `runtime_probe.py` | `status: ok`, les quatre sondes passent. Le venv donne le même résultat. |
| S3 | Coût et exactitude de la mesure | 300 chaînes aléatoires de 3 à 80 caractères. `getlength` comparé à une table d'avances par caractère mesurée à 1000 px | `getlength` coûte **0,28 ms** par appel (1200 appels : 334 ms). La table donne **exactement** la même largeur (écart 0,0 px) en **3,3 µs** par appel, soit ×84. |
| S4 | Crénage et ligatures dans Pillow | `getlength("AV")` comparé à `getlength("A") + getlength("V")`, de même pour `To` et `fi` | Égalité stricte : le moteur basique n'applique **ni crénage ni ligatures** (Inter crène par GPOS, que seul raqm lit). |
| S5 | Dérive du hinting dans le raster | Largeur de la chaîne dessinée à la taille de rendu, comparée à la largeur linéaire | Jusqu'à **+7,9 px** à 13 px, +3,1 px au suréchantillonnage ×2 et +1,2 px à ×3. Le texte dessiné d'un bloc déborde donc de la boîte mesurée. |
| S6 | Coût du dessin glyphe par glyphe | 400 libellés de 30 caractères sur un canevas de 12 000 × 2 400 px | 678 ms glyphe par glyphe aux positions linéaires, contre 620 ms chaîne par chaîne : même ordre de grandeur, et dérive nulle. |
| S7 | Parité SVG WebView2 ↔ Pillow | App installée lancée avec `--remote-debugging-port`, pilotée par CDP. Inter chargée par `FontFace` avec les mêmes octets. `getComputedTextLength()` sur 60 chaînes (11, 13 et 20 px ; 400 et 600) | Avec `font-kerning: none` et `font-variant-ligatures: none`, écart de **−0,06 à +0,09 px** (0,03 % au plus) par rapport à la table Pillow. Avec les réglages par défaut du navigateur, le SVG n'est jamais plus large que la table de plus de 0,014 px. |
| S8 | `ClipboardItem` dans WebView2 | `navigator.clipboard.write([new ClipboardItem({"image/png": blob})])` avec geste utilisateur, puis relecture par `System.Windows.Forms.Clipboard` | Fonctionne. `isSecureContext` est vrai sur `http://127.0.0.1`, `ClipboardItem.supports("image/png")` aussi, et Windows relit bien une image de 123 × 45. |
| S9 | `window.print()` dans WebView2 | Appel avec geste utilisateur, capture de la fenêtre Tauri par `PrintWindow` | La boîte d'impression de WebView2 s'ouvre dans la fenêtre, avec l'aperçu du SVG vectoriel. Mais l'imprimante par défaut était « Microsoft Print to PDF », en portrait, sur 2 feuilles. Les en-têtes et pieds de page (date, titre, URL, pagination) restent affichés malgré `@page { margin: 0 }`. La taille `@page` personnalisée n'est pas reprise. Le moteur de rendu reste bloqué tant que la boîte est ouverte, ce qui est normal pour une boîte modale. |
| S10 | Le moteur d'impression sait-il sortir du vectoriel ? | `Page.printToPDF` (CDP) sur une vue d'impression avec `@page { size: 400mm 120mm }` | Oui : un PDF de 16,6 Ko, `MediaBox` 1134 × 340 pt (soit 400 × 120 mm), Inter Regular et SemiBold incorporées en sous-ensembles, **0 image**. Cette voie n'est pas accessible à l'app (voir D5). |
| S11 | Coût d'un très grand raster | Canevas RGBA de 24 000 × 4 000 (96 Mpx), texte, réduction `LANCZOS` à 12 000 × 2 000, PNG | 1,7 s, et environ 384 Mo pour le tampon suréchantillonné. |

Effet de bord observé pendant S9, hors périmètre : à la fermeture de l'app, le processus Python du
sidecar PyInstaller *onefile* survit à son lanceur, et garde son port. 31 `flask-server.exe`
orphelins tournaient déjà sur la machine. Signalé à part, sans lien avec la frise.

## Réponses aux décisions du prompt

### D1 — §6.4, seuil du mode « paragraphe par paragraphe » : confirmé

Le seuil reste à **25 000 caractères**. Sur CH1, « Tout le cours » (65 k) et chacun des deux
chapitres (30 k et 35 k) basculent donc par défaut en paragraphe par paragraphe, tandis qu'un
chunk seul (au plus 11,9 k) reste en prompt unique. C'est bien le comportement voulu : une frise de
chapitre de CH1 porte sur une cinquantaine de dates, et le modèle survole à cette échelle.

### D2 — Mesure du texte : une table d'avances par graisse (amende §7)

`measure(text, size, weight)` vaut `size × Σ avance₁₀₀₀[weight][caractère] / 1000`. Les avances
de chaque caractère sont mesurées une fois par `getlength` à 1000 px, puis mises en cache. Cette
règle est exacte pour le moteur basique (S3, S4), 84 fois plus rapide (S3), et rend le budget de
300 ms pour 400 évènements réaliste : un placement teste plusieurs dizaines de candidats par
étiquette, avec des retours à la ligne.

- Le moteur est **forcé** à `ImageFont.Layout.BASIC`. Sinon, une installation de Pillow avec raqm
  (Linux, macOS) changerait les mesures sans le dire.
- Les caractères absents de la table `cmap` d'Inter (CJK, emoji) sont mesurés à **1 em**, la borne
  haute, et déclenchent l'avertissement `label_unsupported_chars`. La table `cmap` est lue à la
  bibliothèque standard (`struct`, formats 4 et 12), faute de `fontTools`. Le raster dessine le
  glyphe `.notdef` à cet endroit. Le chevauchement reste donc impossible, même si le rendu est
  dégradé.
- Les espaces internes des libellés sont compressés à la normalisation : le SVG les compresse de
  toute façon, et la mesure doit porter sur le texte réellement affiché.
- Le tout vit dans un petit module `timeline_fonts.py` (chargement des polices, tables d'avances,
  couverture `cmap`), que partagent le mesureur de production et le moteur raster. C'est un module
  de plus que la liste du §14 : il évite que `timeline_render_raster` et la mesure chargent
  chacun leur police de leur côté.

### D3 — SVG : sans crénage ni ligatures (amende §8.1)

Le `<style>` du SVG fixe `font-kerning: none; font-variant-ligatures: none;
text-rendering: geometricPrecision` sur tout son texte. Le navigateur dessine alors à la largeur
exacte de la table (S7). Avec le crénage, le texte serait un peu plus étroit : sans risque de
chevauchement, mais l'aperçu ne serait plus l'export au pixel près (principe 5).

Le nom de famille est **propre à l'app** : `font-family="'Ankigen Inter', Inter, 'Segoe UI',
sans-serif"`. `base.html` charge déjà une autre version d'Inter depuis Google Fonts. Déclarer une
seconde `@font-face` nommée `Inter` laisserait le navigateur choisir entre les deux, et un
changement de version chez Google décalerait les mesures en silence. La page frise déclare
`'Ankigen Inter'` depuis `static/fonts/`, et l'export avec « Incorporer la police » déclare la même
famille en base64. Sans incorporation, Inkscape retombe sur l'Inter installé. On n'incorpore que les
graisses réellement utilisées, environ 550 Ko de base64 chacune.

### D4 — Raster : glyphe par glyphe, aux positions de la mise en page (amende §8.2)

Le moteur raster dessine chaque glyphe à `x + échelle × avance_cumulée`, avec les mêmes avances
que la mesure, au lieu de confier la chaîne entière à `ImageDraw.text`. Cela supprime la dérive du
hinting (S5), et le coût est le même (S6). Le raster colle alors à la display list à 1 px
suréchantillonné près, quelle que soit l'échelle d'export.

### D5 — PDF vectoriel par `window.print()` : validé techniquement, reporté en phase 8 (confirme §9, §17)

S9 montre que la boîte s'ouvre et que le rendu est vectoriel (S10). En revanche, le résultat dépend
de ce que l'utilisateur règle dans la boîte : imprimante, orientation, en-têtes et pieds de page. La
taille de page personnalisée n'est pas reprise. On ne peut donc pas l'annoncer comme un « PDF
vectoriel » fiable. Le PDF de la v1 reste le PDF raster de Pillow à 300 dpi.

En phase 8, deux voies sont possibles :

- **« Imprimer… »**, par une vue d'impression en A4 ou A3 paysage (pas en taille libre), avec
  `document.title` réglé sur le titre de la frise, sous ce nom modeste. Aucun installateur n'est
  nécessaire.
- **Un vrai PDF vectoriel**, par l'API native `ICoreWebView2.PrintToPdf` exposée par une commande
  Tauri. C'est le moteur de S10, sans boîte de dialogue et avec la taille exacte. Mais cela touche
  au shell Rust : il faut un nouvel installateur, et le cas « shell trop ancien » est à gérer côté
  interface.

### D6 — Presse-papiers : confirmé en phase 5

S8 le valide dans WebView2. Le bouton reste protégé par une détection de fonction, parce que le
développement se fait aussi dans un navigateur classique.

## Écarts avec les conventions du dépôt, et résolutions

### E1 — Emplacement des prompts versionnés

Le prompt propose `prompt_templates/timeline_extract.<lang>.md`. Le plan d'agent local (§4.2)
range déjà ses prompts dans `prompt_templates/<lang>/` (`system.md`, `examples.json`). Pour que les
deux fonctionnalités partagent une seule convention, la frise utilise
`prompt_templates/<lang>/timeline_extract.md`. L'ajout de `prompt_templates` à `DATA_DIRS` ne
change pas.

### E2 — Chaînes de l'interface côté JS

`window.T()` ne voit que les clés `js.*` (`catalog_for_js(lang, prefix="js.")`, injecté par
`base.html`). Pour garder l'espace de noms `timeline.*` demandé, `catalog_for_js` accepte un tuple
de préfixes, et seule la page frise (ainsi que les modales de `work.html` et `upload.html` qui en
ont besoin) injecte en plus `timeline.`. Les autres pages ne transportent pas ce catalogue.

Deux langues cohabitent, et on ne les mélange pas :

- le **rapport de validation** stocke des codes et des paramètres. Ses messages sont rendus à
  l'affichage dans la langue de l'**interface** ;
- le **prompt de correction** et le **formatage des dates** suivent la langue du **document**
  (`translate(key, doc_lang)`).

### E3 — Test WebP

Le §16.1 prévoit un test WebP avec `skipUnless`. Or le §8.2 et le contrat de runtime garantissent
l'encodeur WebP, et la sonde le vérifie. Un test sauté masquerait une régression. Le test WebP est
donc **inconditionnel**.

### E4 — Mémoire du raster

Le plafond de 60 Mpx suréchantillonnés est conservé : S11 montre qu'un canevas de 96 Mpx reste
traitable en moins de 2 s. En revanche, le tampon est en **RGB** dès que le fond est opaque (JPEG,
PDF, PNG sans transparence), ce qui ramène le pire cas de 240 à 180 Mo. Le RGBA est réservé au PNG
à fond transparent.

### E5 — Portée « Ce chapitre »

Un chunk appartient au chapitre `A::B` si son deck vaut `A::B` ou commence par `A::B::`. La
comparaison se fait **segment par segment**, pas sur le préfixe de chaîne brut : `A::B` ne doit pas
capturer `A::Bretagne`.

### E6 — Identifiants fusionnés

La fusion préfixe les `id` par le chunk (`c12_gatt`), mais un `id` fait au plus 48 caractères. Le
préfixe tronque donc la fin de l'`id` d'origine, puis ajoute `-2`, `-3`… en cas de collision. Le
résultat reste déterministe (ordre des chunks, puis ordre du document).

### E7 — Police et PR

Les fichiers Inter 4.1 sont déjà vérifiés, mais ils entrent dans la PR de la **phase 2**, avec le
moteur qui les utilise, et non dans celle de la spec.

| Fichier | Taille | SHA-256 |
|---|---|---|
| `Inter-4.1.zip` (release officielle `rsms/inter` v4.1, source des trois fichiers) | 33 707 794 | `9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e` |
| `static/fonts/Inter-Regular.ttf` (`extras/ttf/`) | 411 640 | `40d692fce188e4471e2b3cba937be967878f631ad3ebbbdcd587687c7ebe0c82` |
| `static/fonts/Inter-SemiBold.ttf` (`extras/ttf/`) | 419 744 | `78a843fade9d4612a5567302fb595b56976eb5fcebf4fea5a5912d638bafcde3` |
| `static/fonts/OFL.txt` (`LICENSE.txt` de l'archive) | 4 380 | `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a` |

## Architecture retenue

L'architecture est celle du §14 du prompt, plus `timeline_fonts.py` (D2) :

```
JSON collé / importé / écrit
  └─ timeline_extract.parse_response ── nettoyage (§4.3) ──► timeline_schema.validate ─► rapport
                                                               │   (timeline_dates)
                                                               ▼
                                                    document normalisé ──► timeline_store
                                                               │
      timeline_fonts (avances, cmap) ──measure──► timeline_layout.layout ─► display list ─► check_layout
                                                               │
                                   ┌───────────────────────────┼──────────────────────────┐
                                   ▼                           ▼                          ▼
                         timeline_render_svg      timeline_render_raster      timeline_cards
                       (aperçu + export SVG)   (PNG, JPEG, WebP, PDF, images    (TSV, ZIP,
                                                     des cartes)            collection.media)
```

- Le module `timeline_layout` est pur : il ne fait ni I/O, ni Flask, ni Pillow. En production,
  `measure` vient de `timeline_fonts`. Dans les tests, c'est un mesureur factice fait d'une table de
  largeurs par caractère.
- Les imports `timeline_*` restent **dans les routes**, pour qu'une frise cassée n'empêche jamais
  l'app de démarrer. `build_app_payload` les suit quand même, puisqu'il voit les imports placés dans
  les fonctions.
- La sonde `timeline_raster` de S2 entre dans `runtime_probe.py` en phase 5, avec les exports.
  Elle est déjà prouvée sur l'exe du runtime 1. `runtime.json` ne bouge pas, et il n'y a pas de
  `--bump`.

## Hors périmètre

Le §18 du prompt s'applique. S'y ajoute la réparation des sidecars orphelins (voir S9), qui
relève du shell Tauri et fait l'objet d'une tâche séparée.

## Vérification de la phase 0

- Chaque spike a été exécuté sur cette machine (venv, exe gelé, app installée). Les chiffres
  ci-dessus viennent de ces exécutions. Les scripts sont jetables et ne sont pas versionnés.
- Aucun code produit n'est écrit avant la validation de ce document et du plan.
