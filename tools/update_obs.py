#!/usr/bin/env python3
import argparse
import email.parser
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

UPSTREAM_URL = "https://github.com/amnezia-vpn/amnezia-client.git"
UPSTREAM_BRANCH = "dev"
CONAN_VERSION = "2.28.0"
CONAN_URL = f"https://github.com/conan-io/conan/archive/refs/tags/{CONAN_VERSION}.tar.gz"
CONAN_SHA256 = "ed837130fff9cfda8b957dcfcf4818bd6819f49e634fd112d308da8ef376658d"
OBS_PROJECT = "home:dwolfF:amnezia-vpn:staging"
OBS_PACKAGE = "amneziavpn-secure"
MAINTAINER = "Dmitriy Volkov <dennshield@duck.com>"
CLIENT_CONFIG_VARIABLES = (
    "PROD_AGW_PUBLIC_KEY",
    "PROD_S3_ENDPOINT",
    "FALLBACK_S3_ENDPOINT",
    "DEV_AGW_PUBLIC_KEY",
    "DEV_AGW_ENDPOINT",
    "DEV_S3_ENDPOINT",
    "FREE_V2_ENDPOINT",
    "PREM_V1_ENDPOINT",
)
SYSTEM_DEPENDENCIES = {"libssh", "openssl", "zlib"}
NON_LINUX_DEPENDENCIES = {
    "amnezia-libxray",
    "awg-android",
    "awg-apple",
    "awg-windows",
    "hev-socks5-tunnel",
    "openvpn-pt-android",
    "openvpnadapter",
    "tap-windows6",
    "win-split-tunnel",
    "wintun",
}


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_text_atomic(path, content, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    if mode is not None:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        handle = os.fdopen(fd, "w", encoding="utf-8")
    else:
        handle = temporary.open("w", encoding="utf-8")
    try:
        with handle as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)


def normalized_text(path):
    return "\n".join(line.rstrip() for line in path.read_text().splitlines()).strip()


def packaging_digest(repository):
    paths = []
    debian_dir = repository / "debian"
    if debian_dir.is_dir():
        for path in debian_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(repository).as_posix()
            if rel in {"debian/changelog", "debian/client-config.env"}:
                continue
            paths.append(path)

    for rel in (
        "obs/build.script",
        "vendor/conanfile.py",
        "vendor/3rdparty.cmake",
        "vendor/recipes_bootstrap.cmake",
    ):
        candidate = repository / rel
        if candidate.is_file():
            paths.append(candidate)

    recipes_dir = repository / "vendor/recipes"
    if recipes_dir.is_dir():
        for path in recipes_dir.rglob("*"):
            if path.is_file():
                paths.append(path)

    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.relative_to(repository).as_posix()):
        rel = path.relative_to(repository).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def remove_git_metadata(path):
    for candidate in path.rglob(".git"):
        if candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()


def create_archive(source, archive, timestamp):
    run(
        "tar",
        "--sort=name",
        f"--mtime=@{timestamp}",
        "--owner=0",
        "--group=0",
        "--numeric-owner",
        "-cJf",
        str(archive),
        "-C",
        str(source.parent),
        source.name,
    )


def validate_packaging_overrides(upstream, repository):
    conanfile = (upstream / "conanfile.py").read_text()
    conanfile = re.sub(r"\n\s*# expicitly use libssh[^\n]*", "", conanfile)
    conanfile = re.sub(
        r"\n\s*self\.requires\(\"(?:libssh|openssl|zlib)/[^\"]+\"\)",
        "",
        conanfile,
    )
    expected_conanfile = repository / "vendor/conanfile.py"
    if "\n".join(line.rstrip() for line in conanfile.splitlines()).strip() != normalized_text(expected_conanfile):
        raise RuntimeError("The upstream Conan manifest changed; review the offline dependency overrides")

    third_party = (upstream / "client/cmake/3rdparty.cmake").read_text()
    third_party = third_party.replace(
        "list(APPEND LIBS ssh::ssh)",
        "if(TARGET ssh AND NOT TARGET ssh::ssh)\n"
        "    add_library(ssh::ssh ALIAS ssh)\n"
        "endif()\n"
        "list(APPEND LIBS ssh::ssh)",
    )
    if "\n".join(line.rstrip() for line in third_party.splitlines()).strip() != normalized_text(
        repository / "vendor/3rdparty.cmake"
    ):
        raise RuntimeError("The upstream third-party CMake file changed; review the libssh target override")

    bootstrap = (upstream / "cmake/recipes_bootstrap.cmake").read_text()
    bootstrap = re.sub(
        r"\nexecute_process\(\s*COMMAND \$\{CONAN_COMMAND\} remote add amnezia .*?\n\)\s*",
        "\n",
        bootstrap,
        flags=re.DOTALL,
    )
    if " ".join(bootstrap.split()) != " ".join((repository / "vendor/recipes_bootstrap.cmake").read_text().split()):
        raise RuntimeError("The upstream Conan bootstrap changed; review the remote repository override")


