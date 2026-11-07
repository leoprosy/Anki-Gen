# Ankigen Local Agent — Implementation Plan

> Source: two pieces of feedback on the Reddit thread (u/AnshumanSachdeva, u/hamanovich), applied to this codebase.
> Status: **proposal**. Phase 0 is a go/no-go gate: nothing after it is built until the spike numbers are in.

**Goal:** Ankigen generates the cards itself, on the user's GPU, with no copy/paste and no account. The user imports a `.docx`, clicks *Generate*, reviews the cards and exports. The copy/paste-to-Claude path stays as a manual fallback.

**The two rules taken from the feedback, and which parts of the plan they drive:**

1. **The model returns objects. The code writes the file.** The model never produces TSV. It returns JSON that follows a fixed schema (`{"cards":[{"front","back"}]}`). Ankigen stores the cards as objects and builds the TSV only at export time. The export cleans every field and picks the separator, so a tab or a newline inside a field can no longer shift a column. This rule applies to **every** path, manual Claude included. It fixes a bug class on its own, even if nothing local is ever shipped.
2. **The runtime enforces the format.** llama.cpp constrains decoding with a grammar: a JSON schema, compiled internally to GBNF. Ollama and LM Studio expose the same feature as `format` / `response_format: json_schema`. Once malformed output cannot be generated at all, the model only has to be good at *extraction*. Reliable *formatting* no longer matters. That is why a local Qwen3 or Mistral Small becomes a realistic alternative to Claude for this task.

---

## 0. Where the code is today (what changes and why)

| Today | Problem | After |
|---|---|---|
| The model answers in TSV. `parse_tsv_response` ([build_anki_csv.py](../../../build_anki_csv.py)) splits on the first tab and falls back to a comma. | Any tab or newline inside a field corrupts the card. The comma fallback cuts HTML at its first comma. Each chunk stores only the raw string (`prompt["response"]`). | Each chunk stores `cards: [{front, back, ...}]`. The raw text is kept only for audit. TSV exists only inside `tsv_bytes()`. |
| The user copies the chunk, pastes it into Claude, then pastes the answer back ([static/app.js](../../../static/app.js), dock *Copy / Paste / Save & next*). | Every chunk needs a manual round trip. | A background job generates the chunks one after another. The user reviews the finished ones while the rest are still generating. |
| The formatting rules live in a Skill that the user installs in Claude ([skill_templates/](../../../skill_templates/)). | The app has no system prompt of its own, so it cannot drive a model itself. | Versioned prompt templates ship in the app (`prompt_templates/{lang}/`), with few-shot examples. The Skill template still exists for the manual path, and it now asks for JSON. |
| The model writes inline CSS by hand (`<span style="color: red; ...">`). | That is costly in tokens and hard for small models. The same element comes out styled differently from card to card. | The model writes **semantic tags** (`<concept>`, `<date>`, `<work>`, `<quote>`). Code turns them into inline CSS at export. Styling becomes a setting instead of a prompt rule (Phase 5, optional). |

Current invariants that must survive:

- `{{IMG:n}}` / `{{TABLE:n}}` placeholders are resolved by [render.py](../../../render.py) `resolve_placeholders`, and the model never sees a filename. This design is correct and stays unchanged. Only the check moves earlier: a placeholder with no matching block now triggers an automatic **retry**, not just a line in the export report.
- The deck path comes from headings (`prompt["deck"]`). It is unchanged.
- Everything is local. The local model runs on `127.0.0.1` too. The only new network traffic is the one-time runtime/model download, started explicitly by the user.

---

## 1. Options explored

### 1.1 Which runtime

