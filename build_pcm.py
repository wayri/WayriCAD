import argparse
import copy
import datetime
import hashlib
import json
import os
import zipfile
from io import BytesIO
from pathlib import Path


PCM_DIR = "pcm"
RELEASES_DIR = "releases"

DEFAULT_BRANCH = os.environ.get("KIWAY_BRANCH", "develop")
DEFAULT_RELEASE_TAG = os.environ.get("KIWAY_RELEASE_TAG", "2.24.1")

REPO_OWNER = "wayri"
REPO_NAME = "KiWay"
GITHUB_PROFILE = "https://github.com/wayri"
REPO_HOMEPAGE = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
REPO_URL_BASE = f"{REPO_HOMEPAGE}/releases/download"

PCM_SCHEMA = "https://go.kicad.org/pcm/schemas/v1"
SUPPORTED_RUNTIMES = {"swig", "ipc"}

# KiCad PCM v1 uses the older SPDX spelling for this license.
PCM_LICENSE_ALIASES = {
    "GPL-3.0-only": "GPL-3.0",
}


def calculate_sha256(file_path):
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(1024 * 1024), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path, data):
    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")

    os.replace(tmp_path, path)


def discover_plugins(base_path):
    return sorted(
        path
        for path in base_path.iterdir()
        if path.is_dir() and (path / "metadata.json").exists()
    )


def normalize_runtime(version_info):
    """Normalize old runtime names to KiCad PCM v1 runtime values."""
    normalized = dict(version_info)

    if normalized.get("runtime") == "action-plugin":
        normalized["runtime"] = "swig"

    runtime = normalized.get("runtime", "swig")
    if runtime not in SUPPORTED_RUNTIMES:
        raise ValueError(
            f"Unsupported KiCad PCM runtime: {runtime!r}. "
            f"Expected one of {sorted(SUPPORTED_RUNTIMES)}."
        )

    normalized["runtime"] = runtime
    return normalized


def normalize_author(author, plugin_path):
    """Ensure author data satisfies KiCad PCM v1."""
    if not isinstance(author, dict):
        raise ValueError(f"{plugin_path}: 'author' must be a JSON object.")

    normalized = copy.deepcopy(author)

    name = normalized.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{plugin_path}: 'author.name' is required.")

    contact = normalized.get("contact")
    if contact is None:
        contact = {}
    elif not isinstance(contact, dict):
        raise ValueError(
            f"{plugin_path}: 'author.contact' must be a JSON object."
        )

    # All KiWay packages use the same repository maintainer.
    if not contact:
        contact = {"github": GITHUB_PROFILE}

    normalized["contact"] = contact
    return normalized


def normalize_license(license_name, plugin_path):
    if not isinstance(license_name, str) or not license_name.strip():
        raise ValueError(f"{plugin_path}: 'license' is required.")

    normalized = PCM_LICENSE_ALIASES.get(license_name, license_name)

    if normalized != license_name:
        print(
            f"  Normalized PCM license for {plugin_path.name}: "
            f"{license_name!r} -> {normalized!r}"
        )

    return normalized


def require_string(metadata, key, plugin_path):
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{plugin_path}: required string field {key!r} is missing."
        )
    return value


