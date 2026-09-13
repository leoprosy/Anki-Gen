<img src="static/logo.svg" alt="" width="72" align="left" hspace="12">

# Ankigen

**Turn a `.docx` course into an Anki deck, one paragraph at a time.**

Ankigen est une application locale hybride (backend Flask en Python + frontend web encapsulé dans une app desktop Tauri) qui automatise la création de flashcards Anki à partir de cours au format `.docx`.

L'application découpe le document selon la hiérarchie de ses styles de titre, vous laisse envoyer chaque bloc à Claude pour en tirer des cartes Question/Réponse, puis exporte le tout au format attendu par Anki — images et tableaux compris.

L'interface est disponible en **anglais et en français** (anglais par défaut) ; la langue, le dossier d'export et le préfixe de deck se règlent dans **Paramètres**. La page **Mode d'emploi** décrit le flux complet et comment écrire son propre Skill Claude.

---

## 🛠️ Stack Technique

- **Backend :** Python (Flask), `python-docx` pour le parsing.
- **Frontend :** HTML, CSS natif, JavaScript Vanilla.
- **Application Desktop :** Tauri (Rust/Webview2).

---

## 🚀 Utilisation Courante (Développement)

Si vous voulez modifier le code ou lancer l'application rapidement sans la compiler :

1. **Lancer le backend web classique :**

   ```bash
   .venv/Scripts/python.exe app.py
   ```

   Rendez-vous ensuite sur `http://127.0.0.1:5000` dans votre navigateur.

2. **Lancer l'application Tauri en mode dev (Fenêtre native) :**
   ```bash
   npm run tauri dev
   ```
   _Note : Lancez d'abord le serveur Flask (`.venv/Scripts/python.exe app.py`) en arrière-plan, car Tauri en mode développement s'attendra à ce que le port 5000 soit actif._

---

## 📦 Compiler l'Application de Production (.exe)