| Runtime | Structured output | Windows | Install for the user | Verdict |
|---|---|---|---|---|
| **llama.cpp (`llama-server`)** | `response_format: json_schema`, `json_schema`, raw `grammar` (GBNF). Prompt-prefix cache (`cache_prompt`). MoE offload (`--n-cpu-moe`). | Native. Official binaries in several builds: CUDA, Vulkan, CPU. | Ankigen downloads a pinned ZIP (~30 MB for Vulkan, ~200 MB + ~400 MB cudart for CUDA) and launches it itself. | **Default "managed" path.** Full control: grammar, context, offload, lifecycle. |
| **Ollama** | `format: <json schema>` (native API) and `response_format` (OpenAI-compatible `/v1`). Uses the llama.cpp grammar under the hood. | Native, good GPU detection. | The user installs Ollama separately. Ankigen can then run `pull` through the API. | **"Bring your own" path, supported from day one.** It is the most common install for people who already run local models. |
| **LM Studio** | `response_format: json_schema` on `/v1`. | Native. | A separate GUI app. | Supported through the same OpenAI-compatible adapter. No dedicated code. |
| **vLLM** (xgrammar) | Excellent JSON schema support. | **No native Windows build**: WSL2 + CUDA only. | Heavy: Docker/WSL, Python, CUDA. | **Not recommended.** vLLM is built for multi-user throughput, and Ankigen is a single-user desktop app. Still reachable as a "custom OpenAI-compatible endpoint" for Linux users, at no extra cost. |
| Embedded Python bindings (`llama-cpp-python`) | GBNF | Painful CUDA wheels. | It would bloat the PyInstaller sidecar by hundreds of MB and would break the app.zip update model (see §6). | **Rejected.** |

**Decision:** write **one** client for the OpenAI-compatible protocol (`POST /v1/chat/completions` with `response_format: {type: "json_schema", ...}`). It covers llama-server, Ollama, LM Studio and vLLM. Add a small native Ollama adapter only if Phase 0 shows that `/v1` is less reliable than `format` (it was for older versions). The managed llama-server is simply one more endpoint that Ankigen starts itself.

### 1.2 Which models (target: RTX 4070 Ti, 12 GB VRAM)

Filtered for: Apache-2.0 licence (redistributable and downloadable without friction), good French, and a GGUF build available.

| Tier | Model (GGUF, Q4_K_M) | File size | Fit on 12 GB | Notes |
|---|---|---|---|---|
| **Recommended ≥12 GB VRAM + ≥32 GB RAM** | Qwen3-30B-A3B-Instruct-2507 | ~18.6 GB | Partial: attention on GPU, some experts on CPU (`--n-cpu-moe`) | MoE with 3B active parameters, so it stays fast despite the offload. It is the "Qwen3 30B" from the first comment. Use the non-thinking Instruct variant: it does not waste tokens on `<think>`. |
| Alternative, French-heavy courses | Mistral-Small-3.2-24B-Instruct-2506 | ~14.3 GB | Partial offload (dense model, so slower) | Mentioned in the first comment. Likely better French wording. Compare in Phase 0 on a real ESH course. |
| **Fully on GPU, 12 GB** | Qwen3-14B | ~9 GB | Yes | Disable thinking (`/no_think` or `chat_template_kwargs.enable_thinking=false`). Safest choice if RAM < 32 GB. |
| 8 GB | Qwen3-8B | ~5 GB | Yes | Acceptable for simple chunks. |
| CPU / ≤6 GB | Qwen3-4B-Instruct-2507 | ~2.5 GB | Yes | Always valid JSON thanks to the grammar, but the content is noticeably thinner. Show a quality warning in the UI. |
| (Phase 5) vision | Qwen2.5-VL-7B / Qwen3-VL (+ `mmproj`) | ~5–6 GB | Yes | Only used to **draft alt text** for images that have none. The app already flags these (`missing_alt_count`). |

These are estimates. Phase 0 measures the real speed and quality. The list lives in a data file (`model_catalog.json`, §4.6), so it can be updated through an app update without touching the code.

### 1.3 Where the model's formatting discipline comes from

Three layers, cheapest first:

1. **Constrained decoding (runtime).** A JSON schema is sent with every request. llama.cpp builds the grammar, so tokens that break the schema are masked out. Bounds come from `maxItems` (stops runaway loops) and `maxLength` per field. `additionalProperties: false`. Result: the JSON is **always** parseable and **always** has the right shape.
2. **Fixed prompt + few-shot (prompt).** This is the Reddit recommendation. The system prompt and examples are identical for every chunk, so llama.cpp reuses the prefix KV cache and only the chunk itself gets re-processed.
3. **Semantic validation + retry (code).** Unknown placeholders, an unused image/table, empty or duplicate cards, a card longer than N characters. On a problem, run one retry with the feedback appended to the conversation ("`{{IMG:3}}` does not exist in this paragraph; available: `{{IMG:1}}`"). Maximum 2 retries, after which the chunk goes to `error` with the reason shown.

Optional, stricter layer: a **hand-written GBNF** where JSON strings may not contain a tab or a newline (`\t`, `\n`, or their `\\t` / `\\n` escapes). llama-server accepts it through `grammar`. This goes beyond the JSON schema, which cannot express that constraint cleanly. The export sanitiser removes these characters anyway (§4.1), so this layer is defence in depth only, and it only applies to the managed path.

