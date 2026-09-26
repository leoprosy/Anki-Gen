"""Owner tooling must preserve private access and avoid duplicated dashboards."""

import copy
import unittest

from scripts.setup_analytics_dashboard import ensure_dashboard, dashboard_insights
from scripts.release_downloads import summarize_releases


class FakePostHog:
    def __init__(self):
        self.dashboard = None
        self.insights = []
        self.created_dashboards = 0

    def request(self, method, path, payload=None):
        if path == "dashboards/?limit=100" and method == "GET":
            return {"results": [self.dashboard] if self.dashboard else [], "next": None}
        if path == "dashboards/" and method == "POST":
            self.created_dashboards += 1
            self.dashboard = {"id": 10, "name": payload["name"], "tags": payload["tags"], "is_shared": False, "tiles": []}
            return copy.deepcopy(self.dashboard)
        if path == "dashboards/10/" and method == "GET":
            result = copy.deepcopy(self.dashboard)
            result["tiles"] = [{"insight": value} for value in self.insights]
            return result
        if path == "insights/" and method == "POST":
            value = {"id": len(self.insights) + 1, **copy.deepcopy(payload)}
            self.insights.append(value)
            return value
        if path.startswith("insights/") and method == "PATCH":
            identity = int(path.split("/")[1])
            value = next(i for i in self.insights if i["id"] == identity)
            value.update(copy.deepcopy(payload))
            return value
        raise AssertionError((method, path, payload))


class DashboardTests(unittest.TestCase):
    def test_rerunning_setup_reuses_dashboard_and_insights(self):
        api = FakePostHog()
        self.assertEqual(ensure_dashboard(api), 10)
        self.assertEqual(ensure_dashboard(api), 10)
        self.assertEqual(api.created_dashboards, 1)
        self.assertEqual(len(api.insights), 9)
        self.assertTrue(all(item["dashboards"] == [10] for item in api.insights))
        self.assertFalse(api.dashboard["is_shared"])

    def test_shared_dashboard_is_rejected_before_updating_metrics(self):
        api = FakePostHog()
        ensure_dashboard(api)
        api.dashboard["is_shared"] = True
        with self.assertRaisesRegex(RuntimeError, "public sharing"):
            ensure_dashboard(api)

    def test_cards_exported_sums_rows_and_active_metrics_count_unique_installations(self):
        metrics = {item["key"]: item for item in dashboard_insights()}
        exported = metrics["cards-exported"]["query"]["source"]["series"][0]
        self.assertEqual(exported, {"kind": "EventsNode", "event": "export_completed", "math": "sum", "math_property": "card_count"})
        active = metrics["active-30d"]["query"]["source"]
        self.assertEqual(active["series"][0]["event"], "app_opened")
        self.assertEqual(active["series"][0]["math"], "dau")
        self.assertEqual(active["dateRange"]["date_from"], "-29d")

    def test_daily_chart_uses_project_calendar(self):
        metrics = {item["key"]: item for item in dashboard_insights()}
        self.assertEqual(metrics["active-day"]["query"]["source"]["dateRange"]["date_from"], "dStart")
        self.assertIn("today", metrics["active-day"]["name"])
        self.assertNotIn("UTC", metrics["active-day"]["name"])


class DownloadsTests(unittest.TestCase):
    def test_installer_update_and_other_assets_are_separate(self):
        release = {"tag_name": "v1.2.1", "draft": False, "assets": [
            {"name": "Ankigen-setup.exe", "download_count": 12},
            {"name": "Ankigen.msi", "download_count": 3},
            {"name": "app.zip", "download_count": 47},
            {"name": "version.json", "download_count": 120},
        ]}
        rows, totals = summarize_releases([release, {**release, "draft": True}])
        self.assertEqual(totals, {"installer": 15, "updater": 47, "other": 120})
        self.assertEqual(len(rows), 4)