def normalize_metadata(metadata, plugin_path, branch):
    """
    Return PCM-safe metadata without changing the source dictionary.

    The same normalized metadata is used for pcm/pkgs.json and for the
    metadata.json embedded in each generated package ZIP.
    """
    if not isinstance(metadata, dict):
        raise ValueError(
            f"{plugin_path}: metadata.json root must be an object."
        )

    normalized = copy.deepcopy(metadata)
    normalized["$schema"] = PCM_SCHEMA

    for key in (
        "name",
        "description",
        "description_full",
        "identifier",
        "type",
        "license",
    ):
        require_string(normalized, key, plugin_path)

    normalized["author"] = normalize_author(
        normalized.get("author"),
        plugin_path,
    )

    normalized["license"] = normalize_license(
        normalized["license"],
        plugin_path,
    )

    versions = normalized.get("versions")

    if not isinstance(versions, list) or not versions:
        raise ValueError(
            f"{plugin_path}: 'versions' must be a non-empty array."
        )

    normalized_versions = []

    for index, version in enumerate(versions):

        if not isinstance(version, dict):
            raise ValueError(
                f"{plugin_path}: versions[{index}] must be a JSON object."
            )

        version = normalize_runtime(version)

        if (
            not isinstance(version.get("version"), str)
            or not version["version"].strip()
        ):
            raise ValueError(
                f"{plugin_path}: versions[{index}].version is required."
            )

        if (
            not isinstance(version.get("status"), str)
            or not version["status"].strip()
        ):
            raise ValueError(
                f"{plugin_path}: versions[{index}].status is required."
            )

        if (
            not isinstance(version.get("kicad_version"), str)
            or not version["kicad_version"].strip()
        ):
            raise ValueError(
                f"{plugin_path}: versions[{index}].kicad_version is required."
            )

        normalized_versions.append(version)

    normalized["versions"] = normalized_versions

    resources = normalized.get("resources")

    if resources is None:
        resources = {}

    elif not isinstance(resources, dict):
        raise ValueError(
            f"{plugin_path}: 'resources' must be a JSON object."
        )

    resources = copy.deepcopy(resources)

    resources.setdefault(
        "homepage",
        REPO_HOMEPAGE,
    )

    # IMPORTANT:
    #
    # KiCad does NOT use a per-package URL here for icons shown in
    # Plugin and Content Manager.
    #
    # Those icons come from the separate repository-level resources.zip.
    #
    # The package itself will still contain:
    #
    #     resources/icon.png
    #
    # for use after installation.
    resources.pop("icon", None)

    normalized["resources"] = resources

    return normalized


def get_pcm_icon_bytes(icon_path):
    """
    Return a 64x64 PNG icon suitable for KiCad PCM.

    Pillow is preferred. If Pillow is unavailable or conversion fails,
    the original PNG is returned.
    """

    icon_path = Path(icon_path)

    if not icon_path.exists():
        return None

    try:
        from PIL import Image

        with Image.open(icon_path) as image:

            image = image.convert("RGBA").resize(
                (64, 64),
                Image.Resampling.LANCZOS,
            )

            buffer = BytesIO()

            image.save(
                buffer,
                format="PNG",
                optimize=True,
            )

            return buffer.getvalue()

    except Exception as exc:

        print(
            f"  Warning: could not normalize {icon_path}: {exc}. "
            "Using the original PNG."
        )

        return icon_path.read_bytes()


def create_repository_resources_zip(
    plugin_paths,
    metadata_by_path,
    output_dir,
):
    """
    Create KiCad's repository-level resources.zip.

    THIS is what supplies icons in Plugin and Content Manager before a
    package is installed.

    KiCad expects icons inside the ZIP using:

        <package-identifier>/icon.png

    Examples:

        kiway.extract.pins/icon.png
        kiway.fanout.generator/icon.png
        kiway.via.stitching/icon.png
    """

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    zip_path = output_dir / "resources.zip"

    icon_count = 0

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zipf:

        for plugin_path in plugin_paths:

            metadata = metadata_by_path[plugin_path]

            identifier = metadata["identifier"]

            icon_path = plugin_path / "icon.png"

            icon_bytes = get_pcm_icon_bytes(icon_path)

            if icon_bytes is None:

                print(
                    f"  Warning: no PCM icon found for {identifier}: "
                    f"{icon_path}"
                )

                continue

            # ZIP filenames MUST use forward slashes,
            # including when building under Windows.

            archive_name = f"{identifier}/icon.png"

            zipf.writestr(
                archive_name,
                icon_bytes,
            )

            icon_count += 1

    if icon_count == 0:

        zip_path.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            "No plugin icons were found; refusing to create an empty "
            "repository resources.zip."
        )

    print(
        f"Created repository resources archive: "
        f"{zip_path} ({icon_count} icons)"
    )

    return zip_path, icon_count


