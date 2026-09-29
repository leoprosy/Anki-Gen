<!--
Extraction prompt for timelines (contract ankigen.timeline/1), in English.

timeline_prompt.py splits this file into blocks: each block starts with a line that
holds nothing but an HTML comment "@name", and runs to the next one. It assembles them
according to the mode (strict or enriched), the strategy (one prompt, or paragraph by
paragraph) and the "I installed the Skill" option. The downloadable Skill is made of
the same blocks.

The {{variables}} are filled in by the code. The limits come from timeline_schema:
never copy them by hand. The example must stay valid (a test checks it), and the
French file must keep the same blocks.
-->
<!-- @intro -->
You are building a timeline to help a student review a course.

Your task: extract the chronology of the source text, and nothing beyond what it says. You return a single JSON object in the `{{schema}}` format, which the Ankigen app draws itself. You never produce SVG, HTML or coordinates.

<!-- @title -->
Timeline title: {{title}}

<!-- @strict -->
## Strict mode

- Every date must appear in the text, or follow directly from it ("three years later", right after a given date).
- Never invent a date, and never make a date more precise than the text does: "in 1947" gives "1947", never "1947-10-30".
- Do not add anything the text does not mention, even if it seems important to you. Every element has "origin": "text", the default value: you may leave it out.

<!-- @enriched -->
## Enriched mode

- First extract everything the text contains, following the strict mode rules: no invented date, no date more precise than the text.
- You may then add a few context dates that are essential to understand the passage, at most one for every five extracted elements. Mark them "origin": "model", without "source_quote": they will be flagged as "not from the course".

<!-- @contract -->
## JSON format

A single object, with these keys and no others:

- "schema": always "{{schema}}".
- "title": the timeline title, at most {{max_title}} characters.
- "lang": "{{lang}}", the language of the text.
- "tracks": 0 to {{max_tracks}} tracks. Each track: {"id", "label"}, with a label of at most {{max_track_label}} characters.
- "eras": 0 to {{max_eras}} eras, background bands spanning every track: {"id", "label", "start", "end"}, without "track". Two eras never overlap, but they may share the year where they meet.
- "periods": 0 to {{max_periods}} periods, spans drawn as bars: {"id", "track", "label", "start", "end"}.
- "events": 0 to {{max_events}} point events: {"id", "track", "label", "date"}.

There must be at least one event or one period.

Fields of eras, periods and events:

- "id": lowercase letters without accents, digits, "_" or "-", at most {{max_id}} characters. Unique across the whole document, tracks included.
- "track": the "id" of a track declared in "tracks". Required as soon as there are tracks, absent from eras.
- "label": at most {{max_label}} characters ({{max_era_label}} for an era).
- "importance": 1, 2 or 3 (2 by default).
- "approx": true for an approximate date.
- "precision": "day", "month", "year", "decade", "century" or "millennium". Not needed for a day, a month or a year: the date already says so.
- "description": at most {{max_description}} characters.
- "date_text": how the text words the date, at most {{max_date_text}} characters ("in the aftermath of the war").
- "source_quote": the excerpt of the text that supports the element, at most {{max_quote}} characters.
- "origin": "text" (default) or "model".
- "tags": at most {{max_tags}} keywords of at most {{max_tag}} characters.

## Writing dates

A date is always a string in straight double quotes:

- day "1971-08-15", month "1971-08", year "1971";
- before Christ, a negative year: "-44" means 44 BC. There is no year 0: "-1" is followed by "1";
- approximate date: "around 1450" gives "date": "1450" and "approx": true;
- decade: "the 1970s" gives "date": "1970" and "precision": "decade";
- century: the first year of the century, with "precision": "century". The 16th century starts in 1501: write "1501", not "1500". The 19th century gives "1801", the 5th century BC gives "-500";
- millennium: same rule with "precision": "millennium" (the 3rd millennium BC gives "-3000");
- ongoing period: "end": "present", only in "end";
- the end of a period is included: "start": "1939" and "end": "1945" cover the whole of 1945.

<!-- @rules -->
## Editorial rules

