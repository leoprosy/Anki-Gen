# Ankigen — Rendre l'application publiable en open source

Date : 2026-09-13
Répond à [issue #4](https://github.com/leoprosy/Anki-Gen/issues/4)
Branche : `feat/open-source-readiness`, depuis `main` (`b8e58c1`)

## Contexte

`Anki-Gen` transforme un cours `.docx` en paquet Anki en gardant l'humain dans la boucle :
le document est découpé en chunks selon les styles de titre, chaque chunk est copié dans
Claude, la réponse TSV est recollée dans l'application, puis exportée pour Anki.

L'architecture actuelle sur `main` :

```
launcher.py       Entrée WSGI (Waitress) + bootstrap %APPDATA% + sidecar Tauri
app.py            Routes Flask
paths.py          Résolution APP_DIR / DATA_DIR / UPLOAD / PROJECTS / MEDIA / EXPORT
parse_cours.py    Parsing .docx → chunks (+ SYSTEM_PROMPT)
docx_blocks.py    Itération des blocs (titres, texte, images, tableaux)
media_store.py    Extraction et nommage des images (SHA-1)
render.py         Rendu prompt texte / aperçu HTML / résolution des placeholders
project_store.py  Format projet v2, migration v1, export, copie médias
build_anki_csv.py Parsing TSV des réponses + en-tête Anki
updater.py        Auto-update depuis GitHub Releases
templates/        base.html, upload.html, work.html
static/           style.css, app.js
```

L'application est taillée pour un seul utilisateur : nom « Anki ESH », interface
exclusivement française avec chaînes en dur côté serveur **et** côté JavaScript, préfixe de
deck `*ESH*` codé en dur à quatre endroits, `SYSTEM_PROMPT` spécifique à la prépa ECG
embarqué dans le parseur et exposé par un bouton « copier le prompt système ».

Objectif : rendre l'application utilisable par quelqu'un qui n'est ni francophone ni
étudiant en ESH, sans casser les installations existantes ni le canal de mise à jour.

## Périmètre

Dans le périmètre :

1. Renommage produit vers « Ankigen »
2. Internationalisation anglais / français, anglais par défaut
3. Suppression du préfixe de deck par défaut, rendu configurable
4. Logo SVG et identité visuelle
5. Panneau de paramètres (langue, dossier de téléchargement, préfixe de deck)
6. Remplacement du prompt système par une page « How to use » décrivant le flux et la
   création du Skill Claude
7. Correction des manifestes de packaging, aujourd'hui incomplets

Hors périmètre :

- Migration de l'identifiant Tauri (`ankiesh`) et du dossier de données `%APPDATA%/AnkiGen`
- Refonte visuelle au-delà du logo
- Régénération des icônes `.ico` / `.png` de l'application (le SVG sert de source, la
  rastérisation pourra suivre)

## Décisions de conception

### 1. Identité « Ankigen »

Le renommage ne touche **que les surfaces visibles** : le `<title>` et la marque de
`templates/base.html`, `productName` et le titre de fenêtre dans `tauri.conf.json`, l'écran
d'attente généré par `scripts/generate-dist-tauri.js`, le README, `package.json`, et les
docstrings des modules Python.

Restent inchangés, volontairement :

| Élément | Raison |
|---|---|
| Identifiant Tauri `ankiesh` | Le changer crée une seconde installation au lieu de mettre à jour l'existante |
| `%APPDATA%/AnkiGen/` | Contient projets, uploads et médias des utilisateurs actuels |
| `ANKI_ESH_SIDECAR` | Contrat entre `src-tauri/src/lib.rs` et `launcher.py` ; le renommer des deux côtés n'apporte rien et ajoute un risque de désynchronisation |
| `GITHUB_REPO = "leoprosy/Anki-Gen"` | L'URL du dépôt et les releases déjà publiées |

**Logo.** `base.html` déclare une bibliothèque de symboles SVG en tête de document, dont
`#i-logo` — actuellement un pictogramme « tableau » générique repris de Feather. On y
substitue une marque propre : deux cartes arrondies décalées (recto/verso, la métaphore
flashcard) dont celle du dessus porte une étincelle de génération. Contours en
`currentColor` pour hériter du contexte, un seul aplat en `var(--accent)`.

Le même dessin est dupliqué en fichier autonome `static/logo.svg`, qui sert de source au
README et à une future rastérisation des icônes. C'est la seule duplication acceptée du
projet, et elle est signalée en commentaire des deux côtés : le symbole inline évite une
requête réseau sur le chemin critique, le fichier autonome est nécessaire hors HTML.