def create_plugin_zip(
    plugin_path,
    version,
    output_dir,
    metadata,
):
    """
    Create one KiCad PCM plugin archive.

    Archive layout:

        metadata.json

        plugins/
            ...

        resources/
            icon.png
    """

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    zip_filename = (
        f"{plugin_path.name}-{version}.zip"
    )

    zip_path = (
        output_dir / zip_filename
    )

    print(
        f"Zipping {plugin_path} -> {zip_path}"
    )

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zipf:

        #
        # metadata.json
        #
        # Write NORMALIZED metadata, not the original source metadata.
        #
        # This guarantees:
        #
        #   author.contact
        #   normalized license
        #   normalized runtime
        #
        # are also correct inside the downloadable package.
        #

        normalized_metadata_text = (
            json.dumps(
                metadata,
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )

        zipf.writestr(
            "metadata.json",
            normalized_metadata_text,
        )

        #
        # Plugin files
        #

        for root, dirs, files in os.walk(plugin_path):

            dirs[:] = [
                d
                for d in dirs
                if d
                not in {
                    "__pycache__",
                    ".git",
                    ".vscode",
                }
            ]

            for file in files:

                if file.endswith(".pyc"):
                    continue

                if file == "metadata.json":
                    continue

                file_path = (
                    Path(root) / file
                )

                rel_path = (
                    file_path.relative_to(
                        plugin_path
                    )
                )

                archive_name = (
                    Path("plugins") / rel_path
                ).as_posix()

                zipf.write(
                    file_path,
                    archive_name,
                )

        #
        # Installed-package icon
        #

        icon_bytes = get_pcm_icon_bytes(
            plugin_path / "icon.png"
        )

        if icon_bytes is not None:

            zipf.writestr(
                "resources/icon.png",
                icon_bytes,
            )

    return (
        zip_path,
        zip_filename,
    )


def calculate_install_size(zip_path):

    with zipfile.ZipFile(
        zip_path,
        "r",
    ) as zipf:

        return sum(
            info.file_size
            for info
            in zipf.infolist()
        )


def validate_feed(packages_data):
    """
    Catch common PCM feed errors before publishing.

    This is deliberately strict about the errors we already encountered.
    """

    if not isinstance(
        packages_data,
        dict,
    ):
        raise ValueError(
            "packages feed root must be a JSON object."
        )

    packages = packages_data.get(
        "packages"
    )

    if not isinstance(
        packages,
        list,
    ):
        raise ValueError(
            "packages feed must contain a 'packages' array."
        )

    identifiers = set()

    for index, package in enumerate(
        packages
    ):

        prefix = (
            f"/packages/{index}"
        )

        if not isinstance(
            package,
            dict,
        ):
            raise ValueError(
                f"{prefix}: package must be a JSON object."
            )

        identifier = package.get(
            "identifier"
        )

        if (
            not isinstance(
                identifier,
                str,
            )
            or not identifier.strip()
        ):
            raise ValueError(
                f"{prefix}/identifier: required."
            )

        if identifier in identifiers:

            raise ValueError(
                f"{prefix}/identifier: "
                f"duplicate identifier "
                f"{identifier!r}."
            )

        identifiers.add(
            identifier
        )

        #
        # Author validation
        #

        author = package.get(
            "author"
        )

        if not isinstance(
            author,
            dict,
        ):
            raise ValueError(
                f"{prefix}/author: "
                "must be an object."
            )

        if (
            not isinstance(
                author.get("name"),
                str,
            )
            or not author["name"].strip()
        ):
            raise ValueError(
                f"{prefix}/author/name: required."
            )

        contact = author.get(
            "contact"
        )

        if (
            not isinstance(
                contact,
                dict,
            )
            or not contact
        ):

            raise ValueError(
                f"{prefix}/author/contact: "
                "required by KiCad PCM v1."
            )

        #
        # License validation
        #

        license_name = package.get(
            "license"
        )

        if license_name in PCM_LICENSE_ALIASES:

            raise ValueError(
                f"{prefix}/license: "
                f"unnormalized license "
                f"{license_name!r}; "
                f"expected "
                f"{PCM_LICENSE_ALIASES[license_name]!r}."
            )

        #
        # Versions
        #

        versions = package.get(
            "versions"
        )

        if (
            not isinstance(
                versions,
                list,
            )
            or not versions
        ):

            raise ValueError(
                f"{prefix}/versions: "
                "must be a non-empty array."
            )

        seen_versions = set()

        for v_index, version in enumerate(
            versions
        ):

            v_prefix = (
                f"{prefix}/versions/{v_index}"
            )

            if not isinstance(
                version,
                dict,
            ):

                raise ValueError(
                    f"{v_prefix}: "
                    "must be an object."
                )

            version_name = version.get(
                "version"
            )

            if (
                not isinstance(
                    version_name,
                    str,
                )
                or not version_name.strip()
            ):

                raise ValueError(
                    f"{v_prefix}/version: required."
                )

            if version_name in seen_versions:

                raise ValueError(
                    f"{v_prefix}/version: "
                    f"duplicate version "
                    f"{version_name!r}."
                )

            seen_versions.add(
                version_name
            )

            runtime = version.get(
                "runtime"
            )

            if runtime not in SUPPORTED_RUNTIMES:

                raise ValueError(
                    f"{v_prefix}/runtime: "
                    f"{runtime!r} is invalid."
                )

            for required_key in (
                "download_sha256",
                "download_size",
                "download_url",
                "install_size",
                "platforms",
            ):

                if required_key not in version:

                    raise ValueError(
                        f"{v_prefix}/{required_key}: "
                        "required in generated feed."
                    )


def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "Build KiWay KiCad PCM packages "
            "and repository metadata."
        )
    )

    parser.add_argument(
        "--release-tag",
        default=DEFAULT_RELEASE_TAG,
        help=(
            "GitHub release tag WITHOUT "
            "the leading 'v'. "
            f"Default: {DEFAULT_RELEASE_TAG}"
        ),
    )

    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=(
            "Branch used for raw "
            "pcm/pkgs.json. "
            f"Default: {DEFAULT_BRANCH}"
        ),
    )

    parser.add_argument(
        "--clean-feed",
        action="store_true",
        help=(
            "Ignore existing pcm/pkgs.json "
            "version history and rebuild "
            "the feed from only the current "
            "metadata versions."
        ),
    )

    return parser.parse_args()