- Tracks: 2 to 5 thematic tracks (politics, economy, society…) or geographic ones. A single track if the passage covers a single theme. A track label is 1 to 3 words long.
- A point event is a date, a span is a period, and an epoch that frames everything else is an era.
- Labels of 2 to 8 words, without the date, and if possible without a conjugated verb: "Signing of the GATT", not "The GATT is signed in 1947".
- "importance": 3 for the turning points of the passage (at most one element in five), 2 for what matters, 1 for details.
- "source_quote": an excerpt of 5 to 25 words, copied verbatim from the source text. Do not rephrase it, translate it, or fix its spelling or punctuation.
- "description": one or two sentences that say why the element matters in this course.
- Tables in the text, in markdown, often hold chronologies: use them. The [IMAGE n] markers describe the figures of the course.

<!-- @example -->
## Example

Source text:

During the Cold War (1947-1991), Western Europe organised itself. The Treaty of Paris, signed on 18 April 1951, created the European Coal and Steel Community (ECSC). The Treaties of Rome of 25 March 1957 established the European Economic Community, whose customs union was completed in July 1968. From 1979 to 1998, the European Monetary System (EMS) limited fluctuations between currencies. The euro became the single currency on 1 January 1999.

Expected answer:

{
  "schema": "ankigen.timeline/1",
  "title": "European integration",
  "lang": "en",
  "tracks": [
    {"id": "institutions", "label": "Institutions"},
    {"id": "currency", "label": "Currency"}
  ],
  "eras": [
    {"id": "cold_war", "label": "Cold War", "start": "1947", "end": "1991",
     "source_quote": "During the Cold War (1947-1991), Western Europe organised itself"}
  ],
  "periods": [
    {"id": "ems", "track": "currency", "label": "European Monetary System", "start": "1979", "end": "1998",
     "importance": 2, "description": "It limits fluctuations between European currencies and paves the way for the single currency.",
     "source_quote": "From 1979 to 1998, the European Monetary System (EMS) limited fluctuations between currencies"}
  ],
  "events": [
    {"id": "ecsc", "track": "institutions", "date": "1951-04-18", "label": "Creation of the ECSC", "importance": 2,
     "date_text": "on 18 April 1951",
     "source_quote": "The Treaty of Paris, signed on 18 April 1951, created the European Coal and Steel Community"},
    {"id": "treaties_rome", "track": "institutions", "date": "1957-03-25", "label": "Treaties of Rome", "importance": 3,
     "description": "They found the EEC, the framework of European trade integration.",
     "source_quote": "The Treaties of Rome of 25 March 1957 established the European Economic Community"},
    {"id": "customs_union", "track": "institutions", "date": "1968-07", "label": "Completion of the customs union",
     "importance": 1, "source_quote": "whose customs union was completed in July 1968"},
    {"id": "euro", "track": "currency", "date": "1999-01-01", "label": "Birth of the euro", "importance": 2,
     "source_quote": "The euro became the single currency on 1 January 1999"}
  ]
}

<!-- @output -->
## Answer format

Answer with the JSON object only: no text before or after it, no code block.

<!-- @chunk -->
## This passage

The source text is only one paragraph of a longer course: the full timeline will be assembled from every paragraph.

- If it contains no date, still return the document, with empty lists. That is a normal answer: do not invent anything to fill them.

<!-- @chunk_tracks -->
- Tracks already used in this timeline: {{tracks}}. Reuse their "id" and label when they fit, and only create a new one if none fits.

<!-- @source -->
## Source text

<<<SOURCE
{{source}}
SOURCE>>>

<!-- @skill_strict -->
Use the "Ankigen timeline" Skill, in strict mode, to extract the timeline of the source text below.

<!-- @skill_enriched -->
Use the "Ankigen timeline" Skill, in enriched mode, to extract the timeline of the source text below.

<!-- @skill_lang -->
Language of the text: "{{lang}}".

<!-- @skill_header -->
---
name: ankigen-timeline
description: Extract the chronology of a course text as ankigen.timeline/1 JSON,
  for the Ankigen app, which draws the timeline. Use this skill whenever the user
  asks for an Ankigen timeline, or sends a text delimited by <<<SOURCE and
  SOURCE>>> and mentions the timeline.
---

# Ankigen timeline

The request states the mode: strict by default, or enriched.

<!-- @correction -->
Your JSON has the following errors:

{{errors}}

<!-- @correction_warnings -->
If you can, also fix these warnings:

{{warnings}}

<!-- @correction_end -->
Send back the complete corrected JSON, nothing else: no text before or after it, no code block.
