#!/usr/bin/env python3
"""
local_llm.py — Le petit modèle de langage qui tourne dans l'app elle-même.

Les tâches légères (extraire les dates d'un paragraphe, corriger un JSON
refusé) n'ont pas besoin de Claude : un modèle de 4 milliards de paramètres
suffit, à condition de ne pas pouvoir produire autre chose qu'un JSON conforme.
llama.cpp le garantit en transformant le schéma JSON en grammaire.

Le modèle tourne dans ce processus : ni Ollama, ni serveur à côté, ni port de
plus. Le fichier GGUF (~2,5 Go) n'est pas dans l'installateur ; il se
télécharge à la demande dans DATA_DIR/models, vérifié par SHA-256.

`llama_cpp` n'est importé qu'au premier usage : un exécutable qui ne l'embarque
pas (runtime antérieur) fait simplement `available() == False`.
"""

import hashlib
import importlib.util
import threading
import urllib.request

import paths

MODEL = {
    "name": "Qwen3-4B-Instruct-2507 (Q4_K_M)",
    "file": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    "url": "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/"
           "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    "sha256": "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
    "size": 2497281120,
}

# Fenêtre de contexte. Le cache KV en coûte ~150 Ko par jeton pour ce modèle :
# 8192 jetons ≈ 1,2 Go de RAM en plus des poids. Assez pour un paragraphe et
# son prompt ; une frise entière d'un long cours n'y tient pas (PromptTooLong).
N_CTX = 8192
# Le modèle chargé occupe ~4 Go : on le libère après ce délai sans requête.
IDLE_UNLOAD_SECONDS = 600

_download = {"running": False, "done": 0, "error": None}
_llm = None
_lock = threading.Lock()  # ponytail: une inférence à la fois — l'app n'a qu'un utilisateur
_unload_timer = None


class ModelMissing(Exception):
    pass


class PromptTooLong(Exception):
    def __init__(self, tokens):
        super().__init__(tokens)
        self.tokens = tokens


def available() -> bool:
    """L'exécutable embarque-t-il llama.cpp ?"""
    return importlib.util.find_spec("llama_cpp") is not None


def model_path():
    return paths.MODELS_DIR / MODEL["file"]


def status() -> dict:
    return {
        "available": available(),
        "installed": model_path().is_file(),
        "loaded": _llm is not None,
        "name": MODEL["name"],
        "size": MODEL["size"],
        "downloading": _download["running"],
        "done": _download["done"],
        "error": _download["error"],
    }


# ──────────────────────────────────────────────────────────────
# Téléchargement
# ──────────────────────────────────────────────────────────────
def download_to(url, dest, sha256, progress=lambda done: None, chunk=1 << 20):
    """
    Télécharge `url` dans `dest`, en passant par `dest.part` : un fichier
    interrompu ou corrompu n'est jamais pris pour le modèle. Lève ValueError si
    l'empreinte ne correspond pas.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest, done = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(part, "wb") as out:
            while block := response.read(chunk):
                out.write(block)
                digest.update(block)
                done += len(block)
                progress(done)
        if digest.hexdigest() != sha256:
            raise ValueError("checksum mismatch")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


def _run_download():
    def progress(done):
        _download["done"] = done
    try:
        download_to(MODEL["url"], model_path(), MODEL["sha256"], progress)
    except Exception as error:  # noqa: BLE001 — l'erreur est rendue à l'interface, pas levée
        _download["error"] = f"{type(error).__name__}: {error}"
    finally:
        _download["running"] = False


def start_download() -> bool:
    """Lance le téléchargement en arrière-plan ; False s'il tourne déjà ou si le modèle est là."""
    if _download["running"] or model_path().is_file():
        return False
    _download.update(running=True, done=0, error=None)
    threading.Thread(target=_run_download, name="model-download", daemon=True).start()
    return True


def delete() -> None:
    unload()
    model_path().unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────
# Inférence
# ──────────────────────────────────────────────────────────────
def unload() -> None:
    global _llm
    with _lock:
        _llm = None


def _schedule_unload():
    global _unload_timer
    if _unload_timer:
        _unload_timer.cancel()
    _unload_timer = threading.Timer(IDLE_UNLOAD_SECONDS, unload)
    _unload_timer.daemon = True
    _unload_timer.start()


def complete(messages: list, schema: dict) -> str:
    """
    La conversation → une réponse JSON conforme à `schema` (texte brut, comme un collage).

    Température nulle : on extrait, on n'invente pas, et deux essais sur le même
    paragraphe donnent la même frise.
    """
    global _llm
    if not model_path().is_file():
        raise ModelMissing()
    with _lock:
        if _llm is None:
            from llama_cpp import Llama
            _llm = Llama(str(model_path()), n_ctx=N_CTX, verbose=False)
        # ponytail: estimation (contenus + ~8 jetons de gabarit par message), assez juste pour une marge
        tokens = sum(len(_llm.tokenize(m["content"].encode("utf-8"))) + 8 for m in messages)
        # Il faut aussi la place de la réponse : une frise de paragraphe tient en ~1500 jetons.
        if tokens > N_CTX - 1536:
            raise PromptTooLong(tokens)
        out = _llm.create_chat_completion(
            messages=messages,
            response_format={"type": "json_object", "schema": schema},
            temperature=0,
            max_tokens=N_CTX - tokens,
        )
    _schedule_unload()
    return out["choices"][0]["message"]["content"]
