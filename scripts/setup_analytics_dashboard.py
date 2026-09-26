"""Create or update Ankigen's private PostHog dashboard from the owner's machine.

This script and its personal API key are never included in app.zip or installers.
"""

import argparse
import getpass
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
APP_HOSTS = {"eu": "https://eu.posthog.com", "us": "https://us.posthog.com"}
MANAGED_TAG = "ankigen-usage-v1"


def dashboard_insights():
    definitions = [
        ("observed-installs", "First observed installations · 30 days", "first_launch", "dau", "-29d", False),
        ("active-day", "Active installations · today (UTC)", "app_opened", "dau", "dStart", False),
        ("active-7d", "Active installations · 7 calendar days", "app_opened", "dau", "-6d", False),
        ("active-30d", "Active installations · 30 calendar days", "app_opened", "dau", "-29d", False),
        ("projects", "Projects created · 30 days", "project_created", "total", "-29d", False),
        ("cards-saved", "Cards across changed saves · 30 days", "cards_saved", "sum", "-29d", False),
        ("exports", "Export actions · 30 days", "export_completed", "total", "-29d", False),
        ("cards-exported", "Cards across exports · 30 days", "export_completed", "sum", "-29d", False),
        ("versions", "Active installations by app version · 30 days", "app_opened", "dau", "-29d", True),
    ]
    result = []
    for key, name, event, math, date_from, breakdown in definitions:
        series = {"kind": "EventsNode", "event": event, "math": math}
        if math == "sum":
            series["math_property"] = "card_count"
        source = {"kind": "TrendsQuery", "series": [series], "interval": "day",
                  "dateRange": {"date_from": date_from},
                  "trendsFilter": {"display": "ActionsBarValue" if breakdown else "BoldNumber"}}
        if breakdown:
            source["breakdownFilter"] = {"breakdown": "app_version", "breakdown_type": "event"}
        result.append({"key": key, "name": name, "query": {"kind": "InsightVizNode", "source": source}})
    return result


class PostHogAPI:
    def __init__(self, region, project_id, key):
        self.host = APP_HOSTS[region]
        self.base = f"{self.host}/api/projects/{project_id}/"
        self.key = key

    def request(self, method, path, payload=None):
        # Pagination URLs must never redirect the personal key to another host.
        url = path if path.startswith("https://") else self.base + path
        if not url.startswith(self.base):
            raise RuntimeError("Unexpected PostHog API URL")
        request = Request(url, method=method,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)


def ensure_dashboard(api):
    dashboards = []
    next_page = "dashboards/?limit=100"
    while next_page:
        page = api.request("GET", next_page)
        dashboards.extend(d for d in page["results"] if MANAGED_TAG in d.get("tags", []) and not d.get("deleted"))
        next_page = page.get("next")
    if len(dashboards) > 1:
        raise RuntimeError("Multiple managed Ankigen dashboards exist; resolve duplicates before rerunning.")
    dashboard = dashboards[0] if dashboards else api.request("POST", "dashboards/", {
        "name": "Ankigen — usage",
        "description": "Consented, observed installations only. Downloads are separate. Card-save and export volumes include revisions/re-exports; no verified Anki imports. First observations include existing users who update. All activity dates use UTC.",
        "tags": [MANAGED_TAG], "pinned": True,
    })
    dashboard_id = dashboard["id"]
    dashboard = api.request("GET", f"dashboards/{dashboard_id}/")
    if dashboard.get("is_shared") is not False:
        raise RuntimeError("Disable public sharing on the Ankigen dashboard before continuing.")
    existing = {}
    for tile in dashboard.get("tiles", []):
        insight = tile.get("insight") or {}
        if not insight.get("deleted"):
            for tag in insight.get("tags", []):
                existing[tag] = insight
    for metric in dashboard_insights():
        tag = f"ankigen:metric:{metric['key']}"
        old = existing.get(tag)
        payload = {"name": metric["name"], "query": metric["query"],
                   "tags": [MANAGED_TAG, tag],
                   "dashboards": sorted(set((old or {}).get("dashboards", []) + [dashboard_id]))}
        if old:
            api.request("PATCH", f"insights/{old['id']}/", payload)
        else:
            api.request("POST", "insights/", payload)
    verified = api.request("GET", f"dashboards/{dashboard_id}/")
    if verified.get("is_shared") is not False:
        raise RuntimeError("Cannot verify public sharing is disabled.")
    return dashboard_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=int, help="Numeric Ankigen project ID from PostHog settings")
    parser.add_argument("--region", choices=APP_HOSTS, default="eu")
    parser.add_argument("--key-file", type=Path, default=ROOT / ".posthog-admin-key")
    parser.add_argument("--dry-run", action="store_true", help="Print metric definitions without accessing an account")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps(dashboard_insights(), indent=2))
        return
    if not args.project or args.project <= 0:
        parser.error("--project must be the numeric Ankigen project ID")
    key = os.environ.get("POSTHOG_PERSONAL_API_KEY", "").strip()
    if not key and args.key_file.is_file():
        key = args.key_file.read_text(encoding="utf-8-sig").strip()
    if not key:
        key = getpass.getpass("PostHog personal API key (hidden): ").strip()
    if not key.startswith("phx_"):
        parser.error("Use a personal API key (phx_), never the public project token.")
    api = PostHogAPI(args.region, args.project, key)
    try:
        project = api.request("GET", "")
        if project.get("timezone") != "UTC":
            raise RuntimeError("Set the Ankigen project's timezone to UTC before creating its daily charts.")
        config_path = ROOT / "analytics_config.json"
        if config_path.is_file():
            expected = json.loads(config_path.read_text(encoding="utf-8-sig")).get("project_token")
            if expected and project.get("api_token") != expected:
                raise RuntimeError("Project does not match the token configured for Ankigen.")
        identity = ensure_dashboard(api)
    except HTTPError as error:
        parser.exit(1, f"PostHog returned HTTP {error.code}. Check project ID, region and API key scopes.\n")
    except (OSError, URLError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(1, f"Dashboard setup failed: {error}\n")
    print(f"Dashboard: {api.host}/project/{args.project}/dashboard/{identity}")
    print("Public sharing verified disabled. Access follows your PostHog project membership.")


if __name__ == "__main__":
    main()
