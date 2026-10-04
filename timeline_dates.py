#!/usr/bin/env python3
"""
timeline_dates.py — Les dates des frises : analyse, intervalles, formatage.

Une frise d'histoire mélange « 44 av. J.-C. », « XVIe siècle » et « 15 août
1971 ». `datetime` ne sait représenter ni les années ≤ 0 ni celles au-delà de
9999, et la chronologie historique n'a pas d'an 0 : tout est donc calculé ici,
à la main, dans le calendrier grégorien proleptique (aucune conversion depuis le
julien : une date d'avant 1582 est prise telle qu'écrite).

Chaque date devient un intervalle [t0, t1) en années décimales ASTRONOMIQUES
(1 av. J.-C. = 0, 44 av. J.-C. = -43) : l'arithmétique reste continue, et la
mise en page n'a jamais à connaître l'absence d'an 0.

Le formatage suit la langue du DOCUMENT, pas celle de l'interface : les noms de
mois et les gabarits vivent dans les catalogues (`timeline.date.*`), les règles
de grammaire (chiffres romains, suffixes ordinaux anglais) dans ce module.

Module pur : ni Flask, ni I/O.
"""

import datetime
import re
from dataclasses import dataclass

from i18n import translate

PRECISIONS = ("day", "month", "year", "decade", "century", "millennium")
# Les précisions « ponctuelles » placent le marqueur au début de l'intervalle
# (l'évènement « 1850 » tombe sur la graduation 1850) ; les autres au milieu.
POINT_PRECISIONS = ("day", "month", "year")
PRESENT = "present"

# [0-9] et non \d : \d accepte aussi les chiffres arabes-indiens ou devanagari.
DATE_RE = re.compile(r"(-?)([0-9]{1,5})(?:-([0-9]{2})(?:-([0-9]{2}))?)?")
AS_OF_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# Tiret demi-cadratin des intervalles (« 1870–1914 »).
RANGE_DASH = "–"

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_UNIT_YEARS = {"decade": 10, "century": 100, "millennium": 1000}


class DateError(ValueError):
    """Date refusée. `code` devient la clé i18n `timeline.err.<code>`."""

    def __init__(self, code, **params):
        super().__init__(code)
        self.code = code
        self.params = params


# ──────────────────────────────────────────────────────────────
# Années historiques / astronomiques, calendrier
# ──────────────────────────────────────────────────────────────
def to_astronomical(year: int) -> int:
    """-44 (44 av. J.-C.) → -43. L'année historique 0 n'existe pas."""
    if year == 0:
        raise ValueError("l'année 0 n'existe pas dans la chronologie historique")
    return year if year > 0 else year + 1


def to_historical(astro: int) -> int:
    """0 → -1 (1 av. J.-C.) ; inverse de to_astronomical."""
    return astro if astro > 0 else astro - 1


def is_leap(astro: int) -> bool:
    """Règle grégorienne appliquée aux années astronomiques (0 et -4 sont bissextiles)."""
    return astro % 4 == 0 and (astro % 100 != 0 or astro % 400 == 0)


def days_in_year(astro: int) -> int:
    return 366 if is_leap(astro) else 365


def days_in_month(astro: int, month: int) -> int:
    if month == 2 and is_leap(astro):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def day_of_year(astro: int, month: int, day: int) -> int:
    return sum(days_in_month(astro, m) for m in range(1, month)) + day


def decimal_year(astro: int, month: int = 1, day: int = 1) -> float:
    """Début du jour donné, en années décimales : année + (jour de l'année − 1) / jours."""
    return astro + (day_of_year(astro, month, day) - 1) / days_in_year(astro)


def _next_month(astro, month):
    return (astro + 1, 1) if month == 12 else (astro, month + 1)


def _next_day(astro, month, day):
    if day < days_in_month(astro, month):
        return astro, month, day + 1
    astro, month = _next_month(astro, month)
    return astro, month, 1


