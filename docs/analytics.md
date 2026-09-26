# Private usage statistics

Ankigen sends optional usage events to PostHog. The owner views them in an
authenticated dashboard. Users of the desktop app do not need an account.
Documents, filenames, project IDs, questions, answers, prompts and clipboard
data are never event properties. There is no browser autocapture or replay.

## Configure builds

Use a separate **Ankigen** PostHog project within your existing account, with its
timezone set to your preferred reporting timezone. Daily activity uses that project's calendar.
Set these GitHub repository Actions variables:

| Variable | Value |
| --- | --- |
| `ANKIGEN_POSTHOG_TOKEN` | Public project token (`phc_…`) |
| `ANKIGEN_POSTHOG_REGION` | `eu` or `us` |

Only the public token belongs in the app. Personal API keys must never ship.
PyInstaller generates `analytics_config.json`; both release workflows include
it and the telemetry modules in `app.zip`. Missing configuration disables
reporting. The generated file is Git-ignored; no runtime dependency is added.
For a local build, set the same environment variables, then run:

```powershell
.venv/Scripts/python.exe scripts/configure_analytics.py
.venv/Scripts/pyinstaller.exe --noconfirm flask-server.spec
```

Development runs require `ANKIGEN_ANALYTICS_DEV=1` as well as explicit consent.
Use a separate test PostHog project so test events do not inflate real usage.

## Private dashboard

Create a temporary personal API key with `project:read`, `dashboard:read`,
`dashboard:write`, `insight:read` and `insight:write`, limited to Ankigen.
Replace `12345` below with the numeric project ID from PostHog settings:

```powershell
.venv/Scripts/python.exe scripts/setup_analytics_dashboard.py --project 12345 --region eu
```

The script prompts for the personal key without displaying it. Alternatively,
use `POSTHOG_PERSONAL_API_KEY` or the Git-ignored `.posthog-admin-key` file in the
repository root. It verifies that the project matches the configured public
token, creates nine insights, verifies public sharing is disabled and prints
the link. Rerunning reuses the managed dashboard and insights. A shared dashboard
is rejected. Preview the definitions without account access:

```powershell
.venv/Scripts/python.exe scripts/setup_analytics_dashboard.py --dry-run
```

Private dashboard access follows PostHog project membership. Keep the project
accessible only to you, or use an organization where you are the sole member.
Enable MFA and keep public sharing and embedding off. Revoke the temporary key
after setup and remove its local file. The owner scripts and personal keys are
excluded from installers and updater bundles.

Choose a retention period in PostHog appropriate for these statistics. Turning
reporting off clears pending events and stops collection; it does not delete
already received events. Person-profile processing and GeoIP enrichment are
disabled, but the receiving service still sees the connection's IP address.

## Metric definitions

| Event / chart | Meaning |
| --- | --- |
| `first_launch` | First consented observation of an installation data directory, including existing users receiving an update. Not an installer execution. |
| `app_opened` | Each successful page visit or product action. Update/version polling does not count. |
| Active installations | Distinct installation IDs today, or over 7/30 calendar days including today, in the project's timezone. Two computers can count as two installations for one person. |
| `project_created` | Successful DOCX parse and project save; `chunk_count`. |
| `cards_saved` | A changed, nonempty response saved successfully; `card_count`. Identical saves do not count again, edited responses do. |
| `export_completed` | Export assembled and response prepared; `card_count`, `format` (`tsv`/`zip`). Repeat exports count. Does not prove file delivery or Anki import. |
| App versions | Distinct active installation IDs grouped by app version. An installation can appear in several versions after an upgrade. |

Common fields are random installation/event UUIDs, timestamp, app version, OS
family and schema version. No old projects are scanned or backfilled. Counts
cover participating installations; deleting or copying a data directory affects
identity. These are client-reported product metrics, not billing records.

The outbox is `%APPDATA%/AnkiGen/analytics-state.json` in packaged builds, outside
the updatable `app/` folder. Up to 500 events are retained for seven days. A daemon
thread submits batches of 50, with a five-second timeout and a 60-second retry
delay. UUIDs and timestamps remain unchanged on retry. Disk and network failures
never fail a user action. Consent withdrawal removes pending events; a request
already in flight may finish. The random ID stays locally to avoid counting
consent toggles as new installations.

## GitHub downloads

```powershell
.venv/Scripts/python.exe scripts/release_downloads.py
.venv/Scripts/python.exe scripts/release_downloads.py --json
```

The read-only script paginates releases and separates `.exe`/`.msi` installers
from `app.zip` updater downloads and other assets. Downloads are not unique
users or confirmed installations. The build-latest workflow replaces release
assets; replacement/deletion can reset their counters. Current assets cannot
recover those old values.

## Verification

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests
node --test tests/test_update_ui.js
```

Tests use temporary files, real generated DOCX files and a substituted network
boundary. They exercise consent, privacy, retry identity, queue limits, failures,
save/export counts and dashboard reuse. No tests send events to production.

UI check: open Settings, verify sharing starts unchecked, read the details,
enable and save, verify persistence, then disable and save. Repeat in French.
For live verification use a separate test project, enable developer reporting,
complete an import/save/export and inspect its events in PostHog. Local tests
alone do not prove live ingestion.

References: [capture API](https://posthog.com/docs/api/capture),
[dashboards API](https://posthog.com/docs/api/dashboards),
[insights API](https://posthog.com/docs/api/insights),
[GitHub release assets](https://docs.github.com/en/rest/releases/assets),
[CNIL audience measurement](https://www.cnil.fr/fr/mesurer-la-frequentation-de-vos-sites-web-et-de-vos-applications).
