## Analyse du projet et stratégie de maintenabilité

Ton projet a une architecture solide (Tauri + Flask sidecar) mais elle crée des frictions de maintenance importantes :

- **Chaque update** nécessite de re-exécuter PyInstaller + `tauri build` → nouvel installeur à redistribuer
- **Multi-OS** (Windows/macOS/Linux) = 3 pipelines de compilation distincts
- **Pas de mécanisme de mise à jour** sans retéléchargement complet

Voici une stratégie en deux axes : **architecture repensée** + **module d'auto-update**.

---

## Axe 1 — Découpler ce qui change de ce qui ne change pas

Le problème fondamental : tu embarques **tout** dans le binaire Tauri. Or dans ton app, il y a deux couches très différentes :

```
┌─────────────────────────────────────────────────────┐
│  COQUE (change rarement)                            │
│  Tauri shell + PyInstaller bundle + Rust runtime    │
│  → Compile une fois, redistribue rarement           │
├─────────────────────────────────────────────────────│
│  LOGIQUE APPLICATIVE (change souvent)               │
│  app.py, parse_cours.py, templates/, static/        │
│  → Ce sont juste des fichiers texte !               │
└─────────────────────────────────────────────────────┘
```

**L'idée centrale :** faire en sorte que la coque Tauri charge les fichiers Python/HTML depuis un **dossier externe** versionné, pas depuis l'intérieur du binaire.

---

## Axe 2 — Architecture cible recommandée

Je te déconseille de rester sur Tauri + PyInstaller pour un projet solo multi-machines. Le rapport effort/bénéfice est mauvais. Voici deux options selon ton niveau d'investissement :

### Option A — Web app pure déployée (recommandée ⭐)

```
GitHub (source) ──push──▶ Railway / Render (free tier)
                                    │
                          Flask app + fichiers statiques
                                    │
                    ┌───────────────┴──────────────┐
                    │  Machine 1 (Windows)         │
                    │  Machine 2 (macOS)           │  ← juste un navigateur
                    │  Machine 3 (Linux)           │
                    └──────────────────────────────┘
```

**Avantages :**
- Zéro installation sur chaque machine
- Mise à jour = `git push` → déploiement automatique
- Cross-platform natif
- Coût : 0€ (Railway free tier suffit pour un usage solo)

**Inconvénient :** upload de tes fichiers `.docx` vers un serveur distant (même le tien). Si c'est un bloquant pour des raisons de confidentialité, passe à l'option B.

---

### Option B — App locale avec updater léger (si tu veux garder Tauri)

L'architecture devient :

```
src-tauri/binaries/flask-server.exe   ← coque, change rarement
        │
        │ lit au démarrage
        ▼
%APPDATA%/AnkiGen/app/                ← logique applicative, updatable
    ├── app.py
    ├── parse_cours.py
    ├── build_anki_csv.py
    ├── launcher.py
    ├── templates/
    └── static/
```

Le serveur Flask, au lieu de servir des fichiers embarqués, les cherche dans `%APPDATA%/AnkiGen/app/`. L'updater récupère un `.zip` depuis GitHub Releases et remplace ce dossier.

---

## Implémentation concrète de l'Option B

### 1. Modifier `launcher.py` pour chercher les fichiers au bon endroit

```python
# launcher.py
import os, sys

def get_app_dir():
    """Résout le dossier applicatif selon le contexte d'exécution."""
    if getattr(sys, 'frozen', False):
        # Mode PyInstaller : charge depuis APPDATA
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'AnkiGen', 'app')
    else:
        # Mode dev : utilise le dossier courant
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
```

```python
# app.py — adapter les chemins
from launcher import APP_DIR

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static')
)
PROJECTS_DIR = os.path.join(APP_DIR, '..', 'projects')  # un niveau au-dessus = données user
```

### 2. Module updater (fichier `updater.py`)

