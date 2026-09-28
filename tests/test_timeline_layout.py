#!/usr/bin/env python3
"""
tests/test_timeline_layout.py — Le moteur de mise en page des frises.

Trois étages :
  * check_layout() doit repérer chaque violation d'invariant (I1–I9) sur des
    display lists construites à la main, fautives exprès ;
  * layout() ne doit en produire aucune, sur chaque fixture, dans les deux
    densités, en largeur fixe comme automatique, et sur 300 documents aléatoires ;
  * les propriétés du §7 : marqueurs à leur date exacte, aucun élément perdu,
    rangées de périodes minimales, ruptures d'axe, déterminisme, performance.

Le mesureur est factice (table de largeurs par caractère) : ces tests ne
dépendent ni de Pillow ni des polices.

    .venv/Scripts/python.exe -m unittest discover -s tests
"""

import json
import random
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import timeline_layout as tl  # noqa: E402
import timeline_schema as ts  # noqa: E402
from timeline_layout import Layout, LayoutOptions, Line, Marker, Rect, Scale, Text  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures_timeline"
VALID_FIXTURES = sorted(FIXTURES.glob("*.json"))

NARROW = set("iljtfrI.,;:!|'’ ()[]")
WIDE = set("mwMW@%—…")


def fake_measure(text, size, weight):
    """Largeurs déterministes, grossièrement proportionnelles à une vraie police."""
    total = 0.0
    for ch in text:
        if ch in NARROW:
            total += 0.3
        elif ch in WIDE:
            total += 0.85
        elif ord(ch) >= 0x2E80:
            total += 1.0
        elif ch.isupper() or ch.isdigit():
            total += 0.64
        else:
            total += 0.54
    return total * size * (1.06 if weight >= 500 else 1.0)


def load(name):
    report = ts.validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))
    assert report["ok"], report["errors"]
    return report["normalized"]


def violations(layout):
    return [f"{v.invariant} {v.message}" for v in tl.check_layout(layout)]


# ──────────────────────────────────────────────────────────────
# Display lists fautives
# ──────────────────────────────────────────────────────────────
def text(x, y, s="Traité", role="event-label", ref="e1", lane=None, anchor="start", size=12):
    return Text(x=x, y=y, lines=(s,), size=size, weight=400, fill="#000000", anchor=anchor,
                line_height=15.0, widths=(fake_measure(s, size, 400),), role=role, ref=ref, lane=lane)


def hand(*primitives, width=400, height=200, **extra):
    fields = dict(width=width, height=height, primitives=tuple(primitives))
    fields.update(extra)
    return Layout(**fields)