### 1.4 Execution model inside the app

| Option | Pros | Cons |
|---|---|---|
| Blocking synchronous calls from the browser, one chunk per click | Trivial | Holds a Waitress thread for ~30–60 s. Closing the tab loses everything. No "Generate all". |
| **Background thread inside the Flask process + persisted queue** | No new dependency. Resumes after a restart, because state lives in the project JSON. Fits Waitress (4 threads). | Needs a lock around project reads and writes. |
| Separate worker process / Celery / RQ | Isolation | Overkill for a single user, and a new dependency. Rejected. |

**Decision:** a single worker thread (`jobs.py`) runs chunks **sequentially**, because the GPU cannot generate two at once. Chunk status is persisted after every step. The UI polls `GET /api/jobs/<project>` every second. SSE would be possible with Waitress but adds complexity for no gain here.

---

## 2. The new workflow (user side)

```
Import .docx ──► Parse (unchanged) ──► Generate ──► Review ──► Export
                                          │            │
                                          │            ├─ edit a card (front/back fields)
                                          │            ├─ delete / add a card
                                          │            ├─ "Regenerate this chunk"
                                          │            └─ Approve (= done)
                                          │
                                          ├─ Local (managed llama.cpp)   ← default when installed
                                          ├─ Local (Ollama / LM Studio / custom endpoint)
                                          └─ Manual (copy/paste Claude, JSON answer; TSV still accepted)
```

**Chunk states** (replace `pending | done`):

`pending` → `queued` → `generating` → `review` (cards generated, not yet approved) → `done` (approved)
plus `error` (with reason + retry button) and `skipped` (the user chose to leave it out).

Export keeps its `only_done` option, and gains an "include `review`" choice, which is the default in "I trust the model" mode.

**Screens:**

1. **First launch / Settings › Local AI**: short wizard.
   - Hardware detection (GPU, VRAM, RAM, free disk space) → recommended model, highlighted.
   - "Install" button → downloads runtime + model with progress, pause/resume, and a checksum check.
   - Or "I already have Ollama / LM Studio" → URL field (`http://127.0.0.1:11434`), a *Test* button that lists available models, and a model picker.
   - Or "No local AI" → manual mode, same as today.
2. **Work view** ([templates/work.html](../../../templates/work.html)), reworked:
   - Topbar: a **Generate all** button (or *Resume* / *Pause*) with a global progress bar (`12/48 · ~18 min left`).
   - Rail: per-chunk status icon (queued / spinner / to review / ✓ / ⚠).
   - Right pane: a **card editor** replaces the textarea as the main view. It shows a list of cards, each with an editable *Front* and *Back* field, a live Anki render, and delete/reorder. The *Raw* tab stays for manual paste (JSON or TSV) and for power users.
   - Dock: `Regenerate` · `Approve & next` (Ctrl+Enter) · `Prev/Next`. In manual mode, *Copy / Paste* replace *Regenerate*.
3. **Help** ([templates/help.html](../../../templates/help.html)): split into "Local mode" and "Manual mode (Claude)". The Skill template now asks for JSON.

---

## 3. Data model v3

`PROJECT_VERSION = 3` in [project_store.py](../../../project_store.py). Migration happens on the fly in `normalize()`, following the v1→v2 pattern.

```jsonc
{
  "version": 3,
  "deck_prefix": "Economics",
  "source": "CH8.docx",
  "assets": { ... },                        // unchanged
  "generation": {                           // new, project-wide defaults
    "provider": "managed" | "endpoint" | "manual",
    "model": "qwen3-30b-a3b-instruct-2507-q4_k_m",
    "prompt_version": "fr-2026-10-01"
  },
  "prompts": [{
    "id": 3, "deck": "...", "blocks": [...], "assets": [...], "prompt": "...",   // unchanged
    "status": "review",
    "cards": [
      { "id": "c_9f2a…", "front": "...", "back": "...",
        "origin": "local:qwen3-30b-a3b" | "manual" | "user",
        "edited": false }
    ],
    "response": "...",                       // legacy / raw text of the last manual paste
    "last_run": {                            // audit + debugging
      "model": "...", "prompt_version": "...", "at": "2026-10-02T14:03:11Z",
      "attempts": 1, "duration_ms": 41230, "tokens_out": 1180,
      "error": null, "raw": "{\"cards\":[...]}", "warnings": ["unused {{TABLE:1}}"]
    }
  }]
}
```