Contrainte : rester lisible à 22 px (taille dans la barre) comme à 256 px.

### 2. Socle de réglages — `settings.py`

Nouveau module, seul responsable de la persistance des préférences. Il s'appuie sur
`paths.DATA_DIR` et n'importe ni Flask ni `i18n`.

Emplacement : `DATA_DIR/settings.json` — à côté de `projects/`, `uploads/`, `media/` et
`exports/`, donc hors de `app/` qui est écrasé à chaque mise à jour.

| Clé | Type | Défaut |
|---|---|---|
| `language` | `"en"` ou `"fr"` | `"en"` |
| `download_dir` | chemin | `~/Downloads` s'il existe, sinon `paths.EXPORT_DIR` |
| `deck_prefix` | chaîne | `""` |

Interface publique :

- `load_settings() -> dict` — fusionne le fichier avec les défauts, valide chaque clé,
  ignore les clés inconnues
- `save_settings(partial: dict) -> dict` — fusionne dans l'existant, écrit atomiquement
  (fichier temporaire dans le même dossier + `os.replace`), retourne l'état complet

**Robustesse.** Un `settings.json` absent, illisible ou contenant un JSON invalide produit
les valeurs par défaut sans lever d'exception : une préférence corrompue ne doit jamais
empêcher l'application de démarrer. Une valeur individuelle invalide (langue inconnue, type
inattendu) retombe sur son défaut, les autres clés sont conservées.

**Cas particulier de `download_dir`.** Le module **stocke le chemin tel que l'utilisateur
l'a saisi** dès lors que c'est une chaîne non vide, y compris s'il ne pointe nulle part.
Réécrire silencieusement le réglage vers le défaut ferait disparaître une saisie sans
explication — l'utilisateur retrouverait un champ qu'il n'a pas rempli. La vérification
d'utilisabilité est séparée : `resolve_download_dir()` retourne un dossier écrivable ou
`None`, et c'est l'export qui décide quoi faire d'un `None` (section 5). Le réglage garde
donc la saisie, l'export dégrade proprement, et la page de réglages affiche à la demande
si le dossier est atteignable.

**Surface HTTP.** `GET /api/settings` et `POST /api/settings` (JSON partiel), plus la page
`GET /settings` rendue par un nouveau template `settings.html`, accessible depuis la barre.
La page propose pour `download_dir` un champ texte avec bouton « valider » qui affiche si le
dossier existe et est accessible en écriture — un sélecteur de dossier natif n'est pas
disponible depuis une page web, et l'inventer par un `<input type="file" webkitdirectory>`
donnerait un chemin inutilisable côté serveur.

### 3. Internationalisation — `i18n.py` + `locales/`

**Approche retenue : traduction côté serveur.** Les templates sont déjà rendus par Jinja ;
une solution serveur n'ajoute aucune étape de build ni dépendance. Alternatives écartées :
Flask-Babel (fichiers `.po` à compiler, lourd pour deux langues) et un i18n purement
JavaScript (flash de texte non traduit au chargement, et duplication des chaînes déjà
connues du serveur).

- `locales/en.json` et `locales/fr.json` : dictionnaires plats, clés en `snake_case`
  namespacées par écran (`upload.title`, `settings.language_label`, `help.step_export`,
  `work.cards_detected`)
- `i18n.py` : `translate(key, lang, **params) -> str`, interpolation par `str.format`.
  Clé absente de la locale demandée → repli sur l'anglais ; absente des deux → la clé
  elle-même est retournée (visible en développement, jamais une page cassée)
- Un context processor Flask injecte `t` et `lang` ; `<html lang="{{ lang }}">` suit le
  réglage

**Surfaces à traduire**, toutes concernées :

| Surface | Traitement |
|---|---|
| `templates/*.html` | `{{ t('...') }}` |
| `static/app.js` (579 lignes, toasts et libellés en dur) | `base.html` sérialise le sous-ensemble utile dans `window.__I18N__` ; le JS lit `T('key')` |
| Script inline de `base.html` (bandeau de mise à jour) | Même mécanisme `window.__I18N__` |
| Messages d'erreur JSON de `app.py` | Traduits avant sérialisation |
| `LISEZ-MOI.txt` de `export.zip` | Contenu traduit, nom de fichier `README.txt` en anglais et `LISEZ-MOI.txt` en français |