class TestInvariantsDetectFaults(unittest.TestCase):
    def codes(self, layout):
        return sorted({v.invariant for v in tl.check_layout(layout)})

    def test_clean_display_list(self):
        self.assertEqual(self.codes(hand(text(10, 50), text(10, 100, ref="e2"),
                                         elements=("e1", "e2"))), [])

    def test_i1_texts_overlap(self):
        self.assertEqual(self.codes(hand(text(10, 50), text(20, 55, ref="e2"),
                                         elements=("e1", "e2"))), ["I1"])

    def test_i1_texts_closer_than_two_pixels(self):
        first = text(10, 50)
        x1 = first.bbox[2]
        self.assertEqual(self.codes(hand(first, text(x1 + 1, 50, ref="e2"), elements=("e1", "e2"))), ["I1"])
        self.assertEqual(self.codes(hand(first, text(x1 + 2.5, 50, ref="e2"), elements=("e1", "e2"))), [])

    def test_i2_text_on_a_marker(self):
        marker = Marker(shape="circle", cx=15, cy=46, r=5, fill="#0371B1", stroke="#FFFFFF",
                        role="marker", ref="e2")
        self.assertEqual(self.codes(hand(text(10, 50), marker, elements=("e1",))), ["I2"])

    def test_i2_period_label_may_sit_on_its_own_bar(self):
        bar = Rect(x=5, y=36, w=200, h=18, rx=9, fill="#0371B1", role="period-bar", ref="p")
        label = text(11, 49, role="period-label", ref="p")
        self.assertEqual(self.codes(hand(bar, label, elements=("p",))), [])
        other = text(11, 49, role="period-label", ref="q")
        self.assertEqual(self.codes(hand(bar, other, elements=("q",))), ["I2"])

    def test_i3_stem_through_a_label(self):
        stem = Line(x1=30, y1=80, x2=30, y2=20, stroke="#0371B1", width=1, role="stem", ref="e2")
        self.assertEqual(self.codes(hand(text(10, 50), stem, elements=("e1",))), ["I2", "I3"])

    def test_i4_outside_the_canvas(self):
        self.assertEqual(self.codes(hand(text(390, 50), elements=("e1",))), ["I4"])
        self.assertEqual(self.codes(hand(text(10, 8), elements=("e1",))), ["I4"])

    def test_i5_primitive_outside_its_lane(self):
        lanes = ((40, 60), (70, 120))
        inside = text(10, 55, lane=0)
        self.assertEqual(self.codes(hand(inside, lanes=lanes, elements=("e1",))), [])
        outside = text(10, 100, lane=0)
        self.assertEqual(self.codes(hand(outside, lanes=lanes, elements=("e1",))), ["I5"])

    def test_i5_lanes_overlap(self):
        self.assertEqual(self.codes(hand(text(10, 50), lanes=((40, 80), (70, 120)),
                                         elements=("e1",))), ["I5"])

    def test_i6_marker_away_from_its_date(self):
        scale = Scale(((1900.0, 2000.0, 0.0, 400.0, False),))
        marker = Marker(shape="circle", cx=200.2, cy=150, r=4, fill="#000000", stroke=None,
                        role="marker", ref="e1")
        ok = hand(marker, text(10, 50), scale=scale, anchors=(("e1", 1950.0),), elements=("e1",))
        self.assertEqual(self.codes(ok), [])
        moved = hand(Marker(shape="circle", cx=201.0, cy=150, r=4, fill="#000000", stroke=None,
                            role="marker", ref="e1"), text(10, 50),
                     scale=scale, anchors=(("e1", 1950.0),), elements=("e1",))
        self.assertEqual(self.codes(moved), ["I6"])

    def test_i7_element_without_label_or_note(self):
        self.assertEqual(self.codes(hand(text(10, 50), elements=("e1", "lost"))), ["I7"])

    def test_i7_group_labels_and_notes_count(self):
        group = text(10, 50, ref="a+b")
        note = text(10, 100, role="note", ref="c")
        self.assertEqual(self.codes(hand(group, note, elements=("a", "b", "c"))), [])

    def test_i9_break_inside_a_period(self):
        scale = Scale(((1800.0, 1900.0, 0.0, 200.0, False), (1900.0, 1950.0, 200.0, 240.0, True),
                       (1950.0, 2000.0, 240.0, 400.0, False)))
        clear = hand(text(10, 50), scale=scale, spans=(("p", 1800.0, 1890.0),), elements=("e1",))
        self.assertEqual(self.codes(clear), [])
        broken = hand(text(10, 50), scale=scale, spans=(("p", 1880.0, 1960.0),), elements=("e1",))
        self.assertEqual(self.codes(broken), ["I9"])


class TestScale(unittest.TestCase):
    def test_piecewise_linear_and_invertible(self):
        scale = Scale(((0.0, 10.0, 100.0, 200.0, False), (10.0, 90.0, 200.0, 240.0, True),
                       (90.0, 100.0, 240.0, 340.0, False)))
        self.assertEqual(scale.x(0.0), 100.0)
        self.assertEqual(scale.x(5.0), 150.0)
        self.assertEqual(scale.x(95.0), 290.0)
        for t in (0.0, 3.3, 50.0, 99.0):
            self.assertAlmostEqual(scale.t(scale.x(t)), t)
        self.assertEqual(scale.breaks, ((10.0, 90.0, 200.0, 240.0),))


# ──────────────────────────────────────────────────────────────
# Mise en page réelle
# ──────────────────────────────────────────────────────────────
OPTION_SETS = [
    LayoutOptions(),
    LayoutOptions(density="compact"),
    LayoutOptions(width_mode="fixed", width_px=1200),
    LayoutOptions(width_mode="fixed", width_px=900, density="compact"),
    LayoutOptions(theme="dark"),
    LayoutOptions(theme="print", axis_breaks="off"),
]