- **v2→v3 migration:** `cards = [{front: q, back: a, origin: "manual"} for q, a in parse_tsv_response(response)]`. Status: `done` stays `done`, `pending` with a response becomes `review`. `response` is kept, so the migration is lossless and reversible.
- **Stable `card.id`**: a UUID, or a hash of (project, chunk, index) at creation time. It is used for UI editing, and later for Anki's `#guid column` (§4.1). With it, re-importing an updated deck **updates** the notes instead of duplicating them.
- **Concurrent writes:** today, every endpoint does `load → modify → save` with no lock. Once the worker writes in the background while the user edits, that is a lost-update race. Add a per-project `threading.Lock` in `project_store` (`with project_lock(pid): ...`). Also switch `save_project_file` to an **atomic** write (tempfile + `os.replace`, as [settings.py](../../../settings.py) already does), because a project file is now written dozens of times per session.

---

## 4. Implementation, module by module

New modules stay flat at the root, following the repo's style.

### 4.1 `cards.py`: card contract (no network, no Flask)

- `CARD_SCHEMA`: the JSON schema sent to the runtime.
  ```json
  {"type":"object","additionalProperties":false,"required":["cards"],
   "properties":{"cards":{"type":"array","minItems":1,"maxItems":40,
     "items":{"type":"object","additionalProperties":false,"required":["front","back"],
       "properties":{"front":{"type":"string","minLength":3,"maxLength":400},
                     "back":{"type":"string","minLength":1,"maxLength":2000}}}}}}
  ```
  (Bounds are tuned in Phase 0. `maxItems` scales with chunk length; see `generator.py`.)
- `validate(obj) -> (cards, errors)`: a hand-written validator of about 40 lines. **No `jsonschema` dependency** (see §6).
- `sanitize_field(s)`: `\r\n|\r|\n` → `<br>`, `\t` → space, strip, collapse whitespace, strip Markdown fences if present. It is called **once, at write time** (export), not on the model's output: the raw text stays intact for audit.
- `parse_manual(text) -> (cards, errors)`: accepts (1) the JSON of the contract, (2) a JSON array of `[front, back]`, (3) as a last resort, the legacy TSV via `parse_tsv_response`. This is what the *Paste* button uses.
- `check_placeholders(cards, chunk) -> {unknown: [...], unused: [...]}`: reuses `render.chunk_placeholder_map` and `PLACEHOLDER_RE`.
- `dedupe(cards)`: normalised front text + near-identical back → drop.

**Export** ([project_store.py](../../../project_store.py) `export_rows`, [app.py](../../../app.py) `tsv_bytes`): iterate over `prompt["cards"]`, apply `sanitize_field` to each value, and **drop the comma fallback entirely**. Optionally add a 4th column plus a `#guid column:4` header for stable updates. [build_anki_csv.py](../../../build_anki_csv.py) keeps `parse_tsv_response` only for migration and legacy paste.

### 4.2 `prompt_templates/{en,fr}/`: fixed prompt + few-shot

- `system.md`: rules taken from `skill_templates/*.md` (exhaustiveness, one idea per card, works in both directions, placeholders), **minus** everything about TSV/tabs/lines, which is now the grammar's job.
- `examples.json`: 3–4 pairs of (short chunk → `{"cards":[...]}`) covering concept, work, table+image, formula. They are injected as user/assistant turns (real few-shot, not text inside the system prompt).
- `PROMPT_VERSION` recorded in `last_run`, so that output can be traced back to a prompt version.
- Settings: a **"Custom instructions"** field appended to the end of the system prompt (level of detail, subject, tone). It replaces the Skill for local users.

### 4.3 `llm_client.py`: a single OpenAI-compatible client

- `stdlib` only: `urllib.request` + `json`. It is already bundled for `updater.py`.
- `chat(endpoint, model, messages, schema, *, api_key=None, max_tokens, temperature=0.3, timeout, cancel_event) -> (text, usage)`.
  - Sends `response_format: {"type":"json_schema","json_schema":{"name":"cards","strict":true,"schema":CARD_SCHEMA}}`.
  - Managed llama-server: also sends `cache_prompt: true`, and optionally the stricter `grammar` (§1.3).
  - Streaming (`stream: true`, reading SSE lines) to show progress (tokens/s) and to support **cancellation** mid-generation.