```python
# updater.py
import os, sys, json, zipfile, shutil, tempfile
from urllib.request import urlopen, Request
from urllib.error import URLError

GITHUB_REPO  = "ton-username/Anki-Gen"          # ← à adapter
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def get_app_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'AnkiGen', 'app')

def get_local_version():
    version_file = os.path.join(get_app_dir(), 'version.json')
    if not os.path.exists(version_file):
        return "0.0.0"
    with open(version_file) as f:
        return json.load(f).get('version', '0.0.0')

def fetch_latest_release():
    """Interroge l'API GitHub pour obtenir le dernier release."""
    req = Request(RELEASES_URL, headers={'User-Agent': 'AnkiGen-Updater'})
    with urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())

def download_and_apply(download_url, target_dir):
    """Télécharge le zip du release et remplace les fichiers applicatifs."""
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, 'update.zip')
        
        # Téléchargement
        req = Request(download_url, headers={'User-Agent': 'AnkiGen-Updater'})
        with urlopen(req, timeout=30) as resp, open(zip_path, 'wb') as f:
            f.write(resp.read())
        
        # Extraction
        extract_dir = os.path.join(tmp, 'extracted')
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        
        # Remplacement atomique : backup → replace → cleanup
        backup_dir = target_dir + '_backup'
        if os.path.exists(backup_dir):
            shutil.rmtree(backup_dir)
        if os.path.exists(target_dir):
            shutil.copytree(target_dir, backup_dir)
        
        # Copie des nouveaux fichiers (préserve /projects et /uploads)
        extracted_app = os.path.join(extract_dir, 'app')  # structure du zip
        for item in os.listdir(extracted_app):
            src = os.path.join(extracted_app, item)
            dst = os.path.join(target_dir, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        
        # Suppression du backup si tout s'est bien passé
        shutil.rmtree(backup_dir)

def check_and_update(silent=False):
    """
    Point d'entrée principal.
    Retourne un dict : {'status': 'up_to_date'|'updated'|'error', 'version': str, 'message': str}
    """
    try:
        release = fetch_latest_release()
        remote_version = release['tag_name'].lstrip('v')
        local_version  = get_local_version()
        
        if remote_version == local_version:
            return {'status': 'up_to_date', 'version': local_version, 'message': 'Déjà à jour.'}
        
        # Cherche l'asset app.zip dans le release
        asset_url = next(
            (a['browser_download_url'] for a in release.get('assets', [])
             if a['name'] == 'app.zip'),
            None
        )
        if not asset_url:
            return {'status': 'error', 'message': 'Asset app.zip introuvable dans le release.'}
        
        download_and_apply(asset_url, get_app_dir())
        return {'status': 'updated', 'version': remote_version,
                'message': f'Mis à jour vers v{remote_version}. Redémarrez l\'application.'}
    
    except URLError:
        return {'status': 'error', 'message': 'Pas de connexion réseau.'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
```

### 3. Endpoint Flask pour déclencher la mise à jour depuis l'UI

```python
# Dans app.py
from updater import check_and_update, get_local_version

@app.route('/api/update/check')
def api_update_check():
    """Vérifie si une mise à jour est disponible (sans l'appliquer)."""
    from updater import fetch_latest_release, get_local_version
    try:
        release = fetch_latest_release()
        remote  = release['tag_name'].lstrip('v')
        local   = get_local_version()
        return jsonify({
            'update_available': remote != local,
            'local_version': local,
            'remote_version': remote,
            'release_notes': release.get('body', '')
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update/apply', methods=['POST'])
def api_update_apply():
    """Applique la mise à jour."""
    result = check_and_update()
    return jsonify(result)
```

### 4. Composant UI dans `base.html`

```html
<!-- Bandeau de mise à jour — insérer dans base.html -->
<div id="update-banner" style="display:none"
     class="update-banner">
  <span id="update-message"></span>
  <button id="update-btn" onclick="applyUpdate()">Mettre à jour</button>
  <button onclick="document.getElementById('update-banner').style.display='none'">
    ✕
  </button>
</div>

<script>
// Vérification silencieuse au démarrage
async function checkUpdate() {
  try {
    const res  = await fetch('/api/update/check');
    const data = await res.json();
    if (data.update_available) {
      document.getElementById('update-message').textContent =
        `v${data.remote_version} disponible`;
      document.getElementById('update-banner').style.display = 'flex';
    }
  } catch (_) {}  // silencieux si hors-ligne
}

async function applyUpdate() {
  document.getElementById('update-btn').textContent = 'Mise à jour…';
  document.getElementById('update-btn').disabled = true;
  const res  = await fetch('/api/update/apply', { method: 'POST' });
  const data = await res.json();
  alert(data.message);
  if (data.status === 'updated') location.reload();
}

window.addEventListener('load', checkUpdate);
</script>
```

### 5. Structure du release GitHub

Dans ton workflow GitHub Actions (`.github/workflows/release.yml`) :

```yaml
name: Release app bundle

on:
  push:
    tags: ['v*']

jobs:
  bundle:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Créer app.zip (fichiers Python + templates + static)
        run: |
          mkdir -p release/app
          cp app.py parse_cours.py build_anki_csv.py launcher.py updater.py release/app/
          cp -r templates static release/app/
          echo '{"version": "${{ github.ref_name }}"}' | \
            sed 's/v//' > release/app/version.json
          cd release && zip -r ../app.zip app/
      
      - name: Créer le GitHub Release
        uses: softprops/action-gh-release@v1
        with:
          files: app.zip
          generate_release_notes: true
```

**Pour publier une mise à jour**, tu fais simplement :
```bash
git tag v1.2.0
git push origin v1.2.0
# → GitHub Actions construit et publie app.zip automatiquement
```

---

## Résumé comparatif

| Critère | Situation actuelle | Option A (web) | Option B (updater) |
|---|---|---|---|
| Multi-OS | ❌ 3 compilations | ✅ natif | ✅ avec un seul binaire |
| Mise à jour | ❌ retéléchargement | ✅ `git push` | ✅ un clic dans l'UI |
| Données locales | ✅ | ❌ (serveur distant) | ✅ |
| Complexité setup | Élevée | Faible | Moyenne |
| Coût | 0€ | 0€ | 0€ |

**Ma recommandation :** si tu travailles uniquement sur tes propres machines (pas de distribution à d'autres), passe à **l'Option A** — c'est de loin la solution la plus légère. Si tu veux distribuer l'app ou garder les données strictement locales, l'**Option B avec l'updater** est la bonne approche, et le module `updater.py` ci-dessus est directement intégrable dans ton projet existant.