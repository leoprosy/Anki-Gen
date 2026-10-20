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

import ctypes
import functools
import hashlib
import importlib.util
import os
import sys
import threading
import urllib.request
from pathlib import Path

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


# ──────────────────────────────────────────────────────────────
# Carte graphique
# ──────────────────────────────────────────────────────────────
# llama.cpp est compilé avec Vulkan : il tourne sur les cartes NVIDIA, AMD et
# Intel, et sur le processeur s'il n'en trouve aucune. On ne lui laisse qu'une
# carte dédiée assez grande pour tout le modèle : seul, un GPU intégré fait
# planter le chargement (mesuré sur une Radeon de Ryzen 7000), et une carte trop
# petite ne pourrait en prendre qu'une partie.
# ponytail: tout ou rien ; un déchargement partiel si les cartes de 4 Go comptent.
GPU_MIN_VRAM = 5 << 30          # poids (2,5 Go) + cache KV (1,2 Go) + calculs
_VK_DISCRETE_GPU = 2
_VK_DEVICE_LOCAL = 1
# Le chargeur Vulkan vient avec le pilote de la carte (System32). Sans lui
# llama.dll ne se charge pas : l'exécutable en embarque une copie de secours.
_FALLBACK_LOADER_DIR = Path(getattr(sys, "_MEIPASS", "")) / "vulkan_loader" if paths.is_frozen() else None


class _InstanceInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.c_void_p), ("enabledLayerCount", ctypes.c_uint32),
                ("ppEnabledLayerNames", ctypes.c_void_p), ("enabledExtensionCount", ctypes.c_uint32),
                ("ppEnabledExtensionNames", ctypes.c_void_p)]


def vulkan_devices() -> list:
    """Les cartes que verra llama.cpp, dans son ordre : [{"name", "discrete", "vram"}]. [] sans Vulkan."""
    try:
        vk = ctypes.WinDLL("vulkan-1")
    except (OSError, AttributeError):        # pas de pilote Vulkan, ou pas Windows
        return []
    instance = ctypes.c_void_p()
    info = _InstanceInfo(sType=1)            # VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
    if vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance)) != 0:
        return []
    try:
        count = ctypes.c_uint32()
        vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
        handles = (ctypes.c_void_p * count.value)()
        vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), handles)
        devices = []
        for handle in handles:
            # VkPhysicalDeviceProperties : deviceType à l'octet 16, deviceName (256 octets) à 20.
            props = ctypes.create_string_buffer(2048)
            vk.vkGetPhysicalDeviceProperties(ctypes.c_void_p(handle), props)
            # VkPhysicalDeviceMemoryProperties : 32 types de 8 octets, puis le nombre
            # de tas (octet 260) et les tas de 16 octets {size u64, flags u32} (octet 264).
            memory = ctypes.create_string_buffer(1024)
            vk.vkGetPhysicalDeviceMemoryProperties(ctypes.c_void_p(handle), memory)
            heaps = [(int.from_bytes(memory.raw[264 + 16 * i:272 + 16 * i], "little"),
                      int.from_bytes(memory.raw[272 + 16 * i:276 + 16 * i], "little"))
                     for i in range(int.from_bytes(memory.raw[260:264], "little"))]
            devices.append({
                "name": props.raw[20:276].split(b"\0", 1)[0].decode("utf-8", "replace"),
                "discrete": int.from_bytes(props.raw[16:20], "little") == _VK_DISCRETE_GPU,
                "vram": max((size for size, flags in heaps if flags & _VK_DEVICE_LOCAL), default=0),
            })
        return devices
    finally:
        vk.vkDestroyInstance(instance, None)


def pick_gpu(devices):
    """
    L'indice de la carte à utiliser, ou None : la carte dédiée qui a le plus de
    mémoire, si elle suffit. Les cartes vues à travers Direct3D 12 (la couche
    « Dozen » du pack de compatibilité Windows) doublent les vraies : écartées.
    """
    usable = [(d["vram"], -i) for i, d in enumerate(devices)
              if d["discrete"] and d["vram"] >= GPU_MIN_VRAM and not d["name"].startswith("Microsoft Direct3D12")]
    return -max(usable)[1] if usable else None