Pas de second mécanisme de traduction : tout passe par `i18n.py`.

**Messages de l'updater.** `updater.py` retourne aujourd'hui des messages français dans son
dict de résultat (« Déjà à jour. », « Pas de connexion réseau. »). Il retournera une **clé**
(`message_key`) et ses paramètres éventuels ; la traduction se fait dans `app.py`, qui
connaît la langue. `updater.py` reste ainsi sans dépendance à l'i18n et testable seul.

### 4. Préfixe de deck configurable

Le défaut passe de `"*ESH*"` à `""`. Ce n'est pas qu'un changement de valeur : quatre
endroits supposent un préfixe non vide.

| Emplacement | Problème | Correction |
|---|---|---|
| `parse_cours.build_deck_path` | `"::".join([prefix] + titres)` produit `"::Chapitre"` — deck Anki invalide | Filtrer les segments vides avant jointure |
| `parse_cours.parse_docx`, garde `flush` | `deck != deck_prefix` est une façon détournée de dire « on est entré dans au moins une section » ; devient faux dans les mauvais cas avec un préfixe vide | Tester explicitement que la pile hiérarchique n'est pas vide |
| `project_store.list_projects` | Repli `or "ESH"` | Repli sur une clé traduite `project.untitled_deck` |
| `project_store.export_rows` | Repli `or "ESH"` | Idem |

Côté interface, le champ de `upload.html` est pré-rempli depuis `settings["deck_prefix"]`,
n'est plus `required`, et porte un placeholder d'exemple. Le défaut de `app.py:upload`
(`or "*ESH*"`) devient le réglage. L'argument CLI `--deck-prefix` de `parse_cours.py` passe
à `""`.

Les projets existants ne sont pas touchés : le préfixe est figé dans le champ `deck` de
chaque prompt et dans `deck_prefix` au niveau du projet.

### 5. Export vers le dossier configuré

Comportement retenu : **écriture dans le dossier configuré ET téléchargement navigateur**.

`export_tsv` écrit déjà une copie dans `paths.EXPORT_DIR` ; cette copie va désormais dans
`settings["download_dir"]`. `export_zip`, qui n'écrivait aucune copie, en écrit une aussi —
sans quoi le réglage aurait un effet sur un bouton d'export et pas sur l'autre.

Les deux réponses portent un en-tête `X-Export-Path` avec le chemin absolu écrit. Les
boutons d'export de `work.html` passent d'un `<a href>` à un `fetch` : lecture de l'en-tête,
téléchargement depuis le blob, puis toast « Exporté vers <chemin> » via le `window.toast`
déjà en place.

**Dégradation.** Si le dossier est inaccessible (supprimé, sans droits, disque amovible
débranché), l'écriture est abandonnée, le téléchargement a lieu quand même, et
`X-Export-Path` porte une valeur d'erreur que le JS affiche en avertissement. Un réglage
invalide ne doit jamais faire échouer un export.

### 6. Suppression du prompt système, page « How to use »

`SYSTEM_PROMPT` disparaît de `parse_cours.py`, le champ `system` disparaît de
`build_prompts`, et l'import dans `app.py` ainsi que la variable `system_prompt` passée à
`work.html` sont retirés.

C'est une **suppression de fonctionnalité visible** : le bouton « copier le prompt système »
de `work.html` (`#copy-system-btn`, géré dans `app.js`) disparaît. C'est voulu — le flux de
travail repose désormais sur un Skill Claude côté utilisateur, et un prompt ESH en français
embarqué dans l'application est exactement ce qui la rend inutilisable par quelqu'un d'autre.

Les projets existants qui contiennent encore un champ `system` restent lisibles : le champ
est simplement ignoré par `project_store.normalize`.

À la place, une page `/help` traduite (`help.html`), accessible depuis la barre :

1. **Ce que fait Ankigen** — un cours `.docx` structuré en paquet Anki, l'humain dans la
   boucle
2. **Le flux complet** — uploader le `.docx`, découpage en chunks selon les styles de titre,
   copier chaque chunk dans Claude, coller la réponse TSV, exporter, importer dans Anki
3. **Créer son Skill Claude** — ce qu'est un skill, structure de `SKILL.md`, frontmatter
   `name` / `description`, où le déposer
4. **Template de skill copiable** — point de départ générique : matière neutre, format de
   sortie TSV `QUESTION<TAB>RÉPONSE` imposé, règles de formatage HTML, et surtout la
   convention de placeholders `{{IMG:n}}` / `{{TABLE:n}}` que `render.resolve_placeholders`
   attend. Sans elle les images extraites du `.docx` ne peuvent pas atterrir dans les cartes.