class TestFixtures(unittest.TestCase):
    def test_zero_violation_on_every_fixture_and_option_set(self):
        for path in VALID_FIXTURES:
            doc = load(path.name)
            for options in OPTION_SETS:
                with self.subTest(fixture=path.name, options=options):
                    result = tl.layout(doc, options, fake_measure)
                    self.assertEqual(violations(result), [])

    def test_every_element_is_represented(self):
        for path in VALID_FIXTURES:
            doc = load(path.name)
            result = tl.layout(doc, LayoutOptions(), fake_measure)
            ids = [e["id"] for k in ("eras", "periods", "events") for e in doc[k]]
            self.assertEqual(sorted(result.elements), sorted(ids), path.name)

    def test_markers_sit_exactly_on_their_dates(self):
        doc = load("mondialisation.json")
        result = tl.layout(doc, LayoutOptions(), fake_measure)
        markers = {p.ref: p for p in result.primitives if isinstance(p, Marker) and p.role == "marker"}
        self.assertTrue(result.anchors)
        for element_id, t in result.anchors:
            self.assertLessEqual(abs(markers[element_id].cx - result.scale.x(t)), 0.5)

    def test_determinism(self):
        for name in ("mondialisation.json", "dense_1945.json", "twelve_tracks.json"):
            doc = load(name)
            first = tl.layout(doc, LayoutOptions(), fake_measure)
            second = tl.layout(json.loads(json.dumps(doc)), LayoutOptions(), fake_measure)
            self.assertEqual(first.primitives, second.primitives, name)
            self.assertEqual((first.width, first.height), (second.width, second.height))

    def test_theme_changes_colours_only(self):
        doc = load("mondialisation.json")
        light = tl.layout(doc, LayoutOptions(), fake_measure)
        dark = tl.layout(doc, LayoutOptions(theme="dark"), fake_measure)
        self.assertEqual((light.width, light.height), (dark.width, dark.height))
        geometry = lambda layout: [(type(p).__name__, p.role, p.ref, p.bbox) for p in layout.primitives
                                   if p.role not in ("lane-bg", "era-band")]
        self.assertEqual(geometry(light), geometry(dark))

    def test_fixed_width_is_respected(self):
        result = tl.layout(load("mondialisation.json"), LayoutOptions(width_mode="fixed", width_px=1000),
                           fake_measure)
        self.assertEqual(result.width, 1000)

    def test_auto_width_stays_in_bounds(self):
        for path in VALID_FIXTURES:
            result = tl.layout(load(path.name), LayoutOptions(), fake_measure)
            self.assertGreaterEqual(result.width, tl.WIDTH_MIN, path.name)
            self.assertLessEqual(result.width, tl.WIDTH_MAX, path.name)

    def test_dense_fixture_falls_back_without_overlap(self):
        doc = load("dense_1945.json")
        result = tl.layout(doc, LayoutOptions(width_mode="fixed", width_px=900), fake_measure)
        self.assertEqual(violations(result), [])
        self.assertGreater(result.stats["notes"] + result.stats["grouped"], 0)
        noted = {p.ref for p in result.primitives if p.role == "note"}
        for note in result.notes:
            self.assertIn(note["ref"], noted)

    def test_same_date_events_share_a_marker(self):
        result = tl.layout(load("same_date.json"), LayoutOptions(), fake_measure)
        refs = {p.ref for p in result.primitives if p.role == "event-label"}
        self.assertIn("cee+euratom", refs)


