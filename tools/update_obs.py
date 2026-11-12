#!/usr/bin/env python3
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


def normalized_text(path):
    return "\n".join(line.rstrip() for line in path.read_text().splitlines()).strip()


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
        for token in shlex.split(Path(config_source).read_text()):
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
    config = packaging / "client-config.env"
    config.write_text("".join(f"export {name}={shlex.quote(value)}\n" for name, value in values.items()))
    config.chmod(0o600)


def update_changelog(repository, package_version, commit):
    changelog = repository / "debian/changelog"
    entry = (
        f"amneziavpn ({package_version}) resolute; urgency=medium\n\n"
        f"  * Update to upstream commit {commit}.\n\n"
        f" -- {MAINTAINER}  {format_datetime(datetime.now(timezone.utc))}\n\n"
    )
    changelog.write_text(entry + changelog.read_text())


def create_dsc(work, repository, upstream_version, package_version):
    control = (repository / "debian/control").read_text()
    build_depends = re.search(r"^Build-Depends:\n((?: .+\n)+)", control, re.MULTILINE).group(1)
    build_depends = " ".join(line.strip() for line in build_depends.splitlines())
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
            raise RuntimeError("OBS_USER and OBS_PASSWORD must be configured as GitHub Actions secrets")
        config = work / "oscrc"
        config.write_text(
            "[general]\n"
            "apiurl = https://api.opensuse.org\n"
            "[https://api.opensuse.org]\n"
            f"user = {user}\n"
            f"pass = {password}\n"
        )
        config.chmod(0o600)
    osc = ("osc", "--config", str(config), "--no-keyring")
    checkout = work / "checkout"
    checkout.mkdir()
    run(*osc, "checkout", OBS_PROJECT, OBS_PACKAGE, cwd=checkout)
    package = checkout / OBS_PROJECT / OBS_PACKAGE
    for old_file in package.glob("amneziavpn_*.tar.xz"):
        run(*osc, "rm", old_file.name, cwd=package)
    for old_file in package.glob("amneziavpn_*.dsc"):
        run(*osc, "rm", old_file.name, cwd=package)
    for source in files:
        destination = package / source.name
        is_tracked = destination.exists()
        shutil.copy2(source, destination)
        if not is_tracked:
            run(*osc, "add", source.name, cwd=package)
    run(*osc, "commit", "-m", f"chore: update to {files[-1].stem}", cwd=package)


def main():
    repository = Path(__file__).resolve().parent.parent
    state_path = repository / "obs/upstream.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
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
        if state.get("commit") == commit:
            print(f"Upstream is unchanged at {commit}")
            return

        timestamp = int(subprocess.check_output(("git", "show", "-s", "--format=%ct", "HEAD"), cwd=upstream, text=True))
        validate_packaging_overrides(upstream, repository)
        validate_dependency_versions(upstream, repository)
        current_recipe_hashes = recipe_hashes(upstream)
        if state.get("upstream_recipes", current_recipe_hashes) != current_recipe_hashes:
            raise RuntimeError("Upstream Conan recipes changed; review and refresh the offline recipes")

        cmake = (upstream / "CMakeLists.txt").read_text()
        upstream_release = re.search(r"set\(AMNEZIAVPN_VERSION ([^ )]+)", cmake).group(1)
        date = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y%m%d")
        upstream_version = f"{upstream_release}+git{date}.{commit[:12]}"
        package_version = f"{upstream_version}-0ubuntu1~obs1"
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

        update_changelog(repository, package_version, commit)
        packaging = work / "debian"
        shutil.copytree(repository / "debian", packaging)
        write_client_config(packaging)
        create_archive(packaging, work / f"amneziavpn_{package_version}.debian.tar.xz", timestamp)
        files = create_dsc(work, repository, upstream_version, package_version)
        upload_sources(work, files)

        state = {
            "commit": commit,
            "package_version": package_version,
            "upstream_recipes": current_recipe_hashes,
            "upstream_version": upstream_release,
        }
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        print(f"Uploaded AmneziaVPN {package_version} from upstream commit {commit}")


if __name__ == "__main__":
    main()
