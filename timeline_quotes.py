#!/usr/bin/env python3
"""
timeline_quotes.py — Vérification des citations source (anti-hallucination, §6.5).

Chaque élément extrait porte un `source_quote`, censé être copié à l'identique
depuis le texte du cours. On le cherche dans l'instantané du texte source :

- `verified` : trouvé tel quel, après normalisation ;
- `fuzzy` : retrouvé approximativement (SequenceMatcher ≥ 0,9 sur la meilleure
  fenêtre), ou par morceaux quand le modèle a élidé un passage (« … ») ;
- `not_found` : introuvable. L'élément ne vient peut-être pas du cours.

La normalisation efface ce qui change sans changer le texte : forme Unicode
(NFKC), casse, apostrophes et tirets typographiques, guillemets (retirés : un
modèle les ajoute ou les enlève volontiers), balises markdown, espaces.

La recherche floue reste bornée : une fenêtre n'est évaluée que là où plusieurs
mots de la citation tombent au bon endroit (un vote par mot, comme une
transformée de Hough), et seulement pour les meilleures positions. Le coût ne
dépend donc presque pas de la longueur du cours.

Module pur : ni Flask ni I/O.
"""

import difflib
import functools
import re
import unicodedata
from collections import Counter, defaultdict

from timeline_schema import pointer

STATUSES = ("verified", "fuzzy", "not_found")
WARNING_CODES = ("quote_not_found",)
FUZZY_RATIO = 0.9
# En dessous, une ressemblance approximative ne prouve rien.
MIN_FUZZY_WORDS = 4
MAX_CANDIDATES = 8
# Un mot aussi fréquent (« de », « the ») ne vote pas : il désigne tout le texte.
FREQUENT_WORD = 300

_APOSTROPHES = "'’‘‛ʼ´′"
_QUOTES = "\"«»“”„‟‹›″"
_DASHES = "‐‑‒–—―−"
_TABLE = {ord(c): "'" for c in _APOSTROPHES}
_TABLE.update({ord(c): None for c in _QUOTES})
_TABLE.update({ord(c): "-" for c in _DASHES})
_TABLE.update({ord(c): " " for c in "*|`"})

_TABLE_RULE_RE = re.compile(r"^\s*\|?\s*:?-{3,}[-:| ]*$", re.M)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_QUOTE_LINE_RE = re.compile(r"^\s*>\s?", re.M)
_WORD_RE = re.compile(r"\w+(?:['-]\w+)*")
_ELLIPSIS_RE = re.compile(r"\s*(?:\[\.\.\.\]|\(\.\.\.\)|\.\.\.)\s*")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = _TABLE_RULE_RE.sub(" ", text)
    text = _HEADING_RE.sub(" ", text)
    text = _QUOTE_LINE_RE.sub(" ", text)
    text = text.translate(_TABLE)
    return " ".join(text.split())


class SourceIndex:
    """Texte source normalisé, avec la position de chacun de ses mots."""

    def __init__(self, source_text: str):
        self.text = normalize(source_text)
        self.words = [(m.start(), m.end()) for m in _WORD_RE.finditer(self.text)]
        self.positions = defaultdict(list)
        for i, m in enumerate(_WORD_RE.finditer(self.text)):
            self.positions[m.group()].append(i)

    def find(self, quote: str):
        """Statut d'une citation : verified, fuzzy, not_found (None si elle est vide)."""
        q = normalize(quote)
        if not q:
            return None
        if q in self.text:
            return "verified"
        if self._pieces_in_order(q):
            return "fuzzy"
        if self.best_ratio(q) >= FUZZY_RATIO:
            return "fuzzy"
        return "not_found"

    def _pieces_in_order(self, q) -> bool:
        """Citation élidée (« début … fin ») : chaque morceau, dans l'ordre."""
        pieces = [p for p in _ELLIPSIS_RE.split(q) if p.strip()]
        if len(pieces) < 2 or any(len(_WORD_RE.findall(p)) < 2 for p in pieces):
            return False
        start = 0
        for piece in pieces:
            found = self.text.find(piece, start)
            if found == -1:
                return False
            start = found + len(piece)
        return True

    def best_ratio(self, q) -> float:
        words = _WORD_RE.findall(q)
        n = len(words)
        if n < MIN_FUZZY_WORDS or not self.words:
            return 0.0
        votes = Counter()
        for i, word in enumerate(words):
            occurrences = self.positions.get(word)
            if not occurrences or len(occurrences) > FREQUENT_WORD:
                continue
            for j in occurrences:
                votes[j - i] += 1
        needed = max(2, n // 3)
        candidates = [start for start, count in votes.most_common(MAX_CANDIDATES) if count >= needed]
        best = 0.0
        last = len(self.words) - 1
        for start in candidates:
            for first in (start - 1, start, start + 1):
                for length in (n - 1, n, n + 1):
                    a = max(0, first)
                    b = min(last, a + length - 1)
                    if b < a:
                        continue
                    window = self.text[self.words[a][0]:self.words[b][1]]
                    matcher = difflib.SequenceMatcher(None, q, window, autojunk=False)
                    if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
                        continue
                    best = max(best, matcher.ratio())
        return best


@functools.lru_cache(maxsize=4)
def source_index(source_text: str) -> SourceIndex:
    """L'aperçu redessine à chaque frappe : l'index d'un même texte n'est construit qu'une fois."""
    return SourceIndex(source_text)


def check_document(doc, source_text) -> tuple:
    """
    Document normalisé → ({id: statut}, avertissements `quote_not_found`).

    Les éléments ajoutés par le modèle (`origin: "model"`) n'ont pas de citation
    à vérifier : ils sont déjà signalés « hors cours ». Un élément sans citation
    (saisi à la main) n'est pas vérifié non plus.
    """
    if not source_text or not doc:
        return {}, []
    index = source_index(source_text)
    statuses, warnings = {}, []
    for kind in ("eras", "periods", "events"):
        for i, element in enumerate(doc.get(kind) or []):
            quote = element.get("source_quote")
            if element.get("origin") == "model" or not quote:
                continue
            status = index.find(quote)
            if status is None:
                continue
            statuses[element["id"]] = status
            if status == "not_found":
                warnings.append({"path": pointer(kind, i, "source_quote"), "code": "quote_not_found",
                                 "params": {}})
    return statuses, warnings


def annotate(report, source_text) -> dict:
    """Ajoute au rapport d'un document valide ses statuts de citation et leurs avertissements."""
    if not report.get("ok") or not report.get("normalized"):
        return report
    statuses, warnings = check_document(report["normalized"], source_text)
    out = dict(report)
    out["quotes"] = statuses
    out["warnings"] = list(report.get("warnings") or []) + warnings
    return out
