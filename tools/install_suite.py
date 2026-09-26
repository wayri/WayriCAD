"""Install built WayriCAD IPC archives into KiCad's user plugin directory."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RETIRED_PLUGINS = {
    'com.github.wayri.wayricad.kilo': 'Consolidated into Embed3D',
    'com.github.wayri.wayricad.portable-assets': 'Consolidated into Embed3D',
    'com.github.wayri.wayricad.visual-diff': 'Retired from the suite',
    'com.github.wayri.wayricad.variant-workbench': 'Retired: use native KiCad variants',
    'com.github.wayri.wayricad.pdn-decoupling': 'Consolidated into Quick PI',
    'com.github.wayri.wayricad.return-path-auditor': 'Consolidated into Quick SI',
    'com.github.wayri.wayricad.test-points': 'Consolidated into Quick SI',
}


def retire_plugins(destination, *, apply=False):
    """Back up retired direct-child installs, including PCM's underscore names."""
    destination = Path(destination).resolve()
    moved = []
    for identifier, reason in RETIRED_PLUGINS.items():
        for folder in (identifier, identifier.replace('.', '_')):
            retired = destination / folder
            if not retired.exists() and not retired.is_symlink():
                continue
            if retired.is_symlink() or retired.resolve().parent != destination:
                raise ValueError('Retired plugin path is not a direct child of the install directory.')
            print(reason + ': ' + str(retired))
            if apply:
                backups = destination.parent / 'wayricad-plugin-backups'
                backups.mkdir(exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
                backup = backups / (folder + '-' + stamp)
                retired.rename(backup)
                moved.append(backup)
    return moved


def windows_documents():
    """Respect redirected/OneDrive Documents instead of guessing ~/Documents."""
    import ctypes
    from ctypes import wintypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("data1", wintypes.DWORD), ("data2", wintypes.WORD),
                    ("data3", wintypes.WORD), ("data4", ctypes.c_ubyte * 8)]

    folder = GUID.from_buffer_copy(uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le)
    result = ctypes.c_wchar_p()
    shell = ctypes.windll.shell32.SHGetKnownFolderPath
    shell.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                      ctypes.POINTER(ctypes.c_wchar_p)]
    shell.restype = ctypes.c_long
    code = shell(ctypes.byref(folder), 0, None, ctypes.byref(result))
    if code != 0:
        raise OSError("Cannot determine Windows Documents folder; use --destination.")
    try:
        return Path(result.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))


def default_destination(version, *, platform=None, environ=None, home=None):
    """Match KiCad IPC user-data paths on Windows, macOS and XDG Linux."""
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    configured = environ.get("KICAD_DOCUMENTS_HOME")
    if configured:
        # KiCad PATHS::getUserDocumentPath appends KiCad/<version> even
        # when KICAD_DOCUMENTS_HOME overrides the platform documents path.
        root = Path(configured).expanduser() / "KiCad"
    elif platform == "win32":
        root = windows_documents() / "KiCad"
    elif platform == "darwin":
        root = home / "Documents" / "KiCad"
    else:
        data_home = Path(environ.get("XDG_DATA_HOME", ""))
        # The XDG specification requires absolute paths; relative values are ignored.
        root = (data_home if data_home.is_absolute() else home / ".local" / "share") / "KiCad"
    return root / version / "plugins"


def installation_target(destination, identifier):
    """Update the copy KiCad discovers first when PCM already owns the plugin."""
    destination = Path(destination).resolve()
    pcm_plugins = destination.parent / "3rdparty" / "plugins"
    pcm_target = pcm_plugins / identifier.replace(".", "_")
    if pcm_target.exists() or pcm_target.is_symlink():
        if pcm_target.is_symlink() or pcm_target.resolve().parent != pcm_plugins.resolve():
            raise ValueError("PCM plugin path is not a direct directory under the PCM install path.")
        manifest = pcm_target / "plugin.json"
        if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8"))["identifier"] != identifier:
            raise ValueError(f"Unexpected PCM plugin at {pcm_target}")
        return pcm_target
    return destination / identifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("10.0", "11.0"), default="10.0")
    parser.add_argument("--destination", type=Path, help="Override KiCad user plugins directory.")
    parser.add_argument("--archive-dir", type=Path, default=ROOT / "releases",
                        help="Directory of current-version PCM ZIPs (defaults to releases/).")
    parser.add_argument("--apply", action="store_true", help="Copy plugins; existing installations are backed up.")
    args = parser.parse_args()
    destination = (args.destination or default_destination(args.version)).resolve()
    versions = {json.loads(p.read_text(encoding='utf-8'))['versions'][0]['version'] for p in ROOT.glob('*_plugin/metadata.json')}
    if len(versions)!=1:parser.error('Source plugins must have one release version.')
    release=versions.pop()
    packages = sorted(args.archive_dir.glob("WayriCAD-*-"+release+"-PCM.zip"))
    expected = {"WayriCAD-" + p.parent.name.removesuffix("_plugin").replace("_", "-") + "-"+release+"-PCM.zip"
                for p in ROOT.glob("*_plugin/metadata.json")}
    if not expected or {p.name for p in packages} != expected:
        parser.error("PCM ZIPs differ from the source inventory. Build all current-version packages first.")
    if sys.platform == 'win32':
        try:
            from check_kicad_python import check, repair_malformed, settings_path
        except ImportError:
            from tools.check_kicad_python import check, repair_malformed, settings_path
        settings = settings_path(args.version)
        if settings.is_file():
            okay, message = check(settings)
            if not okay:
                if args.apply:
                    try:
                        print(repair_malformed(settings))
                    except RuntimeError as exc:
                        parser.error(str(exc) + '; no plugins were copied')
                else:
                    print('WARNING: ' + message + '; --apply will repair only the known pythonw/.exe typo after KiCad is closed.', file=sys.stderr)
    for package in packages:
        with zipfile.ZipFile(package) as archive:
            manifest = json.loads(archive.read("plugins/plugin.json"))
            identifier = manifest["identifier"]
            if not identifier.startswith("com.github.wayri.wayricad.") or any(c in identifier for c in "/\\"):
                raise ValueError("Unexpected package identifier")
            target = installation_target(destination, identifier)
            print(f"{manifest['name']} -> {target}")
            if not args.apply:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".wayricad-install-", dir=target.parent) as temporary:
                stage = Path(temporary) / target.name
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
    retire_plugins(destination, apply=args.apply)
    print("Installed. Restart KiCad and enable the API in Preferences > Plugins." if args.apply else
          "Preview only. Add --apply to install; existing installations will be backed up.")


if __name__ == "__main__":
    main()