class TestPeriods(unittest.TestCase):
    def periods_doc(self, spans):
        return ts.validate({
            "schema": ts.SCHEMA_ID, "title": "Périodes", "lang": "fr",
            "periods": [{"id": f"p{i}", "start": str(a), "end": str(b), "label": "A"}
                        for i, (a, b) in enumerate(spans)],
        })["normalized"]

    @staticmethod
    def max_clique(spans):
        points = sorted([(a, 1) for a, _ in spans] + [(b + 1, -1) for _, b in spans])
        best = level = 0
        for _, step in points:
            level += step
            best = max(best, level)
        return best

    def test_rows_equal_the_largest_overlap(self):
        rng = random.Random(7)
        for _ in range(20):
            # Débuts sur des dizaines, fins trois ans avant une dizaine : deux périodes
            # voisines laissent au moins deux ans (> 8 px) entre leurs emprises, et la
            # clique des intervalles est bien celle des emprises.
            spans = []
            for _ in range(rng.randint(1, 12)):
                a = rng.randint(180, 198) * 10
                spans.append((a, a + rng.randint(1, 4) * 10 - 3))
            result = tl.layout(self.periods_doc(spans), LayoutOptions(width_mode="fixed", width_px=2400),
                               fake_measure)
            self.assertEqual(violations(result), [])
            self.assertEqual(result.stats["period_rows"], [self.max_clique(spans)], spans)

    def test_long_label_goes_outside_or_to_a_note(self):
        doc = ts.validate({"schema": ts.SCHEMA_ID, "title": "x", "lang": "fr", "periods": [
            {"id": "p", "start": "1900", "end": "1901", "label": "Un libellé beaucoup trop long pour la barre"}]})
        result = tl.layout(doc["normalized"], LayoutOptions(), fake_measure)
        labels = [p for p in result.primitives if p.ref == "p" and p.role in ("period-label", "note")]
        self.assertTrue(labels)
        self.assertEqual(violations(result), [])


class TestAxisBreaks(unittest.TestCase):
    def test_long_gap_is_compressed(self):
        result = tl.layout(load("long_gap.json"), LayoutOptions(), fake_measure)
        self.assertTrue(result.scale.breaks)
        self.assertLessEqual(len(result.scale.breaks), tl.MAX_BREAKS)
        for t0, t1, x0, x1 in result.scale.breaks:
            self.assertAlmostEqual(x1 - x0, tl.BREAK_PX)
        self.assertTrue(any(p.role == "break" for p in result.primitives))

    def test_off(self):
        result = tl.layout(load("long_gap.json"), LayoutOptions(axis_breaks="off"), fake_measure)
        self.assertEqual(result.scale.breaks, ())

    def test_no_break_when_nothing_is_empty(self):
        result = tl.layout(load("mondialisation.json"), LayoutOptions(), fake_measure)
        self.assertEqual(result.scale.breaks, ())

    def test_never_inside_a_period_or_an_era(self):
        doc = load("long_gap.json")
        doc["eras"] = [{"id": "longue", "label": "Longue ère", "start": "-3000", "end": "1000",
                        "approx": False, "importance": 2, "origin": "text"}]
        result = tl.layout(doc, LayoutOptions(), fake_measure)
        self.assertEqual(violations(result), [])
        for t0, t1, _, _ in result.scale.breaks:
            self.assertFalse(t0 < 1001 and -2999 < t1)


class TestTicks(unittest.TestCase):
    def tick_labels(self, name, **options):
        result = tl.layout(load(name), LayoutOptions(**options), fake_measure)
        return [p.lines[0] for p in result.primitives if p.role == "tick-label"]

    def test_no_year_zero(self):
        labels = self.tick_labels("antiquite.json")
        self.assertTrue(labels)
        self.assertNotIn("0", labels)
        self.assertTrue(any("av. J.-C." in label for label in labels))

    def test_day_ticks_on_a_short_span(self):
        labels = self.tick_labels("short_span_days.json", width_mode="fixed", width_px=4000)
        self.assertTrue(any(label[:1].isdigit() and not label.isdigit() for label in labels), labels)


# ──────────────────────────────────────────────────────────────
# Fuzz
# ──────────────────────────────────────────────────────────────
WORDS = ("traité accords crise guerre paix réforme loi révolution empire marché banque "
         "monnaie tarif conférence sommet déclaration création fin début essor chute "
         "Élysée Œuvre «citation» <b>balise</b> & \"guillemets\" 漢字 𝛼 ÿ ŋ").split()


def random_label(rng, max_len=80):
    words = []
    while True:
        words.append(rng.choice(WORDS))
        label = " ".join(words)
        if len(label) >= rng.randint(1, max_len):
            break
    return label[:max_len].strip() or "x"


