"""Read current GitHub release-asset downloads, separating installers and updates."""

import argparse
import json
import re
from urllib.request import Request, urlopen


def summarize_releases(releases):
    rows = []
    totals = {"installer": 0, "updater": 0, "other": 0}
    for release in releases:
        if release.get("draft"):
            continue
        for asset in release.get("assets", []):
            name = asset["name"]
            category = "installer" if name.lower().endswith((".exe", ".msi")) else "updater" if name == "app.zip" else "other"
            count = asset.get("download_count", 0)
            rows.append({"release": release["tag_name"], "asset": name, "category": category, "downloads": count})
            totals[category] += count
    return rows, totals


def fetch_releases(repo):
    releases = []
    page = 1
    while True:
        request = Request(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}",
                          headers={"Accept": "application/vnd.github+json", "User-Agent": "Ankigen-Owner-Stats"})
        with urlopen(request, timeout=15) as response:
            batch = json.load(response)
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="leoprosy/Anki-Gen")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("--repo must be OWNER/REPO")
    try:
        rows, totals = summarize_releases(fetch_releases(args.repo))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Cannot read GitHub downloads: {error}\n")
    if args.json:
        print(json.dumps({"totals": totals, "assets": rows}, indent=2))
    else:
        for row in rows:
            print(f"{row['release']:12} {row['downloads']:8}  {row['category']:10} {row['asset']}")
        print(f"\nInstaller downloads: {totals['installer']} | Update downloads: {totals['updater']}")
        print("Downloads are not unique users or confirmed installations. Replaced assets reset their counters.")


if __name__ == "__main__":
    main()
