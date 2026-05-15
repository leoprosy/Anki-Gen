# Anki-Gen (Anki ESH)

Anki-Gen est une application locale hybride (backend Flask en Python + frontend web encapsulé dans une app desktop Tauri) qui permet d'automatiser et de faciliter la création de flashcards Anki à partir de vos cours au format `.docx`.

L'application découpe votre document Word en différents blocs (chunks) selon la structure hiérarchique du plan (I., A., 1)). Elle vous permet ensuite d'utiliser l'IA (comme Claude) pour générer des cartes (Question/Réponse) pour chaque paragraphe, puis d'exporter le tout en un fichier `.csv` formaté pour l'import Anki.

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
   # Depuis la racine du projet, avec votre environnement virtuel activé
   python app.py
   ```

   Rendez-vous ensuite sur `http://127.0.0.1:5000` dans votre navigateur.

2. **Lancer l'application Tauri en mode dev (Fenêtre native) :**
   ```bash
   npm run tauri dev
   ```
   _Note : Lancez d'abord le serveur Flask (`python app.py`) en arrière-plan, car Tauri en mode développement s'attendra à ce que le port 5000 soit actif._

---

## 📦 Compiler l'Application de Production (.exe)

Pour créer un installeur Windows autonome (qui n'a pas besoin de Python installé pour fonctionner), il faut compiler le backend Python en un binaire "sidecar" via PyInstaller, puis packager l'interface avec Tauri.

### 1. Compiler le Sidecar (Flask)

Dans le terminal (avec votre environnement virtuel Python activé) :

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm --onefile --console --name flask-server launcher.py --add-data "templates;templates" --add-data "static;static" --hidden-import waitress --hidden-import flask --hidden-import jinja2.ext --hidden-import docx --hidden-import lxml --hidden-import lxml._elementpath --hidden-import lxml.etree
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

1. **Dashboard & Import :** Sur l'écran d'accueil, sous "Nouveau cours", importez un fichier `.docx` bien structuré (avec des titres numérotés comme `I.`, `A)`, `1)`). Entrez le préfixe de votre Deck Anki (ex: `*ESH*`).
2. **Parsing :** L'application va lire et parser le cours, et créer un "Projet" sauvegardé localement (dans le dossier `projects/`).
3. **Génération via l'IA :**
   - Sur l'interface de travail, cliquez sur le bouton "Copier" pour copier le **System Prompt** (à ne coller qu'une seule fois dans Claude ou ChatGPT).
   - Copiez le texte du "Chunk" (paragraphe) actuel et envoyez-le à Claude.
   - Claude va générer des questions/réponses au format TSV.
4. **Validation :** Copiez la réponse de Claude et collez-la dans la zone de texte de l'application (ou utilisez le bouton "Coller").
5. **Sauvegarde :** Cliquez sur "Enregistrer & Suivant" pour passer au paragraphe suivant.
6. **Exportation :** À tout moment, vous pouvez cliquer sur "CSV" pour télécharger votre fichier formaté prêt à être importé dans Anki !

_(Vos projets sont persistants. Vous pouvez fermer l'application et reprendre vos cours en attente plus tard depuis le Dashboard)._