5. **Importer dans Anki** — copie du dossier `media/`, puis Fichier → Importer ; séparateur,
   HTML et colonne de deck sont déjà déclarés dans l'en-tête du TSV

Le template générique sera raffiné à partir du skill ESH réel une fois celui-ci fourni,
comme exemple concret plutôt que comme contenu imposé.

### 7. Packaging — correction d'une régression existante

Les deux manifestes listent explicitement les fichiers applicatifs et **sont déjà en retard
sur `main`**, indépendamment de ce chantier :

- `flask-server.spec` : `datas=[('templates', 'templates'), ('static', 'static')]` — ne
  bundle plus aucun module Python sous `app_bundle/`, alors que `launcher.py` attend
  `sys._MEIPASS/app_bundle` pour son bootstrap
- `.github/workflows/release.yml` : la ligne `cp` construisant `app.zip` ne copie pas
  `paths.py`, `project_store.py`, `render.py`, `docx_blocks.py`, `media_store.py` — une
  mise à jour livrée par ce canal casserait l'installation

Les deux sont remis à jour avec la liste complète des modules, `settings.py`, `i18n.py` et
`locales/` inclus. C'est une correction adjacente et non un élargissement de périmètre :
sans elle, les fichiers ajoutés ici ne seraient pas livrés non plus. Elle est signalée
explicitement dans la PR.

## Architecture après changement

```
app.py            Routes Flask + traduction des messages updater
settings.py       (nouveau) préférences persistées ; dépend de paths, pas de Flask
i18n.py           (nouveau) résolution de clés ; aucune dépendance
locales/          (nouveau) en.json, fr.json
parse_cours.py    Parsing .docx (SYSTEM_PROMPT retiré)
updater.py        Mise à jour (messages devenus des clés)
templates/        base, upload, work, settings (nouveau), help (nouveau)
static/           style.css, app.js, logo.svg (nouveau)
```

`settings.py` et `i18n.py` sont indépendants l'un de l'autre et de Flask : des fonctions sur
fichiers, testables isolément. `app.py` est le seul point qui les relie.

## Tests

Une suite existe (`tests/test_docx_media.py`, avec `tests/make_fixtures.py`), bâtie sur
`unittest` de la bibliothèque standard — choix délibéré du dépôt, documenté dans l'en-tête
du fichier : la suite doit tourner sans dépendance supplémentaire. Les nouveaux tests
suivent ce même cadre ; on n'introduit pas pytest.

Commande de référence, vérifiée : `.venv/Scripts/python.exe -m unittest discover -s tests`
(38 tests au vert sur `b8e58c1`). L'interpréteur du venv est nécessaire — `python` sur le
PATH n'a ni `docx` ni `flask`.

On étend la suite sur les points où une régression serait silencieuse :

- `tests/test_settings.py` — défauts sur fichier absent ; JSON corrompu → défauts sans
  exception ; valeur individuelle invalide → défaut pour cette clé seulement ;
  `save_settings` partiel préserve les autres clés ; round trip
- `tests/test_i18n.py` — parité stricte des clés entre `en.json` et `fr.json` ; repli sur
  l'anglais quand une clé manque en français ; clé inconnue retournée telle quelle ;
  interpolation des paramètres
- `tests/test_deck_prefix.py` — préfixe vide ne produit jamais de deck commençant par `::` ;
  préfixe renseigné produit `Prefix::Chapitre::…` ; contenu antérieur au premier titre non
  émis dans les deux cas

Vérification manuelle avant PR, la suite ne couvrant pas l'interface : parcours complet
upload → travail → export dans les deux langues, bascule de langue, export avec un
`download_dir` volontairement invalide.

## Risques

| Risque | Traitement |
|---|---|
| Nouveaux fichiers absents du build frozen ou d'`app.zip` | Section 7 ; les deux manifestes repassés en revue avant la PR |
| Dérive entre `en.json` et `fr.json` | Test de parité des clés |
| Chaîne française oubliée en dur | Revue finale par `grep` d'accents sur `templates/`, `static/app.js` et les chaînes de `app.py` |
| Perte du prompt système sans remplacement clair | La page `/help` et son template de skill sont livrés dans le même lot, jamais après |
| Projets existants | `project_store.normalize` les migre déjà ; le champ `system` devient inerte, rien n'est supprimé sur disque |
