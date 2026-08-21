import os
import json
import zipfile
import hashlib
import datetime
from io import BytesIO
from pathlib import Path

# Configuration
PCM_DIR = "pcm"
RELEASES_DIR = "releases"
REPO_URL_BASE = "https://github.com/wayri/KiWay/releases/download" 
# All package versions in a feed may differ, but this repository publishes
# their downloadable assets together in one release.
RELEASE_TAG = "2.24.0"

def calculate_sha256(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def discover_plugins(base_path):
    return sorted(
        path for path in base_path.iterdir()
        if path.is_dir() and (path / "metadata.json").exists()
    )


def normalize_runtime(version_info):
    """Migrate legacy ActionPlugin labels to KiCad's PCM runtime enum."""
    normalized = dict(version_info)
    if normalized.get("runtime") == "action-plugin":
        normalized["runtime"] = "swig"
    runtime = normalized.get("runtime", "swig")
    if runtime not in {"swig", "ipc"}:
        raise ValueError(f"Unsupported KiCad PCM runtime: {runtime!r}")
    normalized["runtime"] = runtime
    return normalized

def create_plugin_zip(plugin_path, version, output_dir, metadata):
    os.makedirs(output_dir, exist_ok=True)
    zip_filename = f"{plugin_path.name}-{version}.zip"
    zip_path = os.path.join(output_dir, zip_filename)
    
    print(f"Zipping {plugin_path} to {zip_path}...")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # KiCad PCM expects metadata at the archive root, plugin files under
        # plugins/, and the 64x64 PCM card icon under resources/icon.png.
        zipf.write(plugin_path / 'metadata.json', 'metadata.json')
        for root, dirs, files in os.walk(plugin_path):
            dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git', '.vscode']]
            for file in files:
                # Keep icon.png in the plugin payload: pcbnew.ActionPlugin uses
                # this file for the External Plugins menu and toolbar icon.
                if file.endswith('.pyc') or file == 'metadata.json':
                    continue
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, start=plugin_path)
                arcname = os.path.join('plugins', rel_path)
                arcname = arcname.replace(os.sep, '/')
                zipf.write(file_path, arcname)

        icon_path = plugin_path / 'icon.png'
        if icon_path.exists():
            try:
                from PIL import Image

                with Image.open(icon_path) as image:
                    image = image.convert('RGBA').resize((64, 64), Image.Resampling.LANCZOS)
                    buffer = BytesIO()
                    image.save(buffer, format='PNG', optimize=True)
                    zipf.writestr('resources/icon.png', buffer.getvalue())
            except Exception:
                # Keep package generation usable in minimal Python environments.
                zipf.write(icon_path, 'resources/icon.png')
    
    return zip_path, zip_filename

def main():
    base_path = Path('.')
    
    os.makedirs(PCM_DIR, exist_ok=True)
    packages_file = Path(PCM_DIR) / "pkgs.json"
    repo_file = Path(PCM_DIR) / "repo.json"
    
    # --- PACKAGES.JSON (Object Wrapper) ---
    packages_data = {"packages": []}
    
    if packages_file.exists():
        try:
            with open(packages_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
                if isinstance(existing, dict) and 'packages' in existing:
                    packages_data = existing
                elif isinstance(existing, list):
                    # Migration from root list
                    packages_data['packages'] = existing
        except Exception:
            pass

    plugin_paths = discover_plugins(base_path)
    active_identifiers = set()
    for plugin_path in plugin_paths:
        with open(plugin_path / "metadata.json", "r", encoding="utf-8") as f:
            active_identifiers.add(json.load(f)["identifier"])

    # The filesystem is authoritative. Removed packages must disappear from
    # the feed instead of lingering indefinitely from an older build.
    packages_list = [
        package for package in packages_data['packages']
        if package.get('identifier') in active_identifiers
    ]
    for package in packages_list:
        package['versions'] = [normalize_runtime(version) for version in package.get('versions', [])]
    existing_by_id = {pkg.get('identifier'): pkg for pkg in packages_list}

    for plugin_path in plugin_paths:
        with open(plugin_path / "metadata.json", "r", encoding='utf-8') as f:
            metadata = json.load(f)

        version = metadata['versions'][0]['version']
        identifier = metadata['identifier']
        zip_path, zip_filename = create_plugin_zip(plugin_path, version, RELEASES_DIR, metadata)

        file_size = os.path.getsize(zip_path)
        sha256 = calculate_sha256(zip_path)
        version_info = normalize_runtime(metadata['versions'][0])
        version_info.update({
            "download_sha256": sha256,
            "download_size": file_size,
            "download_url": f"{REPO_URL_BASE}/v{RELEASE_TAG}/{zip_filename}",
            "install_size": 0,
            "platforms": ["windows", "linux", "macos"]
        })

        install_size = 0
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            for info in zipf.infolist():
                install_size += info.file_size
        version_info['install_size'] = install_size

        if 'resources' not in metadata:
            metadata['resources'] = {"homepage": "https://github.com/wayri/KiWay"}
        # Keep every package icon aligned with the repository's actual default branch.
        metadata['resources']['icon'] = f"https://raw.githubusercontent.com/wayri/KiWay/develop/{plugin_path.name}/icon.png"

        package = {
            "name": metadata['name'],
            "description": metadata['description'],
            "description_full": metadata['description_full'],
            "identifier": identifier,
            "type": metadata['type'],
            "author": metadata['author'],
            "license": metadata['license'],
            "resources": metadata['resources'],
            "versions": [version_info]
        }

        pkg = existing_by_id.get(identifier)
        if pkg:
            v_exists = False
        
            for v_idx, v in enumerate(pkg['versions']):
                if v['version'] == version:
                    pkg['versions'][v_idx] = version_info
                    v_exists = True
                    break
        
            if not v_exists:
                pkg['versions'].insert(0, version_info)
        
            # Metadata.json is authoritative for package-level fields.
            for key in (
                'name',
                'description',
                'description_full',
                'type',
                'author',
                'license',
                'resources',
            ):
                pkg[key] = package[key]
        else:
            packages_list.append(package)
            existing_by_id[identifier] = package

        print(f"Updated package {identifier} ({version})")
    
    packages_data['packages'] = packages_list
    
    with open(packages_file, 'w', encoding='utf-8') as f:
        json.dump(packages_data, f, indent=4)
        
    print(f"Updated {packages_file}")
    
    # --- REPOSITORY.JSON ---
    packages_timestamp = int(datetime.datetime.now().timestamp())
    
    # URL to the raw packages.json file on GitHub
    # KiWay's default branch is develop; keep the feed URL aligned with it.
    # Added timestamp query to BUST GITHUB RAW CACHE
    packages_url = f"https://raw.githubusercontent.com/wayri/KiWay/develop/pcm/pkgs.json?t={packages_timestamp}"
    
    repository = {
        "$schema": "https://go.kicad.org/pcm/schemas/v1",
        "name": "KiWay Plugin Repository",
        "maintainer": {
            "name": "Wayri (Yawar)",
            "contact": {"github": "https://github.com/wayri"}
        },
        "packages": {
            "url": packages_url,
            "update_timestamp": packages_timestamp
        }
    }
    
    with open(repo_file, 'w', encoding='utf-8') as f:
        json.dump(repository, f, indent=4)
        
    print(f"Updated {repo_file}")
    print(f"Packages: {len(packages_list)}")

if __name__ == "__main__":
    main()