def random_date(rng, mode, base):
    if mode == "days":
        year, month = base, rng.randint(1, 12)
        return f"{year}-{month:02d}-{rng.randint(1, 28):02d}"
    if mode == "bc":
        year = -rng.randint(1, 3000)
        return str(year)
    if mode == "clustered":
        return f"{base + rng.randint(0, 3)}-{rng.randint(1, 12):02d}"
    year = base + rng.randint(0, 400)
    return str(year if year != 0 else 1)


def random_doc(seed):
    rng = random.Random(seed)
    n_tracks = rng.choice([0, 1, 2, 3, 4, 5, 8, 12])
    tracks = [{"id": f"t{i}", "label": random_label(rng, 40)} for i in range(n_tracks)]
    mode = rng.choice(["spread", "clustered", "days", "bc"])
    base = rng.randint(1500, 1900) if mode != "days" else 2008
    events = []
    for i in range(rng.randint(0, 150)):
        event = {"id": f"e{i}", "date": random_date(rng, mode, base), "label": random_label(rng),
                 "importance": rng.choice([1, 2, 2, 2, 3])}
        if rng.random() < 0.1 and mode in ("spread", "bc"):
            event["precision"], event["date"] = "century", str(rng.choice([-1, 1]) * rng.randint(1, 20) * 100 + 1)
        if rng.random() < 0.1:
            event["approx"] = True
        if rng.random() < 0.05:
            event["origin"] = "model"
        if tracks:
            event["track"] = rng.choice(tracks)["id"]
        events.append(event)
    periods = []
    for i in range(rng.randint(0 if events else 1, 12)):
        a = -rng.randint(1, 3000) if mode == "bc" else base + rng.randint(0, 400)
        b = a + rng.randint(0, 60)
        if a < 0 <= b:          # pas d'an 0 : la période reste avant notre ère
            b = -1
        period = {"id": f"p{i}", "start": str(a), "end": str(b), "label": random_label(rng)}
        if rng.random() < 0.1:
            period["start"], period["end"] = str(rng.randint(1900, 2020)), "present"
        if tracks:
            period["track"] = rng.choice(tracks)["id"]
        periods.append(period)
    doc = {"schema": ts.SCHEMA_ID, "title": random_label(rng, 120), "lang": rng.choice(["fr", "en"]),
           "as_of": "2026-09-28", "tracks": tracks, "events": events, "periods": periods}
    report = ts.validate(doc)
    if not report["ok"]:
        raise AssertionError(f"graine {seed} : document de fuzz invalide {report['errors'][:3]}")
    return report["normalized"]


class TestFuzz(unittest.TestCase):
    SEEDS = range(300)

    def test_random_documents(self):
        for seed in self.SEEDS:
            doc = random_doc(seed)
            options = LayoutOptions(density=random.Random(seed).choice(["comfortable", "compact"]),
                                    width_mode="auto" if seed % 3 else "fixed")
            try:
                first = tl.layout(doc, options, fake_measure)
            except Exception as error:   # pragma: no cover — le message doit donner la graine
                raise AssertionError(f"graine {seed} : {type(error).__name__}: {error}") from error
            found = violations(first)
            self.assertEqual(found, [], f"graine {seed}")
            if seed % 10 == 0:
                second = tl.layout(doc, options, fake_measure)
                self.assertEqual(first.primitives, second.primitives, f"graine {seed} : non déterministe")


class TestPerformance(unittest.TestCase):
    def test_four_hundred_events(self):
        rng = random.Random(400)
        tracks = [{"id": f"t{i}", "label": f"Piste {i}"} for i in range(4)]
        events = [{"id": f"e{i}", "date": str(1800 + rng.randint(0, 200)), "label": random_label(rng, 40),
                   "track": f"t{i % 4}", "importance": rng.choice([1, 2, 3])} for i in range(400)]
        doc = ts.validate({"schema": ts.SCHEMA_ID, "title": "400", "tracks": tracks, "events": events})
        self.assertTrue(doc["ok"], doc["errors"][:3])
        start = time.perf_counter()
        result = tl.layout(doc["normalized"], LayoutOptions(), fake_measure)
        elapsed = time.perf_counter() - start
        self.assertEqual(violations(result), [])
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