# ──────────────────────────────────────────────────────────────
# Unités larges : décennie, siècle, millénaire
# ──────────────────────────────────────────────────────────────
def _unit_number(year: int, size: int) -> int:
    """
    Rang (signé) du siècle ou du millénaire qui contient `year`, convention stricte.

    XVIe siècle = 1501–1600 ; IIIe siècle av. J.-C. = 300–201 av. J.-C. (-3).
    """
    if year > 0:
        return (year - 1) // size + 1
    return -((-year - 1) // size + 1)


def _unit_interval(number: int, size: int):
    """[t0, t1) astronomique du siècle/millénaire de rang signé `number`."""
    if number > 0:
        return float(size * (number - 1) + 1), float(size * number + 1)
    n = -number
    return float(1 - size * n), float(1 + size - size * n)


def _decade_interval(year: int):
    """
    « années 1970 » = 1970–1979 ; « années 1750 av. J.-C. » = 1759–1750 av. J.-C.

    Avant notre ère, les années se comptent à rebours : la décennie D réunit les
    années D+9 à D av. J.-C.
    """
    if year > 0:
        return float(year), float(year + 10)
    d = -year
    return float(-d - 8), float(-d + 2)


def _decade_key(year: int):
    return (1, year // 10) if year > 0 else (-1, -year // 10)


# ──────────────────────────────────────────────────────────────
# Analyse
# ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TimelineDate:
    """
    Une date du document, résolue.

    `year` est l'année HISTORIQUE (-44 = 44 av. J.-C., jamais 0). `unit` est le
    rang signé de la décennie, du siècle ou du millénaire pour ces précisions
    (après résolution d'un siècle ambigu), sinon None.
    """

    year: int
    month: object
    day: object
    precision: str
    t0: float
    t1: float
    unit: object = None
    ambiguous: bool = False
    present: bool = False

    @property
    def bc(self) -> bool:
        return self.year < 0

    @property
    def position(self) -> float:
        """Abscisse (en années) d'un évènement ponctuel portant cette date."""
        if self.precision in POINT_PRECISIONS:
            return self.t0
        return (self.t0 + self.t1) / 2


def _parse_as_of(as_of):
    """`as_of` du document (AAAA-MM-JJ), ou la date du jour."""
    if as_of is None:
        today = datetime.date.today()
        return today.year, today.month, today.day
    if isinstance(as_of, TimelineDate):
        return as_of.year, as_of.month, as_of.day
    if not isinstance(as_of, str) or not AS_OF_RE.fullmatch(as_of):
        raise DateError("as_of_invalid", value=str(as_of))
    date = parse_date(as_of)
    return date.year, date.month, date.day


def parse_date(text, precision=None, *, allow_present=False, as_of=None) -> TimelineDate:
    """
    Chaîne du contrat → TimelineDate. Lève DateError(code, value=…).

    `precision` peut être omise (déduite de la chaîne) ou égale à la précision de
    la chaîne ; `decade`, `century` et `millennium` exigent une année seule. Une
    précision plus grossière que la chaîne est refusée plutôt que tronquée en
    silence : c'est le prompt de correction qui tranchera.
    """
    if precision is not None and precision not in PRECISIONS:
        raise DateError("precision_invalid", value=str(precision))
    if text == PRESENT:
        if not allow_present:
            raise DateError("present_not_allowed", value=text)
        if precision not in (None, "day"):
            raise DateError("precision_mismatch", value=text, precision=precision)
        year, month, day = _parse_as_of(as_of)
        return _build(year, month, day, "day", present=True)

    match = DATE_RE.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise DateError("date_invalid", value=str(text))
    sign, year_s, month_s, day_s = match.groups()
    year = int(year_s) * (-1 if sign else 1)
    if year == 0:
        raise DateError("date_year_zero", value=text)
    astro = to_astronomical(year)
    month = int(month_s) if month_s else None
    day = int(day_s) if day_s else None
    if month is not None and not 1 <= month <= 12:
        raise DateError("date_month_invalid", value=text)
    if day is not None and not 1 <= day <= days_in_month(astro, month):
        raise DateError("date_day_invalid", value=text)

    written = "day" if day else "month" if month else "year"
    if precision is None or precision == written:
        return _build(year, month, day, written)
    if written != "year" or precision in POINT_PRECISIONS:
        raise DateError("precision_mismatch", value=text, precision=precision)
    if precision == "decade" and abs(year) % 10:
        raise DateError("precision_mismatch", value=text, precision=precision)
    return _build(year, None, None, precision)


def _build(year, month, day, precision, present=False) -> TimelineDate:
    astro = to_astronomical(year)
    unit = None
    ambiguous = False
    if precision == "day":
        t0 = decimal_year(astro, month, day)
        t1 = decimal_year(*_next_day(astro, month, day))
    elif precision == "month":
        t0 = decimal_year(astro, month)
        t1 = decimal_year(*_next_month(astro, month))
    elif precision == "year":
        t0, t1 = float(astro), float(astro + 1)
    elif precision == "decade":
        t0, t1 = _decade_interval(year)
        unit = _decade_key(year)
    else:
        size = _UNIT_YEARS[precision]
        # « 1500 » : XVe siècle au sens strict, mais les modèles l'écrivent presque
        # toujours pour dire « le XVIe ». On le lit comme le début de l'unité
        # suivante, avec un avertissement. Avant notre ère, la première année
        # d'un siècle EST le multiple de 100 (-300 ouvre le IIIe av. J.-C.) :
        # aucune ambiguïté.
        if year > 0 and year % size == 0:
            unit = year // size + 1
            ambiguous = True
        else:
            unit = _unit_number(year, size)
        t0, t1 = _unit_interval(unit, size)
    return TimelineDate(year, month, day, precision, t0, t1, unit, ambiguous, present)


# ──────────────────────────────────────────────────────────────
# Comparaisons
# ──────────────────────────────────────────────────────────────
def sort_key(date: TimelineDate):
    """Ordre chronologique : début, puis fin. Les égalités gardent l'ordre d'entrée."""
    return date.t0, date.t1


def coarser(a: str, b: str) -> str:
    return a if PRECISIONS.index(a) >= PRECISIONS.index(b) else b


def bucket(date: TimelineDate, precision: str):
    """Case de `date` à une précision au moins aussi grossière que la sienne."""
    if precision == date.precision and date.unit is not None:
        return date.unit
    if precision == "day":
        return date.year, date.month, date.day
    if precision == "month":
        return date.year, date.month
    if precision == "year":
        return date.year
    if precision == "decade":
        return _decade_key(date.year)
    return _unit_number(date.year, _UNIT_YEARS[precision])


def same_at_common_precision(a: TimelineDate, b: TimelineDate) -> bool:
    """« 1947-10-30 » et « 1947 » tombent dans la même année : même date à la précision commune."""
    common = coarser(a.precision, b.precision)
    return bucket(a, common) == bucket(b, common)


# ──────────────────────────────────────────────────────────────
# Formatage (langue du document)
# ──────────────────────────────────────────────────────────────
_ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))