def _vulkan_build() -> bool:
    """L'exécutable embarque-t-il le llama.cpp Vulkan ? (le runtime 2 n'a que le processeur)"""
    spec = importlib.util.find_spec("llama_cpp")
    return bool(spec and spec.origin) and (Path(spec.origin).parent / "lib" / "ggml-vulkan.dll").is_file()


@functools.cache
def _device() -> tuple:
    """(indice Vulkan, nom) de la carte qui fera tourner le modèle, ou (None, None). Détecté une fois."""
    system_loader = Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "vulkan-1.dll")
    if not system_loader.is_file() and _FALLBACK_LOADER_DIR and _FALLBACK_LOADER_DIR.is_dir():
        os.add_dll_directory(str(_FALLBACK_LOADER_DIR))
    if not _vulkan_build():
        return None, None
    devices = vulkan_devices()
    index = pick_gpu(devices)
    return (index, devices[index]["name"]) if index is not None else (None, None)


def gpu():
    """Nom de la carte qui fera tourner le modèle, ou None (processeur)."""
    return _device()[1]


def status() -> dict:
    return {
        "available": available(),
        "gpu": gpu(),
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


class _GrammarFirstSampler:
    """
    Décodage glouton sous grammaire, comme `common_sampler` de llama.cpp : on
    prend le jeton le plus probable et on ne demande qu'à lui s'il respecte la
    grammaire ; tout le vocabulaire (151 000 jetons) n'est filtré que s'il est
    refusé. Même jeton qu'en filtrant d'abord : le plus probable des jetons
    permis. llama-cpp-python, lui, filtre tout le vocabulaire à chaque jeton.
    """

    def __init__(self, llm, grammar):
        import numpy as np
        from llama_cpp import llama_cpp as C
        self.np, self.C, self.n_vocab = np, C, llm.n_vocab()
        self.grammar = C.llama_sampler_init_grammar(
            llm._model.vocab, grammar._grammar.encode("utf-8"), grammar._root.encode("utf-8"))
        self.one = C.llama_token_data()
        self.all = (C.llama_token_data * self.n_vocab)()
        self.all_view = np.ctypeslib.as_array(self.all)

    def _apply(self, data, size):
        C = self.C
        C.llama_sampler_apply(self.grammar, ctypes.byref(C.llama_token_data_array(
            data=ctypes.cast(data, C.llama_token_data_p), size=size, selected=-1, sorted=False)))

    def sample(self, ctx, idx=-1) -> int:
        np = self.np
        logits = np.ctypeslib.as_array(self.C.llama_get_logits_ith(ctx.ctx, idx), shape=(self.n_vocab,))
        token = int(logits.argmax())
        self.one.id, self.one.logit, self.one.p = token, logits[token], 0.0
        self._apply(ctypes.byref(self.one), 1)
        if self.one.logit == -np.inf:
            self.all_view["id"] = np.arange(self.n_vocab)
            self.all_view["logit"] = logits
            self._apply(self.all, self.n_vocab)
            token = int(self.all_view["id"][self.all_view["logit"].argmax()])
        self.C.llama_sampler_accept(self.grammar, token)
        return token

    def __del__(self):
        self.C.llama_sampler_free(self.grammar)


def _grammar_first(llm):
    """Branche `_GrammarFirstSampler` sur `llm` pour les générations sous grammaire à température nulle."""
    # ponytail: remplace une méthode privée de llama-cpp-python (version figée dans requirements.txt)
    default = llm._init_sampler

    def init_sampler(**options):
        if options.get("grammar") is None or options.get("temp") != 0:
            return default(**options)
        return _GrammarFirstSampler(llm, options["grammar"])

    llm._init_sampler = init_sampler
    return llm


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
            # Lu par llama.cpp à son chargement : il ne voit que la carte choisie, ou aucune.
            index = _device()[0]
            os.environ["GGML_VK_VISIBLE_DEVICES"] = "" if index is None else str(index)
            from llama_cpp import Llama
            _llm = _grammar_first(Llama(str(model_path()), n_ctx=N_CTX, n_gpu_layers=-1, verbose=False))
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