def validate_dependency_versions(upstream, repository):
    recipes = {}
    for recipe in (repository / "vendor/recipes").glob("*/conanfile.py"):
        text = recipe.read_text()
        name = re.search(r'^\s*name = "([^"]+)"', text, re.MULTILINE)
        version = re.search(r'^\s*version = "([^"]+)"', text, re.MULTILINE)
        if name and version:
            recipes[name.group(1)] = version.group(1)

    manifest = (upstream / "conanfile.py").read_text()
    for reference in re.findall(r'self\.requires\("([^"]+)"\)', manifest):
        name, version = reference.split("/", 1)
        version = version.split("@", 1)[0]
        if name in recipes and recipes[name] != version:
            raise RuntimeError(
                f"Upstream requires {name}/{version}, but the offline archive contains {recipes[name]}"
            )
        if name not in recipes and name not in SYSTEM_DEPENDENCIES | NON_LINUX_DEPENDENCIES:
            raise RuntimeError(f"Upstream requires a new dependency without an offline recipe: {name}")


def validate_debian_patches(upstream, repository):
    patches_dir = repository / "debian/patches"
    series = patches_dir / "series"
    if not series.is_file():
        return

    patch_names = []
    for raw_line in series.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patch_name = stripped.split("#", 1)[0].strip().split()[0]
        patch_names.append(patch_name)

    if not patch_names:
        return

    patches_root = patches_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="amnezia-patch-check-") as temporary:
        scratch_copy = Path(temporary) / "upstream"
        shutil.copytree(upstream, scratch_copy, ignore=shutil.ignore_patterns(".git"))
        for patch_name in patch_names:
            patch_path = (patches_dir / patch_name).resolve()
            if not patch_path.is_relative_to(patches_root) or not patch_path.is_file():
                raise RuntimeError(f"Missing or invalid Debian patch in series: {patch_name}")
            try:
                subprocess.run(
                    ("patch", "-p1", "--batch", "--forward", "-s", "-i", str(patch_path)),
                    cwd=scratch_copy,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as error:
                raise RuntimeError(
                    f"Debian patch {patch_name} failed to apply cleanly; review debian/patches"
                ) from error


def recipe_hashes(upstream):
    return {
        str(path.relative_to(upstream)): sha256_file(path)
        for path in sorted((upstream / "recipes").rglob("*"))
        if path.is_file()
    }


def write_client_config(packaging):
    values = {}
    config_source = os.environ.get("CLIENT_CONFIG_FILE")
    if config_source:
        for token in shlex.split(Path(config_source).read_text(), comments=True):
            if token == "export":
                continue
            name, separator, value = token.partition("=")
            if separator and name in CLIENT_CONFIG_VARIABLES:
                values[name] = value
    for name in CLIENT_CONFIG_VARIABLES:
        value = values.get(name) or os.environ.get(name)
        if not value:
            raise RuntimeError(f"The {name} repository secret is required")
        if name.endswith("PUBLIC_KEY"):
            value = value.replace("\n", "\\n")
        values[name] = value
    content = "".join(f"export {name}={shlex.quote(value)}\n" for name, value in values.items())
    write_text_atomic(packaging / "client-config.env", content, mode=0o600)


def prepend_changelog_entry(changelog_text, package_version, commit):
    first_line = changelog_text.lstrip().splitlines()[0] if changelog_text.strip() else ""
    if first_line.startswith(f"amneziavpn ({package_version}) "):
        return changelog_text
    entry = (
        f"amneziavpn ({package_version}) resolute; urgency=medium\n\n"
        f"  * Update to upstream commit {commit}.\n\n"
        f" -- {MAINTAINER}  {format_datetime(datetime.now(timezone.utc))}\n\n"
    )
    return entry + changelog_text


def next_obs_revision(upstream_version, known_versions):
    pattern = re.compile(rf"^{re.escape(upstream_version)}-0ubuntu1~obs(\d+)$")
    revisions = []
    for version in known_versions:
        if not version:
            continue
        match = pattern.fullmatch(version)
        if match:
            revisions.append(int(match.group(1)))
    return max(revisions, default=0) + 1


def ensure_version_monotonic(package_version, baseline_version):
    if not baseline_version or baseline_version == package_version:
        return
    result = subprocess.run(
        ("dpkg", "--compare-versions", package_version, "gt", baseline_version),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Generated package version {package_version} is not greater than {baseline_version}"
        )


def parse_build_depends(control_path):
    lines = [line for line in control_path.read_text().splitlines() if not line.startswith("#")]
    source_paragraph = "\n".join(lines).split("\n\n", 1)[0]
    parsed = email.parser.Parser().parsestr(source_paragraph)
    raw = parsed.get("Build-Depends")
    if not raw:
        raise RuntimeError("debian/control is missing Build-Depends")
    return " ".join(raw.split())


def create_dsc(work, repository, upstream_version, package_version):
    build_depends = parse_build_depends(repository / "debian/control")
    names = [
        f"amneziavpn_{upstream_version}.orig.tar.xz",
        f"amneziavpn_{upstream_version}.orig-vendor.tar.xz",
        f"amneziavpn_{upstream_version}.orig-conan.tar.xz",
        f"amneziavpn_{package_version}.debian.tar.xz",
    ]
    entries = []
    for name in names:
        data = (work / name).read_bytes()
        entries.append(
            (
                name,
                len(data),
                hashlib.md5(data).hexdigest(),
                hashlib.sha1(data).hexdigest(),
                hashlib.sha256(data).hexdigest(),
            )
        )
    lines = [
        "Format: 3.0 (quilt)",
        "Source: amneziavpn",
        "Binary: amneziavpn",
        "Architecture: amd64",
        f"Version: {package_version}",
        f"Maintainer: {MAINTAINER}",
        "Homepage: https://amnezia.org/",
        "Standards-Version: 4.7.2",
        f"Build-Depends: {build_depends}",
        "Package-List:",
        " amneziavpn deb net optional arch=amd64",
        "Checksums-Sha1:",
    ]
    lines.extend(f" {sha1sum} {size} {name}" for name, size, _, sha1sum, _ in entries)
    lines.append("Checksums-Sha256:")
    lines.extend(f" {sha256sum} {size} {name}" for name, size, _, _, sha256sum in entries)
    lines.append("Files:")
    lines.extend(f" {md5sum} {size} {name}" for name, size, md5sum, _, _ in entries)
    dsc = work / f"amneziavpn_{package_version}.dsc"
    dsc.write_text("\n".join(lines) + "\n")
    return [repository / "obs/build.script"] + [work / name for name in names] + [dsc]


def upload_sources(work, files):
    config_source = os.environ.get("OSC_CONFIG")
    if config_source:
        config = Path(config_source)
        if not config.is_file():
            raise RuntimeError("OSC_CONFIG must point to an existing osc configuration")
    else:
        user = os.environ.get("OBS_USER")
        password = os.environ.get("OBS_PASSWORD")
        if not user or not password:
            raise RuntimeError("OSC_CONFIG (or OBS_USER and OBS_PASSWORD) must be configured")
        config = work / "oscrc"
        write_text_atomic(
            config,
            "[general]\n"
            "apiurl = https://api.opensuse.org\n"
            "[https://api.opensuse.org]\n"
            f"user = {user}\n"
            f"pass = {password}\n",
            mode=0o600,
        )
    osc = ("osc", "--config", str(config), "--no-keyring")
    checkout = work / "checkout"
    checkout.mkdir()
    run(*osc, "checkout", OBS_PROJECT, OBS_PACKAGE, cwd=checkout)
    package = checkout / OBS_PROJECT / OBS_PACKAGE
    new_names = {source.name for source in files}
    for pattern in ("amneziavpn_*.tar.xz", "amneziavpn_*.dsc"):
        for old_file in package.glob(pattern):
            if old_file.name not in new_names:
                run(*osc, "rm", old_file.name, cwd=package)
    for source in files:
        destination = package / source.name
        is_tracked = destination.exists()
        shutil.copy2(source, destination)
        if not is_tracked:
            run(*osc, "add", source.name, cwd=package)
    run(*osc, "commit", "-m", f"chore: update to {files[-1].stem}", cwd=package)


def load_json_if_exists(path):
    return json.loads(path.read_text()) if path.exists() else {}


def main():
    parser = argparse.ArgumentParser(description="Prepare and upload AmneziaVPN source packages to OBS staging")
    parser.add_argument("--force", action="store_true", help="Upload a new OBS revision even if commit and packaging are unchanged")
    args = parser.parse_args()

    repository = Path(__file__).resolve().parent.parent
    state_path = repository / "obs/upstream.json"
    state = load_json_if_exists(state_path)
    candidate = load_json_if_exists(repository / ".state/candidate.json")
    stable = load_json_if_exists(repository / ".state/stable.json")
    latest = candidate or stable or state
    current_packaging = packaging_digest(repository)

    with tempfile.TemporaryDirectory(prefix="amneziavpn-update-") as temporary:
        work = Path(temporary)
        upstream = work / "upstream"
        run(
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            UPSTREAM_BRANCH,
            UPSTREAM_URL,
            str(upstream),
        )
        commit = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=upstream, text=True).strip()
        if not args.force and latest.get("commit") == commit and latest.get("packaging_sha256") == current_packaging:
            print(f"Upstream and packaging are unchanged at {commit}")
            return

        timestamp = int(subprocess.check_output(("git", "show", "-s", "--format=%ct", "HEAD"), cwd=upstream, text=True))
        validate_packaging_overrides(upstream, repository)
        validate_dependency_versions(upstream, repository)
        current_recipe_hashes = recipe_hashes(upstream)
        baseline_recipes = (
            state.get("upstream_recipes")
            or candidate.get("upstream_recipes")
            or stable.get("upstream_recipes")
            or current_recipe_hashes
        )
        if baseline_recipes != current_recipe_hashes:
            raise RuntimeError("Upstream Conan recipes changed; review and refresh the offline recipes")
        validate_debian_patches(upstream, repository)

        cmake = (upstream / "CMakeLists.txt").read_text()
        upstream_release = re.search(r"set\(AMNEZIAVPN_VERSION ([^ )]+)", cmake).group(1)
        date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y%m%d")
        upstream_version = f"{upstream_release}+git{date}.{commit[:12]}"

        changelog_path = repository / "debian/changelog"
        original_changelog = changelog_path.read_text()
        known_versions = re.findall(r"^amneziavpn \(([^)]+)\)", original_changelog, re.MULTILINE)
        for record in (state, candidate, stable):
            if record.get("package_version"):
                known_versions.append(record["package_version"])
        obs_revision = next_obs_revision(upstream_version, known_versions)
        package_version = f"{upstream_version}-0ubuntu1~obs{obs_revision}"
        ensure_version_monotonic(package_version, stable.get("package_version"))

        source = work / f"amneziavpn-{upstream_version}"
        upstream.rename(source)
        orig_parent = work / "orig"
        orig_source = orig_parent / source.name
        shutil.copytree(source, orig_source, ignore=shutil.ignore_patterns(".git"))
        create_archive(orig_source, work / f"amneziavpn_{upstream_version}.orig.tar.xz", timestamp)
        shutil.rmtree(orig_parent)

        run("git", "submodule", "update", "--init", "--recursive", "--depth", "1", cwd=source)
        submodule_paths = subprocess.check_output(
            ("git", "config", "-f", ".gitmodules", "--get-regexp", r"submodule\..*\.path"),
            cwd=source,
            text=True,
        ).splitlines()
        vendor = work / "vendor"
        shutil.copytree(repository / "vendor", vendor)
        shutil.rmtree(vendor / "submodules")
        (vendor / "submodules").mkdir()
        for entry in submodule_paths:
            relative_path = Path(entry.split(maxsplit=1)[1])
            shutil.copytree(source / relative_path, vendor / "submodules" / relative_path.name)
        remove_git_metadata(vendor)
        create_archive(vendor, work / f"amneziavpn_{upstream_version}.orig-vendor.tar.xz", timestamp)

        conan_archive = work / "conan.tar.gz"
        urllib.request.urlretrieve(CONAN_URL, conan_archive)
        if sha256_file(conan_archive) != CONAN_SHA256:
            raise RuntimeError("The pinned Conan source archive failed its SHA-256 check")
        conan_extract = work / "conan-extract"
        with tarfile.open(conan_archive) as archive:
            archive.extractall(conan_extract, filter="data")
        tools = work / "tools"
        tools.mkdir()
        (conan_extract / f"conan-{CONAN_VERSION}").rename(tools / "conan")
        create_archive(tools, work / f"amneziavpn_{upstream_version}.orig-conan.tar.xz", timestamp)

        new_changelog = prepend_changelog_entry(original_changelog, package_version, commit)
        packaging = work / "debian"
        shutil.copytree(repository / "debian", packaging)
        (packaging / "changelog").write_text(new_changelog)
        write_client_config(packaging)
        create_archive(packaging, work / f"amneziavpn_{package_version}.debian.tar.xz", timestamp)
        files = create_dsc(work, repository, upstream_version, package_version)
        upload_sources(work, files)

        write_text_atomic(changelog_path, new_changelog)
        next_state = {
            "commit": commit,
            "package_version": package_version,
            "packaging_sha256": current_packaging,
            "upstream_recipes": current_recipe_hashes,
            "upstream_version": upstream_release,
        }
        write_text_atomic(state_path, json.dumps(next_state, indent=2, sort_keys=True) + "\n")
        print(f"Uploaded AmneziaVPN {package_version} from upstream commit {commit}")


if __name__ == "__main__":
    main()
