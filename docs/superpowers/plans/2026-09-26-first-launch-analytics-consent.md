# First-launch analytics choice plan

**Issue:** [#28](https://github.com/leoprosy/Anki-Gen/issues/28)
**Branch:** `feat/first-launch-analytics-consent`, from merged `origin/main`.
**Spec:** [First-launch analytics choice](../specs/2026-09-26-first-launch-analytics-consent-design.md)

## Global constraints

- English Conventional Commit; one issue and PR; no merge without user approval.
- Python 3.11+, unittest, vanilla JavaScript and CSS; no runtime dependency.
- Explicit Allow before tracking; no document content or personal keys in events.
- All new product text in both English and French.

## Tasks

- [x] Add failing settings and Flask route tests for the undecided state,
  refusal, acceptance, persistence, and unrelated settings saves.
- [x] Implement the bilingual panel, preference migration, settings handling,
  and failure feedback.
- [x] Build and inspect the executable. Test EN/FR, narrow layout, Allow,
  Decline, failed save, and an old Settings tab in headless Chrome without
  production ingestion. Include a screenshot.
- [x] Review the change independently, fix the stale Settings tab behavior,
  and rerun the relevant checks.
- [x] Commit, push, create and attach PR #29 for issue #28; verify CI.
- [x] Add two independent analytics categories in settings and telemetry, with
  tests proving event filtering, migration and queued-event removal on partial
  withdrawal. Add Customize to the panel while keeping one-click Allow all and
  Decline all. Update EN/FR copy and docs, rebuild and verify the packaged UI,
  then push to PR #29 and recheck CI.

## Execution record

- 152 Python tests and three JavaScript update tests passed. PyInstaller built.
- The packaged browser check confirmed both choices, French and English,
  mobile width, failed-save retry and no event state with ingestion disabled.
- Review found that an old Settings tab could overwrite another window's choice.
  The browser scenario reproduced the failure, then passed once unrelated
  Settings saves omitted analytics fields.
- PR #29 is attached. GitHub CI passed on Windows with Python 3.11 and 3.13.
- The category refinement passed Python and JavaScript tests and a
  packaged browser check in English and French, including granular acceptance,
  failed-save retry, narrow layout and stale Settings tabs. The screenshot now
  shows the expanded choices.
- Independent review found and verified fixes for offline delivery after a
  creation-only restart and retrying category purges after transient disk errors.
  Final checks passed 159 Python tests and three JavaScript tests; the packaged
  browser check was repeated after both fixes.