- `list_models(endpoint)` → `GET /v1/models` (llama-server, LM Studio, vLLM) or `GET /api/tags` (Ollama).
- `health(endpoint)`.
- A `FakeClient` for tests (returns canned JSON, can simulate errors, invalid JSON and slowness).

### 4.4 `generator.py`: one chunk → validated cards

```
generate_chunk(project, prompt, cfg, client, cancel) -> result
  messages = system(lang, custom_instructions) + few_shot(lang) + user(prompt["prompt"])
  for attempt in 1..3:
      text   = client.chat(..., schema=schema_for(prompt))
      obj    = json.loads(text)                 # constrained → should never fail; catch anyway
      cards, errs = cards.validate(obj)
      ph     = cards.check_placeholders(cards, prompt)
      if not errs and not ph.unknown: break
      messages += [assistant(text), user(feedback(errs, ph))]
  return cards (deduped), warnings (ph.unused, …), last_run
```

- `schema_for(prompt)`: `maxItems` proportional to text length (e.g. `clamp(4, 40, words/25)`), which avoids loops on short chunks.
- **Long chunks:** estimate tokens (~chars/3.5). Above a budget (e.g. 6k tokens), split on block boundaries (text paragraphs), keeping each image/table with its surrounding text. Generate in sub-batches, merge, then dedupe. `n` placeholders are not renumbered, because the resolution map stays the full chunk's map.
- Qwen3 thinking disabled (`chat_template_kwargs: {enable_thinking: false}` + `/no_think`, or simply the `-Instruct-2507` models).

### 4.5 `jobs.py`: queue and worker

- `JobManager` singleton: one daemon thread, `queue.Queue` of `(project_id, chunk_id)`, `threading.Event` for pause and cancel.
- `enqueue(project, chunk_ids | "all_pending")` marks chunks `queued` and persists them. At startup, `resume()` re-queues anything left in `queued`/`generating` (crash or app closed).
- After each chunk: write `cards`, `status="review"`, `last_run`, under the project lock.
- In-memory state exposed at `GET /api/jobs/<pid>`: `{running, paused, current, done, total, eta_s, tokens_per_s, errors}`. The ETA is a moving average of `duration_ms` per chunk.
- Never touches a chunk that is `done`, or `review` with `edited` cards, unless regeneration is explicit, **with a confirmation** ("You edited 3 cards in this chunk, overwrite them?").

### 4.6 `runtime_manager.py` + `hardware.py` + `model_catalog.json`: the "install a local agent" part

**`hardware.py`** (stdlib + `subprocess`/`ctypes`):
- GPU/VRAM: `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader`. If absent, AMD/Intel is assumed via Vulkan and VRAM is unknown, so the UI asks.
- RAM: `ctypes.windll.kernel32.GlobalMemoryStatusEx`. Disk: `shutil.disk_usage`.
- `recommend(hw, catalog) -> entry` + reason text ("18.6 GB model, 12 GB VRAM + 32 GB RAM → MoE offload").

**`model_catalog.json`** (shipped in app.zip, so updatable):
```jsonc
{ "runtime": {
    "llama_cpp_build": "bXXXX",
    "variants": {
      "cuda":   {"url": "https://github.com/ggml-org/llama.cpp/releases/download/bXXXX/llama-bXXXX-bin-win-cuda-12.4-x64.zip", "sha256": "…",
                 "extra": [{"url": "…/cudart-llama-bin-win-cuda-12.4-x64.zip", "sha256": "…"}]},
      "vulkan": {"url": "…/llama-bXXXX-bin-win-vulkan-x64.zip", "sha256": "…"},
      "cpu":    {"url": "…/llama-bXXXX-bin-win-cpu-x64.zip", "sha256": "…"} } },
  "models": [
    { "id": "qwen3-30b-a3b-instruct-2507-q4_k_m", "label": "Qwen3 30B-A3B (recommended)",
      "url": "https://huggingface.co/<org>/<repo>/resolve/<commit>/<file>.gguf", "sha256": "…", "size": 18600000000,
      "min_vram_gb": 10, "min_ram_gb": 32, "moe": true, "ctx": 16384,
      "server_args": ["--n-cpu-moe", "{auto}", "-fa", "on", "--jinja"], "license": "Apache-2.0" },
    …
  ] }
```
- URLs are **pinned to a commit** (HF `resolve/<sha>`, llama.cpp build tag), with a mandatory **SHA-256**. Nothing is downloaded from a URL that is not in the catalog. This is the security rule that makes "Ankigen downloads and runs an executable" acceptable.