def main():

    args = parse_args()

    release_tag = (
        args.release_tag.removeprefix("v")
    )

    branch = args.branch

    base_path = Path(".")

    pcm_dir = Path(
        PCM_DIR
    )

    releases_dir = Path(
        RELEASES_DIR
    )

    pcm_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    releases_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    packages_file = (
        pcm_dir / "pkgs.json"
    )

    repo_file = (
        pcm_dir / "repo.json"
    )

    packages_data = {
        "packages": []
    }

    #
    # Load existing package history
    #

    if (
        packages_file.exists()
        and not args.clean_feed
    ):

        try:

            existing = load_json(
                packages_file
            )

            if (
                isinstance(existing, dict)
                and isinstance(
                    existing.get("packages"),
                    list,
                )
            ):

                packages_data = existing

            elif isinstance(
                existing,
                list,
            ):

                #
                # Migration from older
                # root-array feeds.
                #

                packages_data[
                    "packages"
                ] = existing

            else:

                print(
                    f"Warning: ignoring malformed "
                    f"existing {packages_file}; "
                    "rebuilding feed."
                )

        except Exception as exc:

            print(
                f"Warning: could not read "
                f"existing {packages_file}: "
                f"{exc}. Rebuilding feed."
            )

    #
    # Discover plugins
    #

    plugin_paths = discover_plugins(
        base_path
    )

    if not plugin_paths:

        raise RuntimeError(
            "No plugin directories "
            "containing metadata.json found."
        )

    #
    # Normalize source metadata
    #

    metadata_by_path = {}

    active_identifiers = set()

    for plugin_path in plugin_paths:

        source_metadata = load_json(
            plugin_path
            / "metadata.json"
        )

        metadata = normalize_metadata(
            source_metadata,
            plugin_path,
            branch,
        )

        identifier = metadata[
            "identifier"
        ]

        if identifier in active_identifiers:

            raise ValueError(
                f"Duplicate plugin identifier: "
                f"{identifier!r}"
            )

        active_identifiers.add(
            identifier
        )

        metadata_by_path[
            plugin_path
        ] = metadata

    #
    # Filesystem is authoritative for
    # which packages still exist.
    #

    packages_list = [
        package
        for package
        in packages_data["packages"]
        if package.get("identifier")
        in active_identifiers
    ]

    #
    # Normalize retained historical
    # runtime values.
    #

    for package in packages_list:

        versions = package.get(
            "versions",
            [],
        )

        if not isinstance(
            versions,
            list,
        ):
            versions = []

        package["versions"] = [
            normalize_runtime(version)
            for version
            in versions
        ]

    existing_by_id = {
        package.get("identifier"):
        package

        for package
        in packages_list

        if package.get("identifier")
    }

    #
    # Build every current package
    #

    for plugin_path in plugin_paths:

        metadata = metadata_by_path[
            plugin_path
        ]

        identifier = metadata[
            "identifier"
        ]

        current_version = (
            metadata["versions"][0]
        )

        version = current_version[
            "version"
        ]

        (
            zip_path,
            zip_filename,
        ) = create_plugin_zip(
            plugin_path,
            version,
            releases_dir,
            metadata,
        )

        file_size = os.path.getsize(
            zip_path
        )

        sha256 = calculate_sha256(
            zip_path
        )

        install_size = calculate_install_size(
            zip_path
        )

        version_info = normalize_runtime(
            current_version
        )

        version_info.update(
            {
                "download_sha256":
                    sha256,

                "download_size":
                    file_size,

                "download_url":
                    (
                        f"{REPO_URL_BASE}/"
                        f"v{release_tag}/"
                        f"{zip_filename}"
                    ),

                "install_size":
                    install_size,

                "platforms": [
                    "windows",
                    "linux",
                    "macos",
                ],
            }
        )

        package = {

            "name":
                metadata["name"],

            "description":
                metadata["description"],

            "description_full":
                metadata["description_full"],

            "identifier":
                identifier,

            "type":
                metadata["type"],

            "author":
                metadata["author"],

            "license":
                metadata["license"],

            "resources":
                metadata["resources"],

            "versions": [
                version_info
            ],
        }

        existing_package = (
            existing_by_id.get(
                identifier
            )
        )

        if existing_package is not None:

            versions = (
                existing_package.setdefault(
                    "versions",
                    [],
                )
            )

            if not isinstance(
                versions,
                list,
            ):

                versions = []

                existing_package[
                    "versions"
                ] = versions

            replaced = False

            for (
                index,
                existing_version,
            ) in enumerate(versions):

                if (
                    existing_version.get(
                        "version"
                    )
                    == version
                ):

                    versions[index] = (
                        version_info
                    )

                    replaced = True

                    break

            if not replaced:

                versions.insert(
                    0,
                    version_info,
                )

            #
            # Source metadata is authoritative
            # for ALL package-level fields.
            #
            # This fixes the previous bug where
            # author/license/type could remain stale.
            #

            for key in (
                "name",
                "description",
                "description_full",
                "identifier",
                "type",
                "author",
                "license",
                "resources",
            ):

                existing_package[
                    key
                ] = copy.deepcopy(
                    package[key]
                )

        else:

            packages_list.append(
                package
            )

            existing_by_id[
                identifier
            ] = package

        print(
            f"Updated package "
            f"{identifier} ({version})"
        )

    packages_data[
        "packages"
    ] = packages_list

    #
    # Validate before publishing anything.
    #

    validate_feed(
        packages_data
    )

    #
    # Write package feed
    #

    atomic_write_json(
        packages_file,
        packages_data,
    )

    print(
        f"Updated {packages_file}"
    )

    #
    # ================================================================
    #
    # IMPORTANT:
    #
    # This is the part the previous file was missing.
    #
    # KiCad's Plugin and Content Manager needs a separate
    # repository-level resources.zip to display icons for packages
    # that are not yet installed.
    #
    # ================================================================
    #

    (
        resources_zip,
        resources_icon_count,
    ) = create_repository_resources_zip(
        plugin_paths,
        metadata_by_path,
        releases_dir,
    )

    packages_timestamp = int(
        datetime.datetime.now(
            datetime.timezone.utc
        ).timestamp()
    )

    resources_sha256 = (
        calculate_sha256(
            resources_zip
        )
    )

    packages_url = (
        f"https://raw.githubusercontent.com/"
        f"{REPO_OWNER}/"
        f"{REPO_NAME}/"
        f"{branch}/"
        f"pcm/pkgs.json"
        f"?t={packages_timestamp}"
    )

    #
    # Repository descriptor
    #

    repository = {

        "$schema":
            PCM_SCHEMA,

        "name":
            "KiWay Plugin Repository",

        "maintainer": {

            "name":
                "Wayri (Yawar)",

            "contact": {
                "github":
                    GITHUB_PROFILE,
            },
        },

        "packages": {

            "url":
                packages_url,

            "update_timestamp":
                packages_timestamp,
        },

        #
        # THIS section tells KiCad where
        # the repository icon archive lives.
        #

        "resources": {

            "url":
                (
                    f"{REPO_URL_BASE}/"
                    f"v{release_tag}/"
                    f"resources.zip"
                ),

            "sha256":
                resources_sha256,

            "update_timestamp":
                packages_timestamp,
        },
    }

    atomic_write_json(
        repo_file,
        repository,
    )

    print(
        f"Updated {repo_file}"
    )

    print(
        f"Packages: "
        f"{len(packages_list)}"
    )

    print(
        f"Release tag: "
        f"v{release_tag}"
    )

    print(
        f"Branch: {branch}"
    )

    print(
        f"Repository icons: "
        f"{resources_icon_count}"
    )

    print(
        f"Repository resources: "
        f"{resources_zip}"
    )

    print()

    print(
        "PCM build completed successfully."
    )


if __name__ == "__main__":
    main()