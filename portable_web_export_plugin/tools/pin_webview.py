"""Refresh only reviewed viewer assets from the exact official release archive."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path

VERSION = "0.8.0"
SOURCE_COMMIT = "2945c855df8698af4dfe70fd6e31f729400c5eda"
ARCHIVE_SHA256 = "7312c12b89c696b68b69ef9538ec7bbee42ae4d9c8894b96968214e7a19eb1d9"
ASSET_URL = None
FILES = {name: "dist/"+name for name in (
    "kicad-webview.min.js", "LICENSE", "LICENSING.md", "THIRD-PARTY-NOTICES.md",
    "THREE-LICENSE", "FZSTD-LICENSE", "SPIKE-ENGINE-NOTICE.md", "SOURCE-PROVENANCE.json",
    "licenses/Pocket-KiView-Source-Available-1.0.txt", "PUBLIC-API.md",
    "INSPECTION-CONTROLS.md", "VIEW-NAVIGATION.md", "WAYRICAD-RESULTS.md",
    "PANELS-AND-INSETS.md", "LARGE-PROJECTS.md", "EXPAND-MODE.md", "UPSTREAM-SYNC.md",
)}
FILES.update({"PUBLIC-API.d.ts": "types/index.d.ts", "UPSTREAM-PACKAGE.json": "package.json"})


def pin(archive, destination):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Archive does not match the verified source-preview build.")
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
                    matchingSourceURL="https://github.com/wayri/kicad-webview/tree/"+SOURCE_COMMIT,
                    sourceCommit=SOURCE_COMMIT, distributionKind="source-preview",
                    note="Integration-authored inventory of a tested source build, not the published npm/CDN 0.8.0 artifact.",
                    legalContext="Upstream legal text is retained verbatim. The exact covered source is linked by immutable commit above; no unrelated SPIKE source is included.",
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


def pin_review(archive, destination):
    """Keep Review independently installable with the same verified build."""
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Unexpected source-preview archive.')
    names = ('kivi-viewer.js', 'LICENSE', 'LICENSING.md', 'THIRD-PARTY-NOTICES.md',
             'THREE-LICENSE', 'FZSTD-LICENSE', 'SPIKE-ENGINE-NOTICE.md',
             'SOURCE-PROVENANCE.json', 'PUBLIC-API.md')
    records = {}
    with tarfile.open(archive, 'r:gz') as source:
        for name in names:
            member = source.getmember('package/dist/'+name)
            if not member.isfile() or member.size > 2*1024*1024:
                raise ValueError('Unexpected Review viewer asset: '+name)
            data = source.extractfile(member).read()
            (destination/name).write_bytes(data)
            records[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    receipt = dict(schema='wayricad.review-viewer-pin/v1', version=VERSION,
                   license='MPL-2.0', source_archive_url=None,
                   source_archive_sha256=ARCHIVE_SHA256,
                   source_url='https://github.com/wayri/kicad-webview/tree/'+SOURCE_COMMIT,
                   source_commit=SOURCE_COMMIT, distribution_kind='source-preview',
                   note='Tested source build; not published npm/CDN 0.8.0. Unmodified covered source linked above.',
                   files=records)
    (destination/'REVIEW-PIN.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument('--review-destination', type=Path)
    args = parser.parse_args()
    manifest = pin(args.archive, Path(__file__).resolve().parents[1]/"vendor"/"kicad-webview")
    print("Pinned", len(manifest["files"]), "source-preview assets at", SOURCE_COMMIT)
    if args.review_destination:
        pin_review(args.archive, args.review_destination)