**`runtime_manager.py`:**
- `install_runtime(variant)` / `install_model(id)`: download to `DATA_DIR/runtime/` and `models_dir` (setting, default `DATA_DIR/models`, **changeable**: 18 GB does not always fit on C:). Resumable via HTTP `Range` (`.part` file), checks free space first, verifies SHA-256, then renames atomically. Progress is exposed at `GET /api/runtime/status`.
- CUDA vs Vulkan choice: CUDA if `nvidia-smi` responds with driver ≥ the required version, otherwise Vulkan. There is also a "Use Vulkan" option in case of trouble.
- `start(model_id)`: free port (reuses `launcher.find_free_port`, range 5200–5300), launches `llama-server -m … --host 127.0.0.1 --port P --api-key <random> -c <ctx> -ngl 999 [server_args]`. `{auto}` for `--n-cpu-moe` is computed from VRAM (table in the catalog, adjusted after Phase 0). Waits on `GET /health`.
- **Process lifetime (important):** Tauri kills `flask-server` on exit ([src-tauri/src/lib.rs](../../../src-tauri/src/lib.rs) `child.kill()`), but a grandchild `llama-server` would survive and keep 12 GB of VRAM. Fix: attach llama-server to a **Windows Job Object** with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (via `ctypes`), so it dies with the sidecar even if the sidecar is killed abruptly. Also stop after **N minutes of inactivity** (default 10) to free VRAM for games and other apps, with a transparent restart on the next job.
- Logs from llama-server → `DATA_DIR/logs/llama-server.log` (rotated), linked from Settings for bug reports.

### 4.7 Flask routes (new, in [app.py](../../../app.py))

| Route | Role |
|---|---|
| `GET  /api/ai/status` | Configured provider, runtime installed/running, model, hardware, recommendation |
| `POST /api/ai/config` | Save provider/endpoint/model/custom instructions (via `settings.py`, new validated keys) |
| `POST /api/ai/test` | Test an endpoint: health + model list + one tiny constrained request |
| `POST /api/runtime/install` · `/pause` · `/cancel` · `GET /api/runtime/status` | Download runtime/model |
| `POST /api/jobs/<pid>/start` `{chunks: "pending" \| [ids]}` · `/pause` · `/resume` · `/cancel` · `GET /api/jobs/<pid>` | Generation queue |
| `POST /api/chunk/<pid>/<id>/regenerate` | Regenerate one chunk (with overwrite confirmation) |
| `PUT  /api/chunk/<pid>/<id>/cards` | Save the edited cards |
| `POST /api/chunk/<pid>/<id>/approve` | `review` → `done` |
| `POST /api/save/<pid>` (existing) | Manual path: now goes through `cards.parse_manual`, fills `cards` |
| `POST /api/preview/<pid>` (existing) | Accepts `cards` (preferred) or `response` (legacy) |

**Local security:** these routes launch processes and downloads. Add a random per-session token (generated at startup, injected into `base.html`, required in an `X-Ankigen-Token` header on every mutating `/api/ai|runtime|jobs` route). A page open in the browser cannot then trigger an 18 GB download or a process on `127.0.0.1:5000`. Keep `127.0.0.1` binding for the llama-server, with its `--api-key`.

### 4.8 Front end

- [static/app.js](../../../static/app.js) is 619 lines in one IIFE. Split out `static/cards-editor.js` (card list, editing, render) and `static/jobs.js` (polling, progress, generation buttons) so it stays readable. Stay vanilla, with no framework or build step, consistent with the repo.
- Card editor: one card = two `contenteditable` fields, or `textarea` + live render (recommended: textarea in edit mode, render on blur, same as the current *Text / Cards* toggle). Placeholder chips (`renderInsertBar`) insert into the focused field.
- Follow [design.md](../../../design.md): the dock stays always visible, one accent colour, no borders.
- New `settings.html` section: "Local AI" (status, wizard, advanced: endpoint, ctx, temperature, n-cpu-moe, idle timeout, models folder, custom instructions).
- i18n: every new key in `locales/en.json` **and** `locales/fr.json` (the parity test in `tests/test_i18n.py` enforces it).

---

## 5. Phases (each phase = one or more mergeable PRs)

