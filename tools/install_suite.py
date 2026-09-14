"""Install built WayriCAD IPC archives into KiCad's user plugin directory."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("10.0", "11.0"), default="10.0")
    parser.add_argument("--destination", type=Path, help="Override KiCad user plugins directory.")
    parser.add_argument("--apply", action="store_true", help="Copy plugins; existing installations are backed up.")
    args = parser.parse_args()
    destination = (args.destination or Path.home() / "Documents" / "KiCad" / args.version / "plugins").resolve()
    packages = sorted((ROOT / "releases").glob("WayriCAD-*-3.0.0-PCM.zip"))
    expected = {"WayriCAD-" + p.parent.name.removesuffix("_plugin").replace("_", "-") + "-3.0.0-PCM.zip"
                for p in ROOT.glob("*_plugin/metadata.json")}
    if not expected or {p.name for p in packages} != expected:
        parser.error("Release ZIPs differ from the source inventory. Run python build_pcm.py --clean-feed first.")
    for package in packages:
        with zipfile.ZipFile(package) as archive:
            manifest = json.loads(archive.read("plugins/plugin.json"))
            identifier = manifest["identifier"]
            if not identifier.startswith("com.github.wayri.wayricad.") or any(c in identifier for c in "/\\"):
                raise ValueError("Unexpected package identifier")
            target = destination / identifier
            print(f"{manifest['name']} -> {target}")
            if not args.apply:
                continue
            destination.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".wayricad-install-", dir=destination) as temporary:
                stage = Path(temporary) / identifier
                stage.mkdir()
                for info in archive.infolist():
                    if not info.filename.startswith("plugins/") or info.is_dir():
                        continue
                    relative = Path(info.filename[len("plugins/"):])
                    output = (stage / relative).resolve()
                    if not output.is_relative_to(stage.resolve()):
                        raise ValueError("Unsafe archive entry")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(archive.read(info))
                backup = None
                if target.exists():
                    backups = destination.parent / "wayricad-plugin-backups"
                    backups.mkdir(exist_ok=True)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                    backup = backups / f"{identifier}-{stamp}"
                    target.rename(backup)
                try:
                    stage.rename(target)
                except Exception:
                    if backup is not None:
                        backup.rename(target)
                    raise
    print("Installed. Restart KiCad and enable the API in Preferences > Plugins." if args.apply else
          "Preview only. Add --apply to install; existing installations will be backed up.")


if __name__ == "__main__":
    main()
