"""Read-only PCM repository/download diagnostic; no KiCad config is changed."""
import argparse
import hashlib
import json
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_URL = "https://raw.githubusercontent.com/wayri/WayriCAD/develop/pcm/repo.json"


def load(url, *, limit=16 * 1024 * 1024):
    if urlsplit(url).scheme != "https":
        raise ValueError("Use an HTTPS repository URL.")
    request = Request(url, headers={"Accept": "application/vnd.kicad.pcm.v2+json",
                                   "User-Agent": "WayriCAD-PCM-Diagnostic"})
    with urlopen(request, timeout=30) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Repository response exceeds the diagnostic size limit.")
    return body


def repository_document(body):
    try:
        repo = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("URL did not return JSON. Use the raw repo.json URL, not a GitHub blob page.") from exc
    if not isinstance(repo, dict) or not isinstance(repo.get("packages"), dict) or not isinstance(repo["packages"].get("url"), str):
        raise ValueError("This is not a repository descriptor. Add pcm/repo.json to PCM, not pkgs.json, plugin.json or metadata.json.")
    return repo


def compatible(version, kicad_version, platform):
    def number(value, default):
        parts = [int(p) for p in value.split(".")]
        return tuple((parts + [default] * 3)[:3])
    current = number(kicad_version, 0)
    return (number(version["kicad_version"], 0) <= current
            and (not version.get("kicad_version_max") or current <= number(version["kicad_version_max"], 999))
            and (not version.get("platforms") or platform in version["platforms"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--kicad-version", default="10.0.0")
    parser.add_argument("--platform", choices=("windows", "linux", "macos"),
                        default={"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux"))
    args = parser.parse_args(argv)
    try:
        repo = repository_document(load(args.url, limit=20480))
        body = load(repo["packages"]["url"])
        expected = repo["packages"].get("sha256")
        if expected and hashlib.sha256(body).hexdigest() != expected:
            raise ValueError("Packages hash differs from repo.json: stale or inconsistent server/cache response.")
        feed = json.loads(body)
        packages = feed["packages"]
        available = [p for p in packages if any(compatible(v, args.kicad_version, args.platform) for v in p["versions"])]
        print(f"Repository: {repo.get('name', args.url)}")
        print(f"KiCad validator selected: v{repo.get('schema_version', 1)}")
        print(f"Packages: {len(packages)}; compatible with {args.kicad_version} / {args.platform}: {len(available)}")
        for package in available:
            print("  " + package["name"])
        if not available:
            raise ValueError("No compatible packages in this feed.")
        print("In PCM, select this repository in the repository dropdown and clear the search filter.")
        print("Installed IPC actions appear in the PCB Editor only after its Python environment setup succeeds.")
        print("If an installed action is missing, inspect the PCB Editor warning panel and Preferences > Plugins.")
        return 0
    except (OSError, URLError, ValueError, KeyError, TypeError) as exc:
        print("PCM diagnostic failed: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