def roman(n: int) -> str:
    out = []
    for value, symbol in _ROMAN:
        count, n = divmod(n, value)
        out.append(symbol * count)
    return "".join(out)


def _ordinal_category_en(n):
    if n % 100 in (11, 12, 13):
        return "other"
    return {1: "one", 2: "two", 3: "few"}.get(n % 10, "other")


# Règles de grammaire par langue ; les suffixes eux-mêmes sont traduits
# (`timeline.date.ordinal_<catégorie>`). Une langue absente suit l'anglais,
# comme ses chaînes, qui retombent sur le catalogue anglais.
_ORDINAL_RULES = {
    "fr": (roman, lambda n: "one" if n == 1 else "other"),
}
_DEFAULT_ORDINAL_RULE = (str, _ordinal_category_en)


def ordinal(n: int, lang: str) -> str:
    """16 → « XVIe » (fr), « 16th » (en). Sert aux siècles et millénaires."""
    numeral, category = _ORDINAL_RULES.get(lang, _DEFAULT_ORDINAL_RULE)
    return numeral(n) + translate(f"timeline.date.ordinal_{category(n)}", lang)


def _day_label(day, lang):
    return translate("timeline.date.day_first", lang) if day == 1 else str(day)


def _core(date: TimelineDate, lang: str, short: bool) -> str:
    """Date sans marque d'ère ni « v. » : « 15 août 44 », « XVIe siècle »."""
    year = abs(date.year)
    if date.precision == "day":
        return translate("timeline.date.day", lang, day=_day_label(date.day, lang),
                         month=translate(f"timeline.date.month_{date.month}", lang), year=year)
    if date.precision == "month":
        return translate("timeline.date.month", lang,
                         month=translate(f"timeline.date.month_{date.month}", lang), year=year)
    if date.precision == "year":
        return str(year)
    if date.precision == "decade":
        return translate("timeline.date.decade", lang, year=year)
    key = f"timeline.date.{date.precision}" + ("_short" if short and date.precision == "century" else "")
    return translate(key, lang, n=ordinal(abs(date.unit), lang))


def _with_era(text: str, bc: bool, lang: str) -> str:
    return translate("timeline.date.bc", lang, date=text) if bc else text


def _approx(text: str, approx: bool, lang: str) -> str:
    return translate("timeline.date.approx", lang, date=text) if approx else text


def format_date(date: TimelineDate, lang: str, *, approx: bool = False, short: bool = False) -> str:
    """« 15 août 1971 », « v. 1750 av. J.-C. », « XVIe s. » (`short`)."""
    return _approx(_with_era(_core(date, lang, short), date.bc, lang), approx, lang)


def format_year(year: int, lang: str) -> str:
    """Année historique seule, pour les graduations : « 44 av. J.-C. », « 1971 »."""
    return _with_era(str(abs(year)), year < 0, lang)


def format_range(start: TimelineDate, end: TimelineDate, lang: str, *, approx: bool = False) -> str:
    """
    « 1870–1914 », « 753–509 av. J.-C. », « 44 av. J.-C.–14 » (« 44 BC–AD 14 »),
    « depuis 2001 ». La marque d'ère n'est répétée que si les deux bornes diffèrent.
    """
    if end.present:
        return translate("timeline.date.since", lang, date=format_date(start, lang, approx=approx))
    first, last = _core(start, lang, False), _core(end, lang, False)
    if start.bc and end.bc:
        text = _with_era(first if first == last else first + RANGE_DASH + last, True, lang)
    elif start.bc:
        text = (_with_era(first, True, lang) + RANGE_DASH
                + translate("timeline.date.ad", lang, date=last))
    else:
        text = first if first == last else first + RANGE_DASH + last
    return _approx(text, approx, lang)
