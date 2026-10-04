# Prompt — Frises chronologiques dans Ankigen

> À donner tel quel à un agent de code (Claude Code) lancé à la racine du dépôt `Anki-Gen`.
> Il décrit la fonctionnalité, les contraintes du dépôt, les décisions déjà prises, l'architecture
> attendue, le découpage en phases et les critères d'acceptation. Les sections marquées
> **Décision** peuvent être rediscutées avant de lancer l'agent ; tout le reste est un contrat.

---

## 0. Mission

Tu ajoutes à Ankigen une fonctionnalité **Frise chronologique**.

À partir d'un **cours entier**, d'un **chapitre**, d'un **paragraphe** (un chunk) ou d'un **texte
collé**, Ankigen doit :

1. **obtenir une description structurée de la chronologie au format JSON** (produite par un LLM
   via le copier-coller habituel, ou importée ou écrite à la main) ;
2. **la valider** avec des messages d'erreur précis et un prompt de correction prêt à recoller ;
3. **dessiner une frise lisible, multi-pistes (« tracés »), sans aucun chevauchement**, avec des
   évènements ponctuels, des périodes et des ères en fond ;
4. **l'exporter** en SVG, PNG, JPEG, WebP, PDF et JSON (le presse-papiers est un bonus) ;
5. **en tirer des cartes Anki** (date ↔ évènement, bornes de période, remise en ordre, cartes image
   de la frise avec l'étiquette masquée), exportées dans le même format TSV/ZIP que les cartes
   actuelles.

Tu travailles **phase par phase** (§17). Chaque phase donne une PR autonome, testée, avec des
captures d'écran. Avant d'écrire le moindre code produit, tu rédiges la spec et le plan (§20) et tu
me les fais valider.

---

## 1. Le dépôt : ce qu'il faut lire, et les règles qui ne se négocient pas

### 1.1 À lire en entier avant de commencer

| Fichier | Pourquoi |
|---|---|
| `README.md`, `CONTRIBUTING.md` | philosophie (local, sans clé d'API, copier-coller vers Claude), conventions |
| `design.md` | design system : pas de bordures, un seul accent, Inter, dock toujours visible, mode sombre |
| `app.py` | routes Flask, `tsv_bytes`, `_write_export_copy`, `_with_export_headers` (X-Export-Path) |
| `project_store.py` | format des projets v2, `normalize()`, `list_projects()` (**glob `*.json` dans `projects/`**), `export_rows`, `copy_media` |
| `render.py` | `render_prompt_text`, `resolve_placeholders`, échappement HTML |
| `parse_cours.py`, `docx_blocks.py` | chunks, `deck` = chemin des titres (`A::B::C`) |
| `build_anki_csv.py` | `ANKI_HEADER_LINES`, `parse_tsv_response` |
| `media_store.py` | nommage `ag_<project>_<sha1>.png`, conversion Pillow |
| `paths.py`, `launcher.py`, `updater.py` | `DATA_DIR` / `APP_DIR`, mises à jour par `app.zip` |
| `i18n.py`, `locales/en.json`, `locales/fr.json` | `t()`, `tr()`, `window.T()` |
| `templates/base.html`, `templates/work.html`, `static/app.js`, `static/style.css` | structure de la vue de travail, rail, onglets, dock, modale d'export |
| `skill_templates/fr.md` | conventions HTML des cartes (dates en rouge souligné, etc.) |
| `scripts/build_app_payload.py`, `scripts/runtime_contract.py`, `runtime_probe.py`, `runtime.json` | le contrat entre l'exécutable et app.zip (§15) |
| `docs/superpowers/plans/2026-09-23-local-agent-generation.md` | plan d'agent local (non fusionné). La frise doit s'y brancher plus tard sans refonte |
| `tests/` | style des tests (`unittest`, fixtures générées, `node --test` pour le JS) |

### 1.2 Contraintes du dépôt

- **Dépendances.** Le runtime est volontairement réduit à Flask, Waitress, python-docx, lxml et
  Pillow. **Aucune nouvelle dépendance Python ou JS** sans me la proposer d'abord avec sa
  justification. Tout ce plan est conçu pour tenir avec la bibliothèque standard et **Pillow**.
- **Frontend.** HTML, CSS natif et JS vanilla. Pas de framework, pas d'étape de build, pas de CDN au
  runtime pour la frise : l'app doit fonctionner hors ligne.
- **Tests.** `unittest` uniquement (`pytest` interdit), lancés par
  `.venv/Scripts/python.exe -m unittest discover -s tests`. La suite reste verte et le nombre de
  tests ne fait que monter. Aucun fixture binaire versionné : les fixtures de frise sont des
  fichiers JSON texte.
- **i18n.** Aucun texte visible en dur. Chaque clé est ajoutée à `locales/en.json` **et** à
  `locales/fr.json`, sous le préfixe `timeline.*`. `tests/test_i18n.py` vérifie la parité.
- **Style de code.** Suivre le fichier édité : 4 espaces, snake_case, docstring de module qui dit
  *pourquoi* le module existe, commentaires qui expliquent les décisions. Les commentaires et
  docstrings existants sont **en français** : écris les tiens en français.
- **Commits.** Conventional Commits en anglais, à l'impératif (`feat(timeline): …`). Une PR par
  sujet et par phase. Branches `feat/timeline-<phase>`.
- **Design.** Respecter `design.md` pour l'UI (pas de `border`, accent `#0071E3` réservé au CTA
  principal, à l'état actif, au focus et à la progression, dock toujours visible, rayons, ombres,
  mode sombre). La frise elle-même est une **visualisation de données** : elle a sa propre palette
  catégorielle (§8.4), qui ne consomme pas le budget d'accent de l'UI.
- **Local d'abord.** Rien ne sort de la machine. Pas d'appel réseau pour la frise, et la police
  doit être disponible hors ligne (§8.3).

---

## 2. Parcours utilisateur

### 2.1 Points d'entrée

1. **Vue de travail** (`/work/<project_id>`) : un bouton **Frise** dans la topbar ouvre un
   sélecteur de portée :
   - **Ce paragraphe** : le chunk courant ;
   - **Ce chapitre** : l'utilisateur choisit un niveau de titre parmi les ancêtres du chunk courant.
     Ils se déduisent du `deck` (`Économie::Mondialisation::Les phases` propose
     « Mondialisation » ou « Mondialisation › Les phases »). La portée couvre tous les chunks dont
     le `deck` commence par ce préfixe ;
   - **Tout le cours** : tous les chunks du projet.
   Le sélecteur affiche le nombre de caractères et une estimation de tokens, puis propose le mode
   d'extraction (§6.4).
2. **Tableau de bord** (`/`) : une section **Frises** liste les frises existantes (titre, source,
   nombre d'éléments, date de mise à jour). Un bouton **Nouvelle frise** ouvre une modale à deux
   onglets : **Depuis un texte** (titre, langue, zone de texte) et **Importer un JSON** (dépôt de
   fichier ou collage).
3. **Page frise** (`/timeline/<timeline_id>`) : l'espace de travail de la frise (§13).

### 2.2 Flux nominal (manuel, comme les cartes aujourd'hui)

```
Portée choisie ──► Prompt d'extraction (copier) ──► Claude ──► JSON (coller)
      ──► Validation ──(erreurs)──► Prompt de correction (copier) ──► Claude ──► JSON (coller) ─┐
      ◄────────────────────────────────────────────────────────────────────────────────────────┘
      ──► Aperçu de la frise ──► Édition (formulaires ou JSON brut) ──► Export image/PDF
                                                                   └─► Cartes Anki (TSV / ZIP / collection.media)
```

### 2.3 Récits utilisateur (critères d'acceptation fonctionnels)

- *En tant qu'étudiant*, je sélectionne « Ce chapitre », je copie le prompt et je colle la réponse
  de Claude. J'obtiens une frise lisible en moins d'une minute, sans retoucher le JSON.
- Si Claude se trompe de format, je vois **où** (`/events/4/date`) et **pourquoi**. Un bouton me
  donne un prompt de correction complet à recoller.
- Je vois immédiatement quels évènements **ne viennent pas du cours** : leur citation source est
  introuvable, ou le modèle les a ajoutés en mode enrichi.
- J'édite un évènement (date, libellé, piste, importance) et la frise se redessine en moins de
  300 ms.
- J'exporte la frise en PNG 2× pour mes fiches, en PDF A4 paysage pour l'imprimer et en SVG pour
  la retoucher dans Inkscape.
- Je génère des cartes « En quelle année… ? », « Remettez dans l'ordre… » et des cartes image où un
  évènement est masqué sur la frise. Je les importe dans Anki avec leurs images.
- Aucune configuration de données ne produit de texte qui se chevauche. S'il y a trop
  d'évènements, la frise bascule sur des notes numérotées au lieu de superposer.

---

## 3. Principes directeurs

1. **Le modèle renvoie des objets, le code dessine.** Le LLM produit uniquement du JSON conforme au
   contrat (§4). Il ne produit jamais de SVG, de HTML ni de coordonnées. C'est la même règle que
   dans le plan d'agent local.
2. **Zéro chevauchement, garanti et vérifié.** Le moteur de mise en page produit une *display list*
   (§7.1). Une fonction `check_layout()` la vérifie contre une liste d'invariants (§7.8), dans les
   tests **et** à l'exécution. Un rendu qui viole un invariant n'est jamais livré en silence.
3. **Fidélité aux données.** La position horizontale d'un marqueur est exactement `scale(date)`.
   Seules les **étiquettes** se déplacent. Un élément n'est jamais masqué sans trace : s'il n'est
   pas étiqueté en place, il apparaît dans les notes numérotées.
4. **Déterminisme.** Une même entrée et les mêmes options produisent une display list identique à
   l'octet près. Pas de hasard sans graine, pas de dépendance à l'ordre d'un `dict` ou d'un `set`.
5. **L'aperçu est l'export.** Le SVG affiché dans l'app sort du même moteur et de la même display
   list que les exports. Il n'existe pas de second chemin de rendu côté navigateur.
6. **Séparation stricte** : contrat → dates → validation → mise en page (pure, sans I/O) → display
   list → moteurs de rendu (SVG, raster) → exports. Chaque étage se teste seul.
7. **Rester branchable sur l'agent local.** L'extraction passe par une interface
   (`TimelineExtractor`) dont la seule implémentation v1 est `manual` (copier-coller). Le schéma
   JSON est livré sous une forme utilisable telle quelle en `response_format: json_schema`
   (llama.cpp, Ollama, LM Studio).

---

## 4. Le contrat JSON (`ankigen.timeline/1`)

### 4.1 Forme

```jsonc
{
  "schema": "ankigen.timeline/1",          // requis, constante : sert aux migrations futures
  "title": "La dynamique de la mondialisation économique",   // requis, ≤ 120
  "subtitle": "Du libre-échange britannique à l'OMC",        // optionnel, ≤ 200
  "lang": "fr",                            // langue du CONTENU (formatage des dates), défaut = langue de l'UI
  "as_of": "2026-09-28",                   // optionnel : référence pour "present"

  "tracks": [                              // 0–12 pistes ("tracés"). 0 → une piste implicite sans libellé
    { "id": "commerce",     "label": "Commerce" },                      // label ≤ 40
    { "id": "monnaie",      "label": "Monnaie et finance", "color": "#0072B2" },
    { "id": "institutions", "label": "Institutions", "order": 3 }
  ],

  "eras": [                                // 0–20 bandes de fond qui traversent toutes les pistes
    { "id": "premiere_mondialisation", "label": "Première mondialisation",
      "start": "1870", "end": "1914", "approx": true },
    { "id": "desintegration", "label": "Désintégration de l'économie mondiale",
      "start": "1914", "end": "1945" }
  ],

  "periods": [                             // 0–200 durées, dessinées en barres dans leur piste
    { "id": "bretton_woods", "track": "monnaie", "label": "Système de Bretton Woods",
      "start": "1944-07", "end": "1971-08-15", "importance": 3,
      "description": "Changes fixes mais ajustables, dollar convertible en or.",
      "source_quote": "le système de Bretton Woods, qui prend fin en 1971" }
  ],

  "events": [                              // 0–400 évènements ponctuels
    { "id": "cobden_chevalier", "track": "commerce", "date": "1860-01-23",
      "label": "Traité Cobden-Chevalier", "importance": 3,
      "description": "Traité de libre-échange franco-britannique, modèle de la clause de la nation la plus favorisée.",
      "date_text": "en 1860",
      "source_quote": "le traité Cobden-Chevalier de 1860",
      "tags": ["libre-échange"], "origin": "text" },
    { "id": "gatt", "track": "institutions", "date": "1947-10-30",
      "label": "Signature du GATT", "importance": 3, "origin": "text",
      "source_quote": "le GATT, signé en 1947" },
    { "id": "nixon", "track": "monnaie", "date": "1971-08-15",
      "label": "Fin de la convertibilité du dollar en or", "importance": 3, "origin": "text",
      "source_quote": "la suspension de la convertibilité-or du dollar en août 1971" }
  ],

  "links": []                              // optionnel, réservé à la phase 8 (flèches cause → conséquence)
}
```

Autres formes de dates, pour la documentation et les fixtures :
`{"date": "-1750", "approx": true, "label": "Code de Hammurabi"}` s'affiche « v. 1750 av. J.-C. »,
et `{"date": "1970", "precision": "decade"}` s'affiche « années 1970 ».

### 4.2 Champs communs aux éléments (`eras`, `periods`, `events`)

| Champ | Type | Règle |
|---|---|---|
| `id` | string | `^[a-z0-9][a-z0-9_-]{0,47}$`, **unique sur tout le document**, tous types confondus |
| `track` | string | doit exister dans `tracks` (sauf si `tracks` est vide). Absent de `eras` |
| `label` | string | 1–80 caractères (60 pour les ères). Groupe nominal court. **Ne doit pas contenir la date** (avertissement sinon) |
| `description` | string | ≤ 600. Sert aux cartes et à l'infobulle, jamais dessinée par défaut |
| `importance` | int | 1, 2 ou 3 (défaut 2). 3 = pivot du cours : priorité de placement, marqueur plus gros, jamais regroupé |
| `approx` | bool | défaut `false`. Préfixe « v. » / « c. » et marqueur pointillé |
| `precision` | enum | `day`, `month`, `year`, `decade`, `century`, `millennium`. Déduite de la chaîne si absente (§5). `decade` et au-delà seulement avec une année seule |
| `date_text` | string | ≤ 80. Formulation d'origine (« au lendemain de la guerre ») |
| `source_quote` | string | ≤ 240. **Extrait littéral** du texte source. Vérifié (§6.5) |
| `origin` | enum | `text` (défaut) ou `model` (ajouté par le modèle en mode enrichi, §6.3) |
| `tags` | string[] | ≤ 8 × 30 caractères |
| `color` | string | `^#[0-9A-Fa-f]{6}$` seulement. Tout le reste est refusé (injection CSS dans le SVG) |

### 4.3 Règles de validation

**Erreurs** (bloquantes) :

- JSON invalide. Le message donne la ligne, la colonne et un extrait (`json.JSONDecodeError.lineno` / `colno`).
- `schema` absent ou inconnu, champ requis manquant, type incorrect, longueur ou nombre maximal dépassé.
- Clé inconnue. `additionalProperties: false` partout : une faute de frappe (`lable`) doit se voir.
- `id` dupliqué ou malformé, `track` inexistant.
- Date invalide (§5). `end` avant `start`. L'année 0 n'existe pas (on passe de 1 av. J.-C. à 1 ap. J.-C.). `present` utilisé ailleurs que dans `end`.
- Document vide (aucun évènement, aucune période).
- Ères qui se chevauchent de plus d'une unité de précision. Un recouvrement d'une unité, comme
  « 1870–1914 » suivi de « 1914–1945 », est toléré et **coupé au point de contact**.

**Avertissements** (non bloquants, affichés dans l'UI et repris dans le prompt de correction si
l'utilisateur le souhaite) :

- `label` qui contient l'année de sa propre date, ou libellé tronqué à l'affichage.
- Siècle ambigu (§5.3).
- `source_quote` introuvable dans le texte source (§6.5), ou `origin: "model"`.
- Doublons probables : même date à la précision commune et libellés similaires à ≥ 0,85
  (`difflib.SequenceMatcher` sur une forme normalisée).
- Plus de 25 % des éléments en importance 3.
- Piste déclarée mais vide.

**Tolérances à l'import** (normalisation silencieuse, consignée dans le rapport) :

- supprimer les clôtures ```` ```json ```` et le texte avant le premier `{` ou après le dernier `}` ;
- supprimer le BOM ;
- convertir une année donnée en nombre (`1846`) en chaîne ;
- `trim` des chaînes ;
- `importance` absente → 2.

Rien d'autre n'est « réparé » : les guillemets typographiques ou les virgules finales produisent
une erreur, et c'est le prompt de correction qui s'en charge.

**Format du rapport** :

```json
{ "ok": false,
  "errors":   [{ "path": "/events/3/date", "code": "date_invalid",
                 "message": "« vers 1450 » n'est pas une date.",
                 "hint": "Écrire \"1450\" et ajouter \"approx\": true." }],
  "warnings": [{ "path": "/events/7/label", "code": "label_contains_year", "message": "…" }],
  "normalized": { … } }
```

Chaque `code` correspond à une clé i18n `timeline.err.<code>` ou `timeline.warn.<code>`. Les
chemins suivent la syntaxe JSON Pointer.

### 4.4 Le schéma JSON livré

- Fichier `static/schemas/timeline-v1.json` (JSON Schema 2020-12). Il est servi par l'app,
  téléchargeable depuis la page d'aide, et embarqué automatiquement parce que `static/` l'est déjà.
- N'utiliser que le sous-ensemble que les grammaires de llama.cpp savent compiler : `type`, `enum`,
  `const`, `required`, `properties`, `additionalProperties: false`, `maxLength`, `maxItems`,
  `minimum`, `maximum` et `pattern` simple pour les dates. Pas de `$ref` récursif, pas de
  `patternProperties`, pas de `oneOf` complexe.
- La validation Python est **écrite à la main** (`timeline_schema.py`), sans la bibliothèque
  `jsonschema`. Un test vérifie que le fichier de schéma et les constantes Python (limites, enums,
  clés autorisées) racontent la même chose.

---

## 5. Les dates

### 5.1 Représentation interne

- Chaîne d'entrée : `^-?\d{1,5}(-\d{2}(-\d{2})?)?$`, ou `present` (dans `end` seulement).
- Les années négatives sont **historiques** : `-44` veut dire 44 av. J.-C. et il n'y a pas d'année
  0. En interne, on convertit en année **astronomique** (`-44` → `-43`) pour que l'arithmétique
  soit continue.
- Calendrier grégorien proleptique. Le mois est vérifié dans 1–12 et le jour contre la longueur du
  mois (années bissextiles comprises, règle astronomique pour les années négatives). **Aucune
  conversion julien → grégorien** : une date d'avant 1582 est prise telle qu'écrite (§18).
- Chaque date devient un **intervalle** `[t0, t1)` en années décimales (`float`), selon sa
  précision. `t = année_astro + (jour_de_l'année − 1) / jours_dans_l'année`.
- N'utilise pas `datetime` pour le stockage ou l'arithmétique : il ne gère ni les années ≤ 0 ni
  les années > 9999. `datetime.date` reste utile pour valider le jour d'un mois quand
  1 ≤ année ≤ 9999, avec un calcul manuel en dehors.

### 5.2 Position sur l'axe

| Élément | Position |
|---|---|
| Évènement `day`, `month` ou `year` | marqueur à `t0` (lecture conventionnelle : l'évènement « 1850 » tombe sur la graduation 1850) |
| Évènement `decade`, `century` ou `millennium` | marqueur au centre de `[t0, t1)`, avec une **moustache d'incertitude** sur tout l'intervalle |
| `start` d'une période ou d'une ère | `t0` de la date |
| `end` d'une période ou d'une ère | **`t1`** de la date : la fin est inclusive, donc « 1939–1945 » couvre 1945 |
| `end: "present"` | `as_of` ou la date du jour, dessiné avec un fondu et une flèche ouverte |

### 5.3 Précisions larges

- `decade` : `"1970"` couvre 1970–1979 (« années 1970 », « 1970s »).
- `century` : convention stricte, XVIe = 1501–1600. Une année multiple de 100 (`"1500"`) est
  ambiguë. Elle déclenche l'avertissement `century_ambiguous` et **est lue comme le début du siècle
  suivant** (1500 → XVIe), parce que c'est l'erreur la plus fréquente des modèles. Le prompt
  d'extraction demande explicitement la première année du siècle (1501).
- `millennium` : même logique (IIIe millénaire av. J.-C. = −3000 à −2001).

### 5.4 Affichage (suit `lang` du document, pas la langue de l'UI)

| Cas | fr | en |
|---|---|---|
| jour | 15 août 1971 | 15 Aug 1971 |
| mois | août 1971 | Aug 1971 |
| année | 1971 | 1971 |
| av. J.-C. | 44 av. J.-C. | 44 BC |
| approximatif | v. 1450 | c. 1450 |
| décennie | années 1970 | 1970s |
| siècle | XVIe siècle / XVIe s. (forme courte) | 16th century / 16th c. |
| millénaire | IIIe millénaire av. J.-C. | 3rd millennium BC |
| période | 1870–1914 · 753–509 av. J.-C. · 44 av. J.-C.–14 | idem avec BC / AD si nécessaire |
| en cours | depuis 2001 | since 2001 |

Les noms de mois, suffixes et formats vivent dans les catalogues i18n (`timeline.date.*`). On les
appelle avec `translate(key, doc_lang)`. Si la langue du document n'a pas de catalogue, on retombe
sur l'anglais.

---

## 6. Extraction par LLM

### 6.1 Constitution du texte source

- Chunks : on réutilise `prompt["prompt"]`, le texte déjà rendu par `render_prompt_text`. Il
  contient les tableaux en markdown, et **les tableaux chronologiques sont fréquents dans les
  cours**. Il contient aussi les descriptions d'images.
- Chaque chunk est précédé de son chemin de titres (`## Mondialisation › Les phases`) pour que le
  modèle ait le contexte.
- La portée « texte libre » stocke le texte tel quel.
- On garde un **instantané** du texte source dans la frise, pour vérifier les citations et
  reconstruire les prompts même si le projet change ou disparaît. On garde aussi un hash pour
  détecter qu'il a changé.

### 6.2 Le prompt d'extraction

Il est généré par `timeline_prompt.py` à partir de `prompt_templates/timeline_extract.<lang>.md`,
un fichier versionné et relisible sans toucher au code. Il contient **toujours**, dans la langue
du document :

1. **Le rôle et la consigne** : extraire la chronologie du texte, **rien que le texte**. Chaque
   date doit être présente ou directement déductible du passage. Pas de date inventée, pas de date
   « précisée » au-delà de ce que dit le texte.
2. **Le contrat** : forme JSON abrégée, limites, formats de date avec exemples (y compris
   av. J.-C., `approx`, `decade`, `century` avec la règle « première année du siècle : 1501 »,
   `present`).
3. **Des règles éditoriales** :
   - 2 à 5 pistes thématiques (politique, économie, société…) ou géographiques. Une seule piste si
     le passage est monothématique. Libellés de piste de 1 à 3 mots.
   - Un évènement ponctuel est une date ; une durée est une période. Une époque qui encadre tout
     est une ère.
   - Des libellés de 2 à 8 mots, sans la date, sans verbe conjugué si possible.
   - `importance` : 3 pour les pivots du passage (au plus ~20 %), 2 pour l'important, 1 pour le
     détail.
   - `source_quote` : l'extrait **copié à l'identique**, 5 à 25 mots.
   - `description` : une ou deux phrases qui disent **pourquoi** ça compte dans ce cours.
4. **Un exemple court et complet**, dans la langue du document, qui respecte toutes les règles.
5. **Le format de sortie** : uniquement le JSON, sans texte autour ni bloc de code (on tolère
   quand même les clôtures, §4.3).
6. **Le texte source**, délimité clairement (`<<<SOURCE` … `SOURCE>>>`).

Contrairement aux cartes, où l'utilisateur écrit son propre Skill parce que le style est une
affaire de goût, **le contrat de la frise appartient à l'app** : il est donc toujours inclus dans
le prompt copié. Un modèle de Skill « frise » optionnel est proposé sur la page d'aide pour ceux
qui préfèrent l'installer dans Claude. Il contient le contrat, et le prompt copié se réduit alors
au texte source si l'option « J'ai installé le Skill » est cochée.

### 6.3 Modes d'extraction

- **Strict** (défaut) : uniquement ce que contient le texte.
- **Enrichi** : le modèle peut ajouter des dates de contexte indispensables, marquées
  `origin: "model"` et sans `source_quote`. Elles sont dessinées différemment (marqueur creux,
  astérisque, légende « hors cours ») et exclues des cartes par défaut.

### 6.4 Portées longues : un seul prompt ou paragraphe par paragraphe

**Décision** : au-delà d'environ 25 000 caractères de texte source, le mode par défaut devient
**« paragraphe par paragraphe + fusion »**. C'est l'argument du README appliqué à la frise : un
chapitre entier collé d'un coup fait survoler le modèle.

- **Un seul prompt** : proposé tant que la portée est courte, et toujours disponible avec un
  avertissement.
- **Paragraphe par paragraphe** : même navigation que la vue de travail (liste des chunks de la
  portée, état vide / collé / erreur, copier, coller, suivant). Chaque réponse est validée seule.
- **Fusion** (`timeline_merge.py`) :
  - les `id` sont préfixés par le chunk (`c12_gatt`) pour éviter les collisions ;
  - les pistes sont fusionnées par libellé normalisé (casse, accents et espaces ignorés) ;
  - les doublons (même date à la précision commune et libellés similaires à ≥ 0,85) sont fusionnés
    en gardant l'importance maximale, la description la plus longue, l'union des tags et **toutes**
    les citations ;
  - un rapport de fusion est affiché : « 47 éléments, 6 doublons fusionnés, 2 pistes
    rapprochées ». L'utilisateur peut annuler une fusion individuelle.

### 6.5 Vérification des citations (anti-hallucination)

- On normalise le texte source et la citation : NFKC (`unicodedata`), minuscules, apostrophes et
  guillemets unifiés, espaces compressés, balises markdown retirées.
- Correspondance exacte d'abord, puis **floue** : meilleure fenêtre glissante avec
  `SequenceMatcher` ≥ 0,9, bornée pour rester rapide.
- Résultat par élément : `verified`, `fuzzy` ou `not_found`. Il s'affiche en badge dans l'éditeur
  et en style de marqueur dans l'aperçu. Dans l'export, ce marquage est une option désactivée par
  défaut.

### 6.6 Prompt de correction

Le bouton « Prompt de correction » produit, dans la langue du document :
« Ton JSON contient les erreurs suivantes : » suivi de la liste chemin → message → indice, puis
éventuellement les avertissements, puis « Renvoie le JSON **complet** corrigé, rien d'autre. » Le
JSON fautif n'y est pas recopié : il est déjà dans la conversation Claude.

### 6.7 Interface d'extraction (préparer l'agent local)

```python
class TimelineExtractor:            # timeline_extract.py
    def build_request(self, source_text, lang, mode) -> dict: ...   # prompt, schéma
    def parse_response(self, raw) -> tuple[dict | None, report]: ...
```

La v1 ne fournit que `ManualExtractor` (copier-coller). Quand l'agent local existera, un
`LocalExtractor` enverra `static/schemas/timeline-v1.json` en `response_format` et réutilisera
`parse_response` et le prompt de correction pour ses nouvelles tentatives.

---

## 7. Le moteur de mise en page (`timeline_layout.py`)

C'est le cœur de la fonctionnalité. Le module est **pur** : pas d'I/O, pas de Flask, pas de
Pillow. Il reçoit la mesure du texte par injection.

```python
layout(doc: dict, options: LayoutOptions, measure: Callable[[str, float, int], float]) -> Layout
# measure(text, font_size_px, weight) -> largeur en px
# Layout = (width, height, display_list: list[Primitive], legend_notes, stats, warnings)
```

- En production, `measure` utilise `ImageFont.truetype(Inter).getlength` : c'est la **même police
  que celle du rendu** (§8.3), donc les largeurs sont exactes.
- Dans les tests, `measure` est un mesureur factice déterministe (table de largeurs par caractère),
  ce qui rend les tests indépendants de Pillow et des polices.

### 7.1 Display list

Des primitives en `dataclass(frozen=True)`, toutes avec `role` et `ref` :

| Primitive | Champs |
|---|---|
| `Rect` | x, y, w, h, rx, fill, stroke, opacity |
| `Line` | x1, y1, x2, y2, stroke, width, dash |
| `Path` | d (sous-ensemble M/L/C/Z), fill, stroke, width : ruptures d'axe, moustaches, flèches |
| `Marker` | shape (`circle`, `diamond`, `square`, `triangle`, `hexagon`), cx, cy, r, fill, stroke, dashed |
| `Text` | x, y (ligne de base), lines[], size, weight, fill, anchor (`start`, `middle`, `end`), line_height, **bbox calculée** |

- `role` ∈ `title`, `subtitle`, `era-band`, `era-label`, `axis`, `tick`, `tick-label`,
  `gridline`, `lane-bg`, `lane-label`, `period-bar`, `period-label`, `marker`, `stem`,
  `event-label`, `event-date`, `whisker`, `badge`, `note`, `legend`, `break`.
- `ref` : l'`id` de l'élément du document, ou `None`. Il sert à vérifier les chevauchements, aux
  attributs `data-ref` du SVG (interaction), et au **masquage** pour les cartes (§10.3).

### 7.2 Options

`orientation` (`horizontal` en v1, `vertical` en phase 8), `width_mode` (`auto` | `fixed`),
`width_px`, `density` (`comfortable` | `compact`), `axis_breaks` (`auto` | `off`),
`label_max_width` (180 / 140 px), `max_levels_per_side` (4 / 6), `show_descriptions` (false),
`show_unverified` (true en aperçu), `theme` (§8.4, n'influe que sur les couleurs), `locale`.
Toutes les tailles suivent la grille de 4 px de `design.md`. **Les valeurs par défaut se règlent
après revue visuelle de la galerie** (§16.3).

### 7.3 Échelle, ruptures d'axe, graduations

1. **Domaine** : du plus petit `t0` au plus grand `t1`, avec `present` résolu et une marge de 2 %
   de chaque côté.
2. **Ruptures d'axe automatiques**. On calcule les intervalles occupés (évènements ± marge,
   périodes, ères) **sur toutes les pistes**. Un vide est compressible s'il dépasse 25 % du
   domaine et si le compresser au moins double la densité utile. Il est alors ramené à 40 px et
   marqué d'un zigzag sur l'axe et en travers des pistes. Au plus 3 ruptures. **Jamais au milieu
   d'une période ou d'une ère.** L'échelle devient linéaire par morceaux, avec `scale(t)` et
   `invert(x)`.
3. **Px par an** : en mode `fixed`, la largeur utile divisée par le domaine effectif. En mode
   `auto`, la valeur qui donne ~24 px au 20e percentile des écarts entre évènements consécutifs
   d'une même piste, bornée entre 900 et 12 000 px de large.
4. **Graduations** : « nombres ronds » (1, 2, 5 × 10ⁿ) par segment linéaire. L'unité (jour, mois,
   an, 5, 10, 25, 50, 100, 500 ou 1000 ans) dépend de la densité. Les libellés sont formatés selon
   la langue (§5.4) et gèrent l'an −1 → 1 sans montrer d'an 0. Les graduations restent, mais on
   retire les libellés qui se chevaucheraient (un sur deux, puis un sur quatre…). Les lignes de
   grille majeures sont très discrètes. Il y a un axe en haut, plus un axe en bas si la frise
   dépasse 600 px de haut.

### 7.4 Structure verticale (horizontal)

```
Titre / sous-titre
Rangées de libellés des ères (empilement sans chevauchement)
Axe haut
┌ Piste 1 : [libellé dans la gouttière gauche] [rangées de périodes] [zone évènements : étiquettes au-dessus / ligne de base + marqueurs / étiquettes en dessous]
├ Piste 2 : …
└ …
Axe bas (si besoin)
Légende : pistes (couleur + forme), notes numérotées, « * hors cours / non vérifié », ruptures d'axe
Ligne de crédit optionnelle (« Ankigen · source : CH1 … »)
```

- Les pistes sont séparées par l'espacement et une alternance de fonds très légers, sans bordure,
  conformément à `design.md`.
- La hauteur de chaque piste se calcule à partir de son contenu. Les pistes ne se recouvrent
  jamais.
- Les bandes d'ères couvrent la hauteur de l'axe haut à l'axe bas, avec des fonds alternés très
  pâles. Leurs libellés sont empilés comme des intervalles dans leurs propres rangées.

### 7.5 Périodes

- L'**emprise** d'une période est la barre plus son libellé s'il est dehors.
- Le libellé est **à l'intérieur** de la barre s'il tient avec sa marge. Sinon il va **à droite**
  de la barre dans la même rangée, si la place est libre jusqu'à la prochaine emprise. Sinon il
  passe en **note numérotée**, avec une pastille dans la barre.
- Placement en rangées par partitionnement d'intervalles glouton, trié par `(x0, −importance, id)` :
  chaque période va dans la première rangée où `fin_de_rangée + gap ≤ x0`. C'est optimal en nombre
  de rangées pour des intervalles.
- Barre en forme de pilule, de 18 px de haut, dans la couleur de la piste. La couleur du libellé
  intérieur (blanc ou encre) est choisie par contraste WCAG ≥ 4,5:1.
- Une période `approx` a ses extrémités en dégradé ou en hachures.

### 7.6 Évènements : placement des étiquettes

Chaque évènement a un **marqueur** sur la ligne de base de sa piste, à `x = scale(position)`, et
une **étiquette** (ligne de date + libellé sur 1 à 3 lignes) reliée par une **tige** verticale.

1. **Regroupement des évènements simultanés**. Ceux dont les marqueurs tomberaient à moins de
   `diamètre + 2 px` dans une même piste partagent un marqueur et **une** étiquette en liste
   (« 1945 · Fin de la guerre · Création de l'ONU »).
2. **Ordre de placement** : d'abord l'importance décroissante, ensuite l'ordre chronologique, puis
   l'`id` pour départager. Les pivots obtiennent les meilleures places.
3. **Candidats**, dans cet ordre de préférence :
   - niveaux `k = 1…K`, en alternant au-dessus et en dessous de la ligne de base (préférence
     alternée selon la parité du rang, pour équilibrer) ;
   - pour chaque niveau, des décalages horizontaux de l'étiquette par rapport à la tige : centrée,
     ±¼ de sa largeur, puis alignée à gauche ou à droite sur la tige. La tige, elle, reste à `x`.
4. **Un candidat est accepté** si sa bbox (marge de 4 px) ne touche aucun **obstacle** : étiquettes
   déjà placées, tiges déjà placées, marqueurs, rangées de périodes de la piste, gouttière des
   libellés de piste, bords du canevas et limites verticales de la piste. **Sa propre tige** ne
   doit pas non plus traverser une étiquette déjà placée. Une fois placées, l'étiquette et sa tige
   deviennent des obstacles.
5. **Échelle de repli**, par élément et dans cet ordre, dès que rien ne passe :
   1. repasser tous les candidats avec le libellé renvoyé sur 2 lignes, puis 3, mesurés, en réduisant `label_max_width` ;
   2. en mode `auto`, élargir le canevas de 25 % et **tout recommencer**, 3 fois au plus ;
   3. **note numérotée** : le marqueur reçoit une pastille ①②③… et l'étiquette part dans le bloc
      de notes de la légende (« ③ 1957 — Traité de Rome ») ; les importances 1, puis 2, sont
      renvoyées en notes en premier ;
   4. **grappe** : les évènements trop proches pour tenir même en pastilles deviennent une pastille
      « ×4 » avec une accolade sur leur étendue, et leurs notes sont listées. **Une importance 3
      n'entre jamais dans une grappe**, sauf impossibilité physique.
6. **Index spatial** : une grille de cases de 64 px sur x, pour ne tester que les obstacles
   voisins. Budget : 400 évènements mis en page en ≤ 300 ms sur une machine de dev.

### 7.7 Couleurs, formes et accessibilité dans la mise en page

- Chaque piste a une **couleur et une forme de marqueur** : la frise reste lisible en noir et blanc
  et sans la couleur.
- L'importance fixe la taille du marqueur (rayons 4 / 5,5 / 7) et la graisse du libellé (400 / 400 / 600).
- La ligne de date d'une étiquette est dans la couleur de la piste, avec un contraste ≥ 4,5:1
  contre le fond. On assombrit la couleur si besoin.

### 7.8 Invariants (`check_layout(layout) -> list[Violation]`)

| # | Invariant |
|---|---|
| I1 | Aucune paire de bbox de texte ne s'intersecte (marge ≥ 2 px) |
| I2 | Aucun texte ne touche un marqueur, une tige, une barre, une pastille ou une moustache, sauf le libellé **de sa propre** barre |
| I3 | Aucune tige ne traverse un texte |
| I4 | Tout tient dans le canevas, marges comprises |
| I5 | Chaque primitive d'une piste reste dans les limites verticales de cette piste, et les pistes ne se recouvrent pas |
| I6 | Le marqueur d'un évènement non groupé est à `scale(position) ± 0,5 px` |
| I7 | Chaque élément du document est représenté : étiqueté en place, en note numérotée ou dans une grappe listée |
| I8 | Déterminisme : deux appels donnent des display lists égales |
| I9 | Les ruptures d'axe ne tombent pas dans une période ou une ère |

- **Dans les tests** : chaque fixture et chaque cas de fuzz doit donner zéro violation.
- **À l'exécution** : `render()` appelle `check_layout`. En cas de violation, on passe au cran de
  repli suivant. Si des violations persistent (ce qui ne doit pas arriver), l'erreur est journalisée
  et renvoyée à l'UI comme avertissement visible. Jamais en silence.

---

## 8. Rendu

### 8.1 Moteur SVG (`timeline_render_svg.py`, bibliothèque standard uniquement)

- `<svg xmlns=… viewBox width height role="img" aria-labelledby>`, avec `<title>` et `<desc>`.
  `<desc>` liste les éléments en texte, pour l'accessibilité et pour qu'un LLM puisse relire le SVG.
- **Tout texte est échappé XML.** Les couleurs sont des littéraux hexadécimaux validés, sans
  variable CSS de la page : le fichier exporté doit être autonome.
- `<text>` avec une `<tspan x dy>` par ligne. Les ancres (`text-anchor`, `dominant-baseline`)
  correspondent exactement au moteur raster.
- Un `<g data-ref="…" class="tl-…">` par élément, pour l'interaction dans l'app.
- Police : `font-family="Inter, 'Segoe UI', sans-serif"`. À l'export, l'option **« Incorporer la
  police »** (activée par défaut) ajoute un `@font-face` en base64 dans un `<style>`. Documenter la
  limite : Inkscape et Illustrator gèrent mal les polices incorporées. Leur utilisateur installe
  Inter ou décoche l'option.

### 8.2 Moteur raster (`timeline_render_raster.py`, Pillow)

- Il consomme **la même display list**. Le dessin se fait avec `ImageDraw` : `rounded_rectangle`,
  `line`, `polygon`, `ellipse`, `text(anchor="ls" | "ms" | "rs")` avec `ImageFont.truetype`.
- Anticrénelage par **suréchantillonnage** (×2 ou ×3), puis réduction `LANCZOS`. Les opacités se
  font par calques et `alpha_composite`. Les pointillés sont dessinés à la main.
- **Budget mémoire** : plafonner la surface suréchantillonnée (par exemple 60 Mpx). Au-delà,
  réduire d'abord le suréchantillonnage, puis l'échelle, et prévenir l'utilisateur. Limites de
  format : JPEG ≤ 65 535 px par côté, WebP ≤ 16 383 px.
- Les capacités Pillow utilisées (FreeType, encodeurs PNG, JPEG, WebP et PDF) sont garanties par
  le runtime et vérifiées par des sondes dans `runtime_probe.py` (§15). Pas de détection au
  moment de l'appel ni de mode dégradé.

### 8.3 Polices

- Embarquer `static/fonts/Inter-Regular.ttf` et `static/fonts/Inter-SemiBold.ttf` avec
  `static/fonts/OFL.txt` (Inter est sous SIL OFL 1.1, compatible GPL). Créditer la police dans le
  README.
- La page frise déclare un `@font-face` **local** vers ces fichiers, sans passer par Google Fonts.
  Sinon, hors ligne, l'aperçu utiliserait une autre police que celle qui a servi aux mesures, et
  le texte déborderait.

### 8.4 Thèmes et palette

- **Thèmes** : `light` (fond `#FFFFFF`, encre `#1D1D1F`, secondaire `#86868B`, repris de
  `design.md`), `dark` (fond `#1C1C1E`, encre `#F5F5F7`…) et `print` (fond blanc, encre noire,
  pistes en niveaux de gris, formes de marqueurs obligatoires, sans fonds pâles).
- **Palette des pistes** : 8 couleurs catégorielles adaptées aux daltoniens, sur la base
  d'Okabe–Ito ajustée. Le jaune pur est exclu parce qu'il est illisible sur fond blanc. Chaque
  couleur est validée par un test : contraste ≥ 3:1 contre le fond de chaque thème pour les
  marqueurs, et ≥ 4,5:1 pour le texte, quitte à assombrir. Si le skill `dataviz` est disponible
  dans ta session, charge-le avant de fixer la palette.
- L'aperçu suit le thème de l'UI (`prefers-color-scheme`). L'export est en `light` par défaut, et
  le thème s'y choisit indépendamment de l'UI.

---

## 9. Exports

| Format | Moteur | Options | Remarques |
|---|---|---|---|
| **SVG** | SVG | thème, largeur, incorporer la police | vectoriel et autonome |
| **PNG** | Pillow | échelle 1× à 4×, fond transparent | plafond de surface (§8.2) |
| **JPEG** | Pillow | qualité (90), thème | pas d'alpha : aplatir sur le fond du thème |
| **WebP** | Pillow | qualité ou sans perte | ≤ 16 383 px par côté |
| **PDF** | Pillow, raster 300 dpi (`save(..., "PDF", resolution=300)`) | page : ajustée au contenu, A4 ou A3, portrait ou paysage, marges ; titre et auteur en métadonnées | si l'échelle d'ajustement descend sous 0,5 → proposer A3 ou le PDF multipage (phase 8) |
| **PDF vectoriel** | `window.print()` sur une vue d'impression dédiée (`@page` à la taille de la frise) | — | **à valider en phase 0** dans WebView2 ; proposé sous le nom « Imprimer / PDF vectoriel » si ça marche |
| **JSON** | — | — | document normalisé (§4), réimportable |
| **Presse-papiers** | navigateur : `navigator.clipboard.write([new ClipboardItem({"image/png": blob})])` | échelle | détection de la fonction ; à valider en phase 0 dans WebView2 |
| HTML interactif | — | — | phase 8 (fichier autonome avec infobulles) |

- Nom de fichier : `<slug(titre)>.<ext>`, assaini comme `sanitize_filename`.
- **Réutiliser `_with_export_headers`** pour la copie dans le dossier d'export de l'utilisateur et
  l'en-tête `X-Export-Path`. Réutiliser aussi la façon dont `static/app.js` affiche le chemin
  obtenu. L'expérience d'export doit être identique à celle des cartes.
- Une modale d'export présente les options avec un aperçu miniature, les dimensions finales en px,
  en mm ou en pages, et le poids estimé.

---

## 10. Cartes Anki depuis la frise (`timeline_cards.py`)

### 10.1 Principe

Le **code** génère les cartes à partir du JSON, sans LLM. Elles sont stockées comme objets
`{id, type, ref, front, back, media[]}`, avec un `id` stable dérivé d'un hash de
`(type, ref, contenu)`. On les prévisualise dans le même rendu que l'onglet **Cartes** actuel, on
peut les désactiver une par une, et on les exporte avec `tsv_bytes` (mêmes `ANKI_HEADER_LINES` et
colonnes `deck, recto, verso`, pour ne rien casser).

### 10.2 Types de cartes (cases à cocher, les trois premiers actifs par défaut)

| Type | Recto | Verso | Règles |
|---|---|---|---|
| `event_to_date` | « En quelle année : {libellé} ? ». L'interrogatif suit la précision : *En quelle année / En quel mois / À quelle date / Dans quelle décennie / Au cours de quel siècle* | date formatée (style date) + description | un par évènement `origin=text` |
| `date_to_event` | « {date} — {piste} : que se passe-t-il ? » | libellé(s) + description | **les évènements de même date et même piste sont regroupés** en une carte, pour éviter une question ambiguë ; ignoré pour les précisions ≥ siècle |
| `period_bounds` | « Bornes de la période : {libellé} ? » | « 1944–1971 » + description | un par période |
| `ordering` | « Classez chronologiquement : B · D · A · C » | `<ol>` dans l'ordre, avec les dates | groupes de 3 à 5 évènements consécutifs d'une piste, mélange **déterministe** (graine = ids) |
| `neighbors` | « Dans {piste}, qu'est-ce qui précède / suit {libellé} ? » | libellé + date | optionnel |
| `whole_image` | « Frise : {titre} — retrouver les grandes étapes » | image PNG de la frise entière | optionnel |
| `masked_image` | la frise **recadrée autour de l'évènement**, son étiquette remplacée par « ? » sur fond surligné | la même vue avec l'étiquette révélée et surlignée + description | optionnel ; importance ≥ 2 ; au plus 30 par frise |

### 10.3 Images des cartes

- Les variantes masquées se rendent **depuis la display list** : on filtre ou on remplace les
  primitives `event-label` et `event-date` dont le `ref` correspond. La mise en page ne change pas,
  donc la position de l'étiquette cachée reste identique.
- Le recadrage se fait sur une fenêtre de ±450 px autour du `x` de l'évènement, en conservant la
  gouttière des libellés de pistes et l'axe. Le rendu fait environ 1000 px de large pour rester
  lisible sur téléphone.
- **Nommage** : `ag_<project>_tl_<timeline>_<ref>_<sha1[:10]>.png`, ou `ag_tl_<timeline>_…` pour
  une frise sans projet. Le **hash du contenu dans le nom** est indispensable :
  `collection.media` est un espace plat et global, et Anki ne voit pas qu'un fichier a changé s'il
  garde le même nom.
- Les images sont écrites dans `MEDIA_DIR/<project_id>/`, ou `MEDIA_DIR/_timelines/<timeline_id>/`.
  Elles sont ajoutées au ZIP (`media/…`) et au flux « copier dans collection.media »
  (`copy_media`, choix explicite du profil Anki, comme aujourd'hui).

### 10.4 HTML, deck et stabilité

- Le style des dates, œuvres et concepts vient **d'une seule constante**, alignée sur
  `skill_templates/fr.md` (date en rouge, gras, souligné). Elle sera remplaçable plus tard par les
  balises sémantiques du plan d'agent local.
- **Assainissement TSV** : aucun `\t` ni `\n` ne subsiste dans un champ (les retours à la ligne
  deviennent `<br>`) et tout le HTML est échappé. C'est exactement la classe de bugs que le plan
  d'agent local veut éliminer.
- **Deck** : le deck de la portée (chunk, préfixe de chapitre ou préfixe du projet) suivi de
  `::<sous-deck>`. Le sous-deck vaut par défaut « Chronologie » ou « Timeline » selon la langue
  **du document**, puis il est **figé** dans la frise. On ne le traduit jamais à la volée, pour la
  même raison que `DEFAULT_DECK_NAME` dans `project_store.py` : un même projet exporté dans deux
  langues créerait deux decks.
- **Réimport** : le recto est déterministe, donc un réimport après modification met à jour les
  notes au lieu de les dupliquer (Anki compare le premier champ). À expliquer dans l'aide.
- **Intégration à l'export du projet** : une case « Inclure les cartes des frises liées » dans la
  modale d'export existante, **désactivée par défaut**. `export_rows` ajoute alors les lignes et les
  médias des frises. Les tests d'export existants doivent rester verts sans modification.

---

## 11. Stockage (`timeline_store.py`)

- `paths.TIMELINES_DIR = DATA_DIR / "timelines"`, ajouté à `ensure_dirs()`.
- **Jamais dans `projects/`** : `list_projects()` prend tous les `*.json` de ce dossier pour des
  projets.
- Un fichier `timelines/<timeline_id>.json` :

```jsonc
{
  "version": 1,
  "id": "mondialisation-3f9a",
  "created_at": "…", "updated_at": "…",
  "source": { "kind": "project" | "chapter" | "chunk" | "text" | "import",
              "project_id": "…", "deck_path": "…", "chunk_ids": [3, 4, 5],
              "text_hash": "sha1…" },
  "source_text": "…",                 // instantané (§6.1)
  "extraction": { "mode": "strict" | "enriched", "strategy": "single" | "per_chunk",
                  "per_chunk": { "3": { "status": "ok" | "error" | "empty", "raw": "…" } } },
  "data": { /* document ankigen.timeline/1 normalisé */ },
  "raw_responses": [ /* 5 derniers collages bruts, pour audit */ ],
  "render_options": { … }, "card_options": { … }, "cards_deck": "…::Chronologie",
  "disabled_cards": ["…"]
}
```

- Identifiant : slug du titre suivi de 4 caractères hexadécimaux. Validé par
  `^[a-z0-9][a-z0-9_-]{0,63}$` avant **tout** accès disque (pas de traversée de chemin).
- **Écriture atomique** : fichier temporaire, puis `os.replace`.
- **Suppression d'un projet** : ses frises survivent, puisqu'elles sont autonomes. L'UI affiche
  « source supprimée » et désactive ce qui dépend du projet (re-extraction). On les supprime depuis
  le tableau de bord.

---

## 12. Routes et API (dans `app.py`, modules `timeline_*` importés dans les routes, §15)

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/timeline/<tid>` | page frise |
| POST | `/timeline/new` | création depuis `{scope: {kind, project_id, deck_path, chunk_ids}}`, `{text, title, lang}` ou `{json}` → redirection ou `{ok, id}` |
| POST | `/timeline/<tid>/delete` | suppression |
| GET | `/api/timelines` | liste (tableau de bord) |
| GET | `/api/timeline/<tid>` | document + rapport de validation + options |
| POST | `/api/timeline/validate` | validation à blanc `{raw}` → rapport (§4.3) |
| POST | `/api/timeline/<tid>` | enregistrement `{data}` ou `{raw}` (+ `chunk_id` en mode paragraphe par paragraphe) → validation, fusion éventuelle, sauvegarde |
| GET | `/api/timeline/<tid>/prompt` | prompt d'extraction (`?chunk_id=`, `?mode=`) |
| GET | `/api/timeline/<tid>/correction-prompt` | prompt de correction du dernier collage |
| POST | `/api/timeline/<tid>/render` | `{data?, options}` → `{svg, width, height, warnings, stats}`. Alimente l'aperçu : on y envoie le document **non enregistré** en cours d'édition |
| GET | `/export/timeline/<tid>.<fmt>` | `svg`, `png`, `jpeg`, `webp`, `pdf`, `json`, avec les options en query. Passe par `_with_export_headers` |
| POST | `/api/timeline/<tid>/cards` | aperçu des cartes avec `card_options` |
| GET | `/export/timeline/<tid>/cards.tsv` et `cards.zip` | export des cartes (+ médias) |
| POST | `/api/timeline/<tid>/anki-media` | copie des médias dans un `collection.media` choisi (même contrôle `allowed` que la route existante) |

Réponses au format existant (`jsonify(ok=True, …)`, erreurs avec `tr(...)`). Limites : 2 Mo par
document, 200 000 caractères de texte source.

---

## 13. Interface

### 13.1 Page frise (`templates/timeline.html`, `static/timeline.js`, styles dans `style.css` ou `static/timeline.css`)

Même charpente que la vue de travail (`shell--fixed`, rail, panneaux, dock) :

- **Rail gauche** : l'éditeur structuré.
  - Sections repliables **Pistes** (renommer, couleur, réordonner par glisser-déposer ou flèches
    au clavier), **Ères**, **Périodes**, **Évènements**. Les évènements sont regroupés par piste et
    triés par date.
  - Chaque ligne montre la date courte, le libellé et des badges : importance, ⚠ non vérifié,
    ✦ hors cours, ① renvoyé en note.
  - Un clic ouvre un **tiroir d'édition** (champs du §4.2, date avec aide au format et aperçu
    formaté en direct). Bouton **Ajouter**.
  - En mode paragraphe par paragraphe, une section **Sources** liste les chunks de la portée avec
    leur état.
- **Panneau principal, onglets** :
  - **Frise** : aperçu SVG en ligne, zoom (Ctrl + molette, boutons), déplacement, bouton
    « Ajuster », choix du thème et de la densité. Au survol, une infobulle montre la date complète,
    la description, `date_text` et la citation. Un clic sélectionne l'élément dans le rail.
    Rafraîchissement anti-rebond de 250 ms après chaque édition.
  - **JSON** : zone monospace (13 px, `design.md`), bouton Valider. Les erreurs sont listées avec
    leur chemin, et un clic place le curseur à l'endroit fautif.
  - **Prompt** : le prompt d'extraction et le bouton Copier. Après un collage invalide, le prompt
    de correction.
  - **Cartes** : les options, puis l'aperçu des cartes rendu comme l'onglet Cartes actuel, avec un
    interrupteur par carte.
- **Panneau d'avertissements** : validation, chevauchements évités (« 7 étiquettes renvoyées en
  notes »), doublons probables, citations introuvables.
- **Dock (toujours visible)** : Copier le prompt · Coller le JSON · **Valider et enregistrer**
  (Ctrl + Entrée, CTA accent) · Exporter ▾ · Cartes ▾.
- Garde de sortie si des modifications ne sont pas enregistrées.

### 13.2 Ailleurs

- `work.html` : le bouton **Frise** et le sélecteur de portée (§2.1).
- `upload.html` : la section **Frises** et la modale **Nouvelle frise**.
- `help.html` : une section « Frises chronologiques » (flux, format JSON, schéma téléchargeable,
  modèle de Skill frise, réimport des cartes, limites).
- Modale d'export du projet : la case « Inclure les cartes des frises liées » (§10.4).

### 13.3 Qualité d'interface

- `design.md` en entier : pas de bordures, rayons, ombres, cibles de 40 px minimum, mouvements
  avec `--ease`, mode sombre complet.
- Accessibilité : navigation au clavier dans le rail et le tiroir, `aria-*` sur les onglets,
  anneaux de focus, SVG avec `role="img"`, `<title>` et `<desc>`. L'information ne passe jamais
  par la seule couleur.
- Fenêtre minimale de Tauri : 800 × 600. Tout doit rester utilisable à cette taille (rail
  repliable).
- Toutes les chaînes passent par `window.T("timeline.…")`.

---

## 14. Fichiers

**Nouveaux**

| Fichier | Contenu |
|---|---|
| `timeline_dates.py` | analyse, intervalles, arithmétique, formatage des dates |
| `timeline_schema.py` | constantes, validation, normalisation, rapport |
| `timeline_layout.py` | mise en page pure, display list, `check_layout` |
| `timeline_render_svg.py` | moteur SVG |
| `timeline_render_raster.py` | moteur Pillow : PNG, JPEG, WebP, PDF |
| `timeline_prompt.py` | texte source par portée, prompts d'extraction et de correction |
| `timeline_extract.py` | `TimelineExtractor`, `ManualExtractor`, nettoyage des réponses |
| `timeline_merge.py` | fusion paragraphe par paragraphe, dédoublonnage |
| `timeline_cards.py` | génération des cartes, variantes image |
| `timeline_store.py` | persistance dans `DATA_DIR/timelines/` |
| `prompt_templates/timeline_extract.fr.md`, `.en.md` | prompts d'extraction versionnés |
| `skill_templates/timeline/fr.md`, `en.md` | modèle de Skill frise (optionnel) |
| `static/schemas/timeline-v1.json` | JSON Schema |
| `static/fonts/Inter-Regular.ttf`, `Inter-SemiBold.ttf`, `OFL.txt` | police embarquée |
| `templates/timeline.html`, `static/timeline.js` (+ `static/timeline.css` si besoin) | UI |
| `tests/fixtures_timeline/*.json` | fixtures texte (§16.2) |
| `tests/test_timeline_*.py`, `tests/test_timeline_ui.js` | tests |
| `scripts/timeline_gallery.py` | galerie de rendus pour la revue visuelle |

**Modifiés** : `app.py`, `paths.py`, `project_store.py` (option d'export des cartes de frise
seulement), `templates/work.html`, `templates/upload.html`, `templates/help.html`,
`static/app.js`, `static/style.css`, `locales/en.json`, `locales/fr.json`, `runtime_probe.py`
(sondes de la frise), `scripts/build_app_payload.py` (`DATA_DIRS`), `README.md`,
`README.fr.md`, `CONTRIBUTING.md` (tableau de l'arborescence).

---

## 15. Packaging et mises à jour

Le dépôt a un **contrat de runtime** (PR `chore(build)` : `scripts/build_app_payload.py`,
`scripts/runtime_contract.py`, `runtime_probe.py`, `runtime.json`). Lis ces fichiers et la section
*Conventions* de `CONTRIBUTING.md` avant la phase 0. En résumé :

- **Rien n'est listé à la main.** Le contenu d'app.zip et de l'`app_bundle` de l'exe est calculé
  à partir des imports réels depuis `app.py` et `launcher.py`, imports placés dans des fonctions
  compris. Un nouveau module `timeline_*.py` est embarqué dès qu'une route l'importe. Ne touche ni
  à `flask-server.spec` ni aux workflows.
- **Un nouveau dossier de données** n'est atteint par aucun import. Ajoute
  `prompt_templates/` à `DATA_DIRS` dans `scripts/build_app_payload.py`, et ajoute un cas au test
  `tests/test_build_payload.py`. Ce qui vit dans `static/`, `templates/`, `locales/` et
  `skill_templates/` est déjà couvert, d'où le schéma et les polices dans `static/`.
- **L'exécutable embarque toute la bibliothèque standard et tous les sous-modules des
  dépendances.** `difflib`, `unicodedata`, `PIL.ImageDraw`, `PIL.ImageFont`, FreeType
  (`_imagingft`), les plugins PDF et WebP sont déjà présents dans tout exécutable de runtime ≥ 1.
  La frise **n'ajoute aucune dépendance** : donc pas de `--bump`. S'il te semble qu'il en faut
  une, arrête-toi et demande-moi (§1.2).
- **Les exécutables plus anciens n'ont pas à être gérés.** Un exe antérieur au contrat vaut
  runtime 0. L'updater ne lui livre plus de code qui exige le runtime 1 : il propose
  l'installateur. **Aucun code de dégradation** (formats raster désactivés, message
  « installateur requis » propre à la frise…) n'est donc à écrire. Les imports des modules
  `timeline_*` restent placés **dans les routes** pour une autre raison : une frise cassée ne
  doit jamais empêcher l'app de démarrer.
- **Déclare ce dont la frise a besoin dans `runtime_probe.py`.** Un import réussi ne prouve pas
  que FreeType rend du texte ou que l'encodeur PDF marche. Ajoute des sondes, par exemple
  `timeline_raster` : charger `static/fonts/Inter-Regular.ttf` avec `ImageFont.truetype`,
  mesurer et dessiner du texte accentué, `save` en PNG, JPEG, WebP et PDF. La CI les exécute sur
  l'exe neuf (`flask-server.exe --self-check`) **et** sur l'exe de la release précédente avec le
  nouveau code (`scripts/check_runtime_compat.py`).
- **Vérifie localement** : `pyinstaller --noconfirm flask-server.spec`, puis
  `dist\flask-server.exe --self-check`. Lance ensuite l'exe et appelle les routes d'export PNG,
  PDF et SVG (§17, phase 5).

---

## 16. Tests

### 16.1 Tests unitaires (`unittest`)

- **`test_timeline_dates.py`** : tous les formats ; années négatives ; absence d'an 0 ; bissextiles
  (y compris négatives) ; jours invalides ; précisions ; bornes `t0` et `t1` ; fin inclusive ;
  `present` ; siècle ambigu ; formatage fr/en pour chaque ligne du tableau §5.4 ; tri stable.
- **`test_timeline_schema.py`** : fixtures valides ; un cas par code d'erreur et d'avertissement,
  avec vérification du chemin JSON Pointer ; tolérances (clôtures, prose autour, BOM, année en
  nombre) ; clés inconnues ; couleurs malicieuses (`red;}</style><script>`) refusées ; limites ;
  concordance avec `static/schemas/timeline-v1.json`.
- **`test_timeline_layout.py`** :
  - zéro violation de `check_layout` sur toutes les fixtures, dans les deux densités et en largeur
    fixe comme automatique ;
  - **fuzz** : 300 documents aléatoires (`random.Random(seed)`, 1 à 12 pistes, 0 à 150 évènements,
    dates groupées ou étalées, libellés de 1 à 80 caractères, unicode), zéro violation et
    déterminisme ; en cas d'échec, le message donne la graine ;
  - I6 (position exacte des marqueurs) et I7 (aucun élément perdu) ;
  - partitionnement des périodes : nombre de rangées = clique maximale d'intervalles qui se
    chevauchent ;
  - ruptures d'axe : présentes sur la fixture « long vide », absentes si `off`, jamais dans une
    période ;
  - performance : 400 évènements en moins de 2 s dans la CI (le budget réel est de 300 ms en local).
- **`test_timeline_render.py`** : SVG bien formé (`xml.etree.ElementTree`) ; texte échappé ; un
  `data-ref` par élément ; `<desc>` complet ; PNG aux bonnes dimensions ; JPEG sans alpha ; PDF
  qui commence par `%PDF` ; WebP seulement si disponible (`skipUnless`) ; plafond de surface
  respecté.
- **`test_timeline_prompt.py`** : texte source par portée (chunk, préfixe de deck, cours) ;
  présence du contrat et de l'exemple ; mode strict ou enrichi ; prompt de correction qui liste
  toutes les erreurs.
- **`test_timeline_merge.py`** : collisions d'`id`, fusion des pistes, doublons, citations
  conservées, déterminisme.
- **`test_timeline_quotes.py`** : correspondance exacte, floue et introuvable ; normalisation des
  apostrophes et guillemets.
- **`test_timeline_cards.py`** : chaque type ; regroupement par date ; mélange déterministe ;
  absence de `\t` et `\n` ; en-tête Anki ; noms de médias avec hash ; deck figé ; variante masquée
  sans l'étiquette cachée dans la display list.
- **`test_timeline_store.py`** : CRUD ; écriture atomique ; ids malicieux (`../x`) refusés ;
  **`list_projects()` ignore les frises**.
- **`test_build_payload.py`** (existant, à compléter) : `prompt_templates/` est copié dans le
  payload et les modules `timeline_*` y figurent.
- **`test_runtime_contract.py`** (existant) : il reste vert, sans `--bump`. Les nouvelles sondes
  de `runtime_probe.py` passent dans l'environnement de dev.
- **`test_i18n.py`** : parité (déjà en place, doit rester verte).
- **`tests/test_timeline_ui.js`** (`node --test`, même approche que `test_update_ui.js`) : les
  helpers purs du JS (anti-rebond, sérialisation de l'éditeur, placement du curseur sur un chemin
  JSON).

### 16.2 Fixtures (`tests/fixtures_timeline/`)

`mondialisation.json` (ESH, 3 pistes, ères, périodes, ~25 évènements) · `antiquite.json`
(av. J.-C., siècles, `approx`) · `dense_1945.json` (15 évènements entre 1944 et 1946 dans une
piste) · `same_date.json` · `single_event.json` · `only_periods.json` · `long_gap.json`
(−3000, puis 1789–1815) · `present.json` · `twelve_tracks.json` · `long_labels.json` (80
caractères, accents, `<>&"'`) · `short_span_days.json` (crise de 2008, graduations en jours) ·
`invalid/*.json` (un fichier par erreur).

### 16.3 Revue visuelle

`scripts/timeline_gallery.py` rend chaque fixture en SVG et en PNG, dans chaque thème, vers
`exports/gallery/`. **Tu dois regarder les PNG** (en les ouvrant avec l'outil de lecture d'images)
avant de déclarer une phase de rendu terminée, et joindre une planche de captures aux PR. Tu
règles les valeurs par défaut du §7.2 sur ces rendus.

---

## 17. Livraison par phases (une PR par phase)

| Phase | Contenu | Critères d'acceptation |
|---|---|---|
| **0. Spike + spec** | Rendu de texte Pillow + Inter dans le venv **et** dans l'exe gelé (sonde `runtime_probe` + `flask-server.exe --self-check`) ; `window.print()` et `ClipboardItem` dans WebView2 ; spec `docs/superpowers/specs/2026-09-28-timeline-design.md` et plan `docs/superpowers/plans/2026-09-28-timeline.md` | spec et plan validés par moi ; résultats des spikes consignés dans la spec |
| **1. Contrat** | `timeline_dates`, `timeline_schema`, `timeline_store`, schéma JSON, `paths` | tests §16.1 correspondants verts |
| **2. Mise en page + SVG** | `timeline_layout`, `check_layout`, `timeline_render_svg`, galerie, polices | zéro violation (fixtures + fuzz), galerie revue, captures dans la PR |
| **3. Page frise** | création depuis JSON ou texte, aperçu, onglet JSON, rail éditeur, tableau de bord | parcours « importer un JSON → éditer → voir la frise » vérifié dans l'app (outils de preview), captures clair et sombre |
| **4. Extraction** | portées depuis la vue de travail, prompts, correction, paragraphe par paragraphe, fusion, vérification des citations | parcours complet sur le projet `CH1_ La dynamique de la mondialisation…` : prompt copié, JSON collé, frise obtenue |
| **5. Exports** | raster, PDF, modale d'options, presse-papiers, sondes `runtime_probe` (§15) | exports vérifiés dans l'app **et sur l'exe gelé** ; `--self-check` vert |
| **6. Cartes** | `timeline_cards`, images et variantes masquées, TSV, ZIP, `collection.media`, option dans l'export du projet | import réel dans Anki d'un ZIP de test (captures) ; tests d'export existants intacts |
| **7. Finition** | aide, README en/fr, CONTRIBUTING, accessibilité, performance, textes | relecture complète en fr et en en, suite verte |
| **8. (optionnel)** | orientation verticale, flèches `links`, PDF multipage découpé dans le temps, export HTML interactif, PDF vectoriel si la phase 0 l'a validé | à spécifier séparément |

---

## 18. Hors périmètre v1

- Temps géologique (millions d'années) et calendriers non grégoriens. **Aucune conversion
  julien → grégorien**, à dire dans l'aide.
- Appels directs à une API de LLM. L'app reste sans clé ; l'agent local se branchera sur
  `TimelineExtractor`.
- Édition collaborative, synchronisation, cloud.
- Placement d'images à l'intérieur de la frise.
- Retouche graphique libre (glisser une étiquette à la main). Envisageable plus tard sous forme de
  « surcharges » de placement stockées dans `render_options`, à condition que `check_layout` les
  accepte.

---

## 19. Définition de « terminé » (globale)

- Toutes les phases 0 à 7 sont fusionnées et la suite `unittest` et `node --test` est verte.
- Aucune fixture ni aucun cas de fuzz ne produit de chevauchement. La galerie a été revue.
- Les parcours du §2.3 ont été vérifiés dans l'app, avec captures à l'appui.
- Les exports fonctionnent dans l'exe packagé, et `flask-server.exe --self-check` passe avec les
  sondes de la frise. `runtime.json` n'a pas bougé.
- Chaque chaîne est traduite en fr et en en. Le mode sombre est complet. `design.md` est respecté.
- Aucune nouvelle dépendance runtime n'a été ajoutée sans mon accord explicite.

---

## 20. Méthode de travail attendue

1. **Lis** tous les fichiers du §1.1. Ne propose rien qui contredise une convention existante sans
   le dire explicitement.
2. **Rédige la spec et le plan** (phase 0) dans `docs/superpowers/specs/` et
   `docs/superpowers/plans/`, dans le format des documents qui s'y trouvent déjà. Pour chaque
   **Décision** de ce prompt, confirme-la ou propose mieux, avec la raison. Pose-moi **seulement**
   les questions qui bloquent réellement.
3. **Code phase par phase**. Tests d'abord pour les modules purs (dates, schéma, mise en page).
   Commits petits, en anglais et en Conventional Commits. Commentaires en français.
4. **Vérifie ce que tu livres** : lance l'app avec les outils de preview, parcours les flux, ouvre
   les exports produits et regarde-les. N'annonce jamais « ça marche » sans l'avoir vu.
5. À la fin de chaque phase, écris un **compte rendu court** : ce qui est fait, ce qui a été
   vérifié et comment, les écarts par rapport au plan et pourquoi, et ce qui reste.
