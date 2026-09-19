"""Regression checks for KiCad's repository protocol, beyond JSON shape."""
import hashlib
import json
from pathlib import Path

import pytest

from tools.validate_packages import validate_repository


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "tools/schemas/pcm-v2.json").read_text(encoding="utf-8"))


def documents():
    # Use real source packages without depending on a release rebuild.
    from build_pcm import normalize_metadata
    package = normalize_metadata(
        json.loads((ROOT / "quick_pi_plugin/metadata.json").read_text(encoding="utf-8")),
        ROOT / "quick_pi_plugin", "develop")
    payload = json.dumps({"packages": [package]}).encode("utf-8")
    repo = {"name": "test", "schema_version": 2,
            "packages": {"url": "https://example.org/packages.json", "update_timestamp": 1,
                         "sha256": hashlib.sha256(payload).hexdigest()}}
    return repo, payload


def test_repository_negotiates_the_kicad_10_validator():
    repo, payload = documents()
    assert len(validate_repository(repo, payload, SCHEMA)["packages"]) == 1
    del repo["schema_version"]
    repo["$schema"] = "https://go.kicad.org/pcm/schemas/v2"
    with pytest.raises(ValueError, match="schema_version"):
        validate_repository(repo, payload, SCHEMA)


def test_repository_rejects_stale_or_corrupted_feed():
    repo, payload = documents()
    with pytest.raises(ValueError, match="SHA-256"):
        validate_repository(repo, payload + b" ", SCHEMA)


def test_repository_requires_feed_digest():
    repo, payload = documents()
    del repo["packages"]["sha256"]
    with pytest.raises(ValueError, match="SHA-256"):
        validate_repository(repo, payload, SCHEMA)


def test_repository_rejects_empty_feed():
    repo, _ = documents()
    payload = b'{"packages": []}'
    repo["packages"]["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError, match="empty"):
        validate_repository(repo, payload, SCHEMA)


def test_diagnostic_explains_wrong_json_or_github_page():
    from tools.diagnose_pcm import repository_document
    for payload in (b'{"packages": []}', b'{"identifier": "example"}'):
        with pytest.raises(ValueError, match="repo.json"):
            repository_document(payload)
    with pytest.raises(ValueError, match="GitHub blob"):
        repository_document(b"<!doctype html><html>GitHub</html>")


def test_diagnostic_matches_kicad_version_and_platform_rules():
    from tools.diagnose_pcm import compatible
    version = {"kicad_version": "10.0", "runtime": "ipc", "status": "testing"}
    # 'testing' and IPC do not hide packages in KiCad's PreparePackage.
    assert compatible(version, "10.0.0", "linux")
    assert not compatible(version, "9.0.9", "linux")
    version.update(kicad_version_max="10.0", platforms=["windows"])
    assert compatible(version, "10.0.6", "windows")
    assert not compatible(version, "10.0.6", "linux")
    assert not compatible(version, "11.0.0", "windows")
