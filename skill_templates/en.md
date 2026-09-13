---
name: anki-flashcard-creator
description: Turn course paragraphs into importable Anki flashcards. Use this
  skill whenever the user sends a paragraph of course material (economics,
  sociology, philosophy, history, and so on) to be turned into flashcards.
  Trigger it too when the user says "generate flashcards", "make Anki cards",
  "turn this into cards", "make this into flashcards", or anything similar.
  This skill applies to any academic subject where structured content has to
  be memorised.
---

# Anki flashcard generator

Convert each paragraph of course material the user sends into Anki cards —
exhaustively, precisely, and in a consistent structure.

## Operating rules

### 1. Generate immediately
Whenever the user sends a paragraph, produce the cards straight away. Never
write an introduction, a confirmation, or a closing remark. Output only the
card rows.

### 2. Nothing is dropped
Every fact, mechanism, figure, date, author and concept in the paragraph becomes
a card. Nothing is set aside as "minor".

### 3. One idea per card
A card whose answer needs an "and" is two cards. The question must be answerable
without seeing the paragraph.

### 4. Works and articles
If the paragraph mentions a book or an article, always produce:
- a normal card on its content or thesis;
- a dedicated card for memorising the work itself, in both directions
  (author → thesis, and thesis → work).

Example fronts for the dedicated cards:
- `What is the central thesis of [Author] in [Work] ([Year])?`
- `In which work does [Author] develop [thesis]?`

## Output format — this is the contract

One row per card, two columns separated by a tab:

    FRONT<TAB>BACK

- No header row: the application adds `#separator:tab`, `#html:true` and
  `#deck column:1` itself, along with the deck column.
- No preamble, no commentary, no markdown fences.
- All the HTML of a card fits on one line: a line break inside a cell splits
  the card in two.

## HTML formatting

Cards are raw HTML with inline CSS. Keep the same convention across a whole deck
so the cards look alike:

| Element | Tag |
|---|---|
| Dates | `<span style="color: red; font-weight: bold; text-decoration: underline;">1929</span>` |
| Quotes | `<span style="background-color: plum; font-style: italic;">"…"</span>` |
| Works | `<span style="background-color: yellow; font-style: italic;">Title (Year) — Author</span>` |
| Articles | `<span style="background-color: yellow;">"Title" (Year) — Author</span>` |
| Theory, key concept | `<span style="color: red; font-weight: bold;">term</span>` |
| Lists | `<ul><li>…</li><li>…</li></ul>` |
| Maths | `<anki-mathjax>Y = A K^\alpha L^{1-\alpha}</anki-mathjax>` |

For a display formula: `<anki-mathjax block="true">…</anki-mathjax>`.
MathJax ships with Anki and needs nothing installed, unlike `[latex]…[/latex]`,
which requires a LaTeX distribution on the machine.

## Images and tables — required convention

The paragraph may contain `[IMAGE n]` markers (with a description) and
`[TABLE n]` markers (with the table in markdown).

- To show an image, write exactly `{{IMG:n}}` where it belongs.
- To reuse a table, write exactly `{{TABLE:n}}`.
- NEVER write an `<img>` tag and NEVER invent a filename: the application
  substitutes these markers with the real file at export time, and a
  hand-written tag points at nothing.
- A chart or diagram usually deserves its own card: the question on the front,
  `{{IMG:n}}` plus the interpretation on the back.
- A data table deserves one whole-table recall card (`{{TABLE:n}}` on the back)
  AND targeted cards on the striking values.
- If an image has no description, do not guess what it shows.

## Examples of well-formed cards

Concept:

    What is creative destruction according to Schumpeter?	The process by which <span style="color: red; font-weight: bold;">innovation destroys established economic structures</span> in order to create new ones. Set out in <span style="background-color: yellow; font-style: italic;">Capitalism, Socialism and Democracy (1942) — Schumpeter</span>.

Dedicated card for a work:

    In which work does Schumpeter develop creative destruction?	<span style="background-color: yellow; font-style: italic;">Capitalism, Socialism and Democracy</span> (<span style="color: red; font-weight: bold; text-decoration: underline;">1942</span>)

List:

    What are the three functions of money?	<ul><li>Unit of account</li><li>Medium of exchange</li><li>Store of value</li></ul>

Formula:

    What is the production function in the Solow model?	<anki-mathjax>Y = A K^\alpha L^{1-\alpha}</anki-mathjax> where <ul><li><b>Y</b> = output</li><li><b>K</b> = capital</li><li><b>L</b> = labour</li><li><b>A</b> = total factor productivity</li></ul>

Image:

    What does the Phillips curve show over 1960-1970?	{{IMG:1}} A downward-sloping relationship between <span style="color: red; font-weight: bold;">inflation</span> and <span style="color: red; font-weight: bold;">unemployment</span>.

## Check before emitting the cards

- [ ] Every piece of information in the paragraph is covered by at least one card
- [ ] Works and articles have their extra dedicated cards
- [ ] All HTML is inline, no line break inside a cell
- [ ] The separator is a tab, and there are exactly two columns
- [ ] No header row
- [ ] No commentary around the cards
