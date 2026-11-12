"""Refresh only reviewed viewer assets from the exact official release archive."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

VERSION = "0.6.0"
ARCHIVE_SHA256 = "668f973db5e931ff32a68a7ee2dfd178d54d0be25ff47b24a5b460681a6d28a4"
ASSET_URL = "https://github.com/wayri/kicad-webview/releases/download/v0.6.0/wayrisignals-kicad-webview-0.6.0.tgz"
FILES = {name: "dist/"+name for name in (
    "kicad-webview.min.js", "LICENSE", "LICENSING.md", "THIRD-PARTY-NOTICES.md",
    "THREE-LICENSE", "FZSTD-LICENSE", "SPIKE-ENGINE-NOTICE.md", "SOURCE-PROVENANCE.json",
    "licenses/Pocket-KiView-Source-Available-1.0.txt", "PUBLIC-API.md",
    "INSPECTION-CONTROLS.md", "VIEW-NAVIGATION.md",
)}
FILES.update({"PUBLIC-API.d.ts": "types/index.d.ts", "UPSTREAM-PACKAGE.json": "package.json"})


def pin(archive, destination):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Archive does not match the verified official 0.6.0 release.")
    payloads = {}
    with tarfile.open(archive, "r:gz") as source:
        for name, origin in FILES.items():
            member = source.getmember("package/"+origin)
            if not member.isfile() or member.size > 8*1024*1024:
                raise ValueError("Unexpected upstream asset: "+origin)
            payloads[name] = source.extractfile(member).read()
    package = json.loads(payloads["UPSTREAM-PACKAGE.json"])
    if package["version"] != VERSION or package["license"] != "MPL-2.0":
        raise ValueError("Unexpected upstream package identity.")
    manifest = dict(schema=1, kind="wayricad-integration-pin", version=VERSION,
                    upstreamAssetURL=ASSET_URL, upstreamArchiveSHA256=ARCHIVE_SHA256,
                    matchingSourceURL="https://github.com/wayri/kicad-webview/tree/v0.6.0",
                    note="Integration-authored file inventory; upstream 0.6.0 ships no RELEASE.json.",
                    legalContext="Upstream legal text is retained verbatim, including historical source links. Exact matching source is v0.6.0 above. Archived source-available text is historical, not an extra restriction on MPL-2.0.",
                    files=[])
    for name, data in sorted(payloads.items()):
        path = destination/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        manifest["files"].append(dict(path=name, sourcePath=FILES[name], bytes=len(data),
                                      sha256=hashlib.sha256(data).hexdigest()))
    (destination/"PINNED-DISTRIBUTION.json").write_text(
        json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    manifest = pin(args.archive, Path(__file__).resolve().parents[1]/"vendor"/"kicad-webview")
    print("Pinned", len(manifest["files"]), "official 0.6.0 assets")