### Phase 0: Spike and measurement (≈2 days) — **GO/NO-GO gate**
This answers the Reddit question ("Have you tested the same course chunk with any local models yet?") before building anything.
- [ ] Install Ollama by hand + pull `qwen3:30b-a3b-instruct-2507` (Q4), `qwen3:14b`, `mistral-small3.2:24b`. Also try llama-server directly with `--n-cpu-moe`.
- [ ] `tools/eval_local.py` (not shipped): takes an existing project JSON (one of the user's courses already done with Claude) and runs N chunks through each model with a draft `system.md` + few-shot + schema.
- [ ] Measure per model: % valid JSON (expected 100%), % chunks with unknown placeholders, cards/chunk vs Claude, s/chunk, tok/s, peak VRAM, and do a **manual side-by-side quality review** on ~10 chunks (FR and EN).
- [ ] Also test JSON through the Claude web UI with the updated Skill, to confirm the manual path still works.
- **Gate:** if the best local model covers ≥ ~80% of the facts Claude covers on the sample → continue. Otherwise, ship only Phases 1 and 3 (JSON contract + editor, still valuable) and wait for better models.

### Phase 1: JSON contract and data model v3 (no AI yet)
- [ ] `cards.py` + tests (validate, sanitize, parse_manual JSON/TSV, placeholders, dedupe).
- [ ] `project_store`: v3, v2→v3 migration, per-project lock, atomic write, `export_rows` over `cards`, `#guid column`.
- [ ] `/api/save` and `/api/preview` go through `cards`. Remove the comma fallback from the export.
- [ ] `skill_templates/{en,fr}.md`: switch the "Output format" section to JSON (`{"cards":[{"front","back"}]}`, no fence).
- [ ] Tests: golden export test with fields containing `\t`, `\n`, `"` → still 3 columns, content preserved.
- *Delivers value on its own:* it closes the delimiter bug class described in the second comment, for manual users too.

### Phase 2: Generation through an existing endpoint (Ollama / LM Studio / custom)
- [ ] `llm_client.py` (+ `FakeClient`), `generator.py`, `prompt_templates/`, `jobs.py`.
- [ ] Routes `/api/ai/*`, `/api/jobs/*`, `/api/chunk/*/regenerate`. Session token.
- [ ] Minimal UI: Settings › Local AI (endpoint mode only) + *Generate all* button + rail statuses.
- [ ] Tests: generator with FakeClient (valid, invalid JSON then valid, unknown placeholder → retry → success, 3 failures → `error`), jobs (sequential order, pause, cancel, resume after "restart").

### Phase 3: Workflow rework (review-first UI)
- [ ] Card editor, `review` / `done` / `error` / `skipped` states, `Approve & next`, `Regenerate` with confirmation.
- [ ] Export: "include cards under review" option, export report with per-chunk warnings.
- [ ] `help.html` rewritten (local mode / manual mode), README/README.fr updated ("no API key" still holds).

### Phase 4: Managed installation ("install a local agent")
- [ ] `hardware.py`, `model_catalog.json`, `runtime_manager.py` (download with resume + SHA-256, CUDA/Vulkan choice, start/stop, Job Object, idle timeout, logs).
- [ ] First-launch wizard + install progress, with pause/resume.
- [ ] **New installer required** (see §6): hiddenimports for `ctypes`, `subprocess`, `hashlib`, `queue`, and `min_installer_version` in the update manifest.
- [ ] Manual tests on: 4070 Ti (CUDA), an AMD/Intel machine (Vulkan), a machine without a GPU (CPU + 4B model + warning).

### Phase 5: Refinements (optional, ordered by value)
- [ ] **Alt text through a vision model** for images without a description (the app already highlights them): "Suggest" button → the user validates.
- [ ] **Semantic tags** (`<concept>`, `<date>`, `<work>`, `<quote>`) + a "card style" setting that renders them as inline CSS. Easier for small models, and every card looks the same.
- [ ] Cloze cards (`type: "cloze"` in the schema, `#notetype` column).
- [ ] Direct push into Anki through AnkiConnect (optional) instead of TSV import.
- [ ] Optional cloud provider (Anthropic API with structured output) for users without a GPU. It reuses the `generator.py` interface. Off by default, to keep the "no key" promise.

---

## 6. Packaging and updates: the constraint most likely to be missed

The in-app updater ([updater.py](../../../updater.py)) replaces **only the Python sources** (`app.zip` → `%APPDATA%/AnkiGen/app`). The **interpreter and the third-party/stdlib modules** come from the PyInstaller executable, frozen at install time. Consequences:

1. **No new third-party dependency** (`jsonschema`, `httpx`, `psutil`, `requests`…). Anyone who updated through app.zip would get an `ImportError` at startup. Everything above is designed around the stdlib plus what is already bundled.
2. **Watch out for stdlib modules too:** PyInstaller only bundles the modules the *old* code imported. `ctypes`, `hashlib`, `queue` and `subprocess` are probably present (pulled in transitively), but that is not guaranteed. Actions:
   - add them explicitly to `hiddenimports` in [flask-server.spec](../../../flask-server.spec);
   - add `min_installer_version` to `version.json`/the release manifest. `updater.is_update_available` refuses an app.zip that needs a newer exe, and instead shows "Download the new installer";
   - guard the imports in `hardware.py` / `runtime_manager.py` (`try: import ctypes`), so the app **starts anyway** and only the local-AI features are disabled.
3. **The list of shipped modules is duplicated in three places:** `flask-server.spec` (`datas`), `.github/workflows/release.yml`, `.github/workflows/build-latest.yml`. Add `cards.py`, `llm_client.py`, `generator.py`, `jobs.py`, `runtime_manager.py`, `hardware.py`, `model_catalog.json`, `prompt_templates/` to all three. Better still, factor the list into a `bundle_manifest.txt` read by all three, plus a test that fails when a root `.py` imported by `app.py` is missing from it.
4. The runtime and the models are **never** in the installer (size). They are downloaded on demand into `DATA_DIR`, outside `app/`, so they survive updates. Uninstalling should offer to remove `DATA_DIR/models` (NSIS hook). Otherwise 18 GB is left behind.

---

## 7. Tests (unittest, as today)

| File | Covers |
|---|---|
| `tests/test_cards.py` | validate, sanitize_field (tab/newline/CRLF), parse_manual (JSON, array, legacy TSV, fences), check_placeholders, dedupe |
| `tests/test_project_v3.py` | v2→v3 migration (statuses, cards, response kept), atomic write, lock |
| `tests/test_export_tsv.py` | Golden export: exact column count whatever the content, `#guid column`, placeholders resolved |
| `tests/test_generator.py` | Retry with feedback, max attempts, long-chunk splitting, schema_for bounds (FakeClient) |
| `tests/test_jobs.py` | Order, pause/resume/cancel, resume after reload, never overwrites edited cards without force |
| `tests/test_llm_client.py` | Request format (response_format, cache_prompt), SSE parsing, cancellation, HTTP errors (local `http.server` in a thread) |
| `tests/test_hardware.py` | Parsing `nvidia-smi` output, recommend() on several profiles |
| `tests/test_runtime_manager.py` | Resume on `.part`, wrong SHA-256 rejected, URL outside the catalog refused, args generation |
| `tests/test_bundle_manifest.py` | Every shipped module is listed in the spec + both workflows |

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Local quality falls short of Claude on dense chunks | Phase 0 gate. Manual mode stays first-class. Per-chunk "Regenerate". Optional cloud provider in Phase 5. |
| The model loops or produces 40 near-identical cards | `maxItems` proportional to chunk length, `max_tokens`, moderate `repeat_penalty`, `dedupe`. |
| Unknown placeholders | Placeholder retry with feedback + existing export report. |
| The GPU is busy (game) / VRAM exhausted | Clear error message, Vulkan/CPU fallback option, idle timeout, "Pause" button. |
| Orphan llama-server after closing | Job Object `KILL_ON_JOB_CLOSE` + tracked PID + cleanup at startup (kill a stale PID recorded in `DATA_DIR/runtime/pid`). |
| 18 GB download on a small SSD | Size shown before starting, disk-space check, configurable models folder. |
| Antivirus flags a downloaded `llama-server.exe` | Official llama.cpp binaries, pinned, SHA-256 verified. Documented in the help page. |
| Update that needs a new exe | `min_installer_version` + guarded imports (§6). |
| Lost-update race (worker vs UI) | Per-project lock + atomic write (§3). |

---

## 9. Minimum viable order

If time is short: **Phase 0 → Phase 1 → Phase 2 (Ollama endpoint only) → Phase 3.** At that point the app works end to end for anyone with Ollama, and the "one-click install" (Phase 4) is a comfort layer on top of an architecture that already works.