Pour créer un installeur Windows autonome (qui n'a pas besoin de Python installé pour fonctionner), il faut compiler le backend Python en un binaire "sidecar" via PyInstaller, puis packager l'interface avec Tauri.

### 1. Compiler le Sidecar (Flask)

Dans le terminal (avec votre environnement virtuel Python activé) :

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm flask-server.spec
```

_Le fichier `flask-server.spec` versionné contient déjà les imports cachés nécessaires,
y compris ceux de Pillow (conversion et redimensionnement des images extraites du .docx).
L'équivalent en ligne de commande :_

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm --onefile --console --name flask-server launcher.py --add-data "templates;templates" --add-data "static;static" --hidden-import waitress --hidden-import flask --hidden-import jinja2.ext --hidden-import docx --hidden-import lxml --hidden-import lxml._elementpath --hidden-import lxml.etree --hidden-import PIL --hidden-import PIL._imaging
```

_Cela génère un fichier `dist/flask-server.exe`._

### 2. Placer le Sidecar pour Tauri

Copiez l'exécutable généré dans le dossier des binaires de Tauri en lui donnant le nom correspondant à la cible de compilation Windows :

```powershell
Copy-Item dist\flask-server.exe src-tauri\binaries\flask-server-x86_64-pc-windows-gnu.exe -Force
```

_(Remplacez `-gnu` par `-msvc` si vous utilisez la toolchain MSVC pour Rust)._

### 3. Compiler l'App Tauri

```bash
npm run tauri build
```

Vous trouverez les installeurs finaux `.exe` (NSIS) et `.msi` (Wix) dans le dossier :
`src-tauri/target/release/bundle/`

---

## 📖 Mode d'emploi de l'Application

La page **Mode d'emploi** de l'application reprend tout ceci, traduit, avec un template
de Skill Claude à copier.

1. **Import :** Sur l'écran d'accueil, sous « Nouveau cours », importez un `.docx` dont les
   titres utilisent de vrais styles de titre — c'est là-dessus que repose le découpage.
   Le préfixe de deck est optionnel (vide par défaut, réglable dans Paramètres).
2. **Parsing :** L'application découpe le cours et crée un projet sauvegardé localement.
3. **Génération via Claude :** Ankigen n'embarque plus de prompt système. Le flux suppose
   que vous disposez d'un **Skill Claude** dédié à l'écriture de cartes — la page Mode
   d'emploi explique comment l'écrire. Copiez ensuite le chunk courant et envoyez-le à
   Claude, qui répond au format TSV.
4. **Validation :** Collez la réponse dans la zone de texte (ou bouton « Coller »), et
   vérifiez le rendu dans l'onglet « Cartes ».
5. **Sauvegarde :** « Enregistrer & suivant » passe au paragraphe suivant.
6. **Exportation :** Le menu « Exporter » écrit le fichier dans votre dossier d'export
   configuré **et** le télécharge.

_(Vos projets sont persistants. Vous pouvez fermer l'application et reprendre vos cours en attente plus tard depuis le Dashboard)._

---

## 🖼️ Images et tableaux du .docx

Depuis la version 2 du format de projet, le parsing ne se limite plus au texte :
les **images** et les **tableaux** du document sont extraits et rejoignent les cartes.

### Images

- Chaque image est extraite dans `media/<projet>/`, sous un nom préfixé et dérivé
  de son SHA-1 (`ag_<projet>_<sha1>.png`). Une image répétée dans le cours n'est
  écrite qu'une fois. Le préfixe est indispensable : `collection.media` d'Anki est
  un espace de noms **plat et global**.
- Les formats qu'Anki ne sait pas afficher (emf, wmf, tiff, bmp…) sont convertis en
  PNG ; les images de plus de 1200 px de large sont réduites.
- Le **texte alternatif** du document (Word : « Texte de remplacement » ; Google Docs :
  « Texte alternatif ») est repris et envoyé à Claude avec le paragraphe. S'il manque,
  l'interface met l'image en évidence et permet de saisir la description à la main :
  le prompt est immédiatement re-généré.

### Tableaux

- Les tableaux sont reconstruits avec leurs fusions (`colspan` / `rowspan`), leurs
  tableaux imbriqués et les images de leurs cellules.
- Ils partent vers Claude en **markdown** (compact en tokens) et sont réinjectés dans
  les cartes en **HTML autonome** (CSS inline, défilement horizontal sur mobile).

### Placeholders

Claude n'écrit jamais de balise `<img>` ni de nom de fichier. Il place des marqueurs,
que l'application remplace à l'export :

| Marqueur | Devient |
|---|---|
| `{{IMG:1}}` | `<img src="ag_projet_xxx.png">` |
| `{{TABLE:1}}` | le tableau complet en HTML |

La numérotation est **locale au chunk**. Un marqueur inventé par le modèle est
supprimé à l'export et signalé dans le rapport. Les boutons d'insertion de l'interface
permettent d'ajouter un marqueur oublié, et l'onglet « Aperçu cartes » montre le rendu
final avant import.

### Exporter avec les médias

Le menu **Exporter** propose trois voies :

1. **TSV seul** — les cartes uniquement (avec les en-têtes `#separator:tab`,
   `#html:true`, `#deck column:1`).
2. **ZIP (TSV + images)** — l'archive contient le TSV, les images utilisées et un
   mode d'emploi.
3. **Copier les médias dans Anki** — copie directe dans le `collection.media` du
   profil choisi. **Anki doit être fermé.** Un fichier identique est laissé tel quel ;
   un conflit (même nom, contenu différent) est signalé et jamais écrasé.

Dans tous les cas, importez ensuite le TSV via _Fichier > Importer_ : le séparateur,
le HTML et la colonne de deck sont déjà déclarés dans l'en-tête du fichier.

---

## 🗂️ Où sont stockées les données ?

- **En développement** (`python app.py`) : dans le dossier du projet
  (`projects/`, `uploads/`, `media/`, `exports/`).
- **Dans l'app packagée** : dans `%APPDATA%\AnkiGen\` (`settings.json`, `projects/`,
  `uploads/`, `media/`, `exports/`). C'est indispensable —
  un exécutable PyInstaller *onefile* est déballé dans un dossier temporaire, tout
  ce qui y serait écrit disparaîtrait à la fermeture.

Le port du serveur de dev peut être changé avec `ANKI_GEN_PORT` (utile quand l'app
installée occupe déjà le port 5000) :

```bash
ANKI_GEN_PORT=5051 .venv/Scripts/python.exe app.py
```

---

## 🧪 Tests

```bash
.venv/Scripts/python.exe -m unittest discover -s tests
```

Les fixtures `.docx` (images avec/sans alt, image seule dans un paragraphe, image
répétée, fusions horizontales et verticales, tableau imbriqué, image en cellule) sont
générées à la volée par `tests/make_fixtures.py` — rien de binaire n'est versionné.
