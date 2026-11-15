#!/usr/bin/env python3
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from tools.update_obs import packaging_digest
except ImportError:
    from update_obs import packaging_digest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".state"
STAGING = "home:dwolfF:amnezia-vpn:staging"
STABLE = "home:dwolfF:amnezia-vpn"
PACKAGE = "amneziavpn-secure"
BINARY_PACKAGE = "amneziavpn"
REPOSITORY = "xUbuntu_26.04"
ARCHITECTURE = "x86_64"
KEEP_STABLE = 2
UPSTREAM_URL = "https://github.com/amnezia-vpn/amnezia-client.git"
UPSTREAM_BRANCH = "dev"


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, text=True, timeout=3600, **kwargs)


def osc(*args):
    return run(
        ["osc", "--no-keyring", "--setopt", f"cookiejar={STATE / 'osc-cookiejar'}", *args],
        capture_output=True,
    ).stdout


def api(path, method="GET", data=None, file=None):
    args = ["api", "-X", method]
    if data is not None:
        args += ["-d", data]
    if file is not None:
        args += ["-T", str(file)]
    return osc(*args, path)


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def save_json(path, record):
    temporary = path.with_suffix(".new")
    with temporary.open("w") as output:
        json.dump(record, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def store_record(filename, record):
    if os.environ.get("AMNEZIA_CLOUD") == "1":
        api(f"/source/{STAGING}/pipeline-state/{filename}", "PUT", json.dumps(record, indent=2, sort_keys=True) + "\n")
    save_json(STATE / filename, record)


def load_remote_state():
    try:
        listing = ET.fromstring(api(f"/source/{STAGING}/pipeline-state"))
    except subprocess.CalledProcessError as error:
        if "404" in (error.stderr or ""):
            return
        raise
    for entry in listing.findall("entry"):
        filename = entry.attrib.get("name")
        if filename in {"candidate.json", "stable.json"}:
            save_json(STATE / filename, json.loads(api(f"/source/{STAGING}/pipeline-state/{filename}")))


def source_md5():
    return ET.fromstring(api(f"/source/{STAGING}/{PACKAGE}")).attrib["srcmd5"]


def expanded_md5():
    return ET.fromstring(api(f"/source/{STAGING}/{PACKAGE}?expand=1")).attrib["srcmd5"]


def build_revision():
    revision = ET.fromstring(api(f"/build/{STAGING}/{REPOSITORY}/{ARCHITECTURE}/{PACKAGE}/_buildinfo")).findtext("srcmd5")
    if not revision:
        raise ValueError("OBS buildinfo is missing the source revision")
    return revision


def require_same_revision(before, after):
    if not before or before != after:
        raise ValueError("The source revision changed during verification")


def build_succeeded():
    result_list = ET.fromstring(api(f"/build/{STAGING}/_result?package={PACKAGE}"))
    ready = any(
        entry.attrib.get("repository") == REPOSITORY
        and entry.attrib.get("arch") == ARCHITECTURE
        and entry.attrib.get("dirty") != "true"
        and any(
            status.attrib.get("package") == PACKAGE and status.attrib.get("code") == "succeeded"
            for status in entry.findall("status")
        )
        for entry in result_list.findall("result")
    )
    if not ready:
        return False
    try:
        return build_revision() == expanded_md5()
    except ValueError:
        return False


def fetch_binary(filename, destination):
    part = destination.with_suffix(destination.suffix + ".part")
    with part.open("wb") as output:
        run(
            [
                "osc",
                "--no-keyring",
                "--setopt",
                f"cookiejar={STATE / 'osc-cookiejar'}",
                "api",
                f"/build/{STAGING}/{REPOSITORY}/{ARCHITECTURE}/{PACKAGE}/{filename}",
            ],
            stdout=output,
            stderr=subprocess.PIPE,
        )
    os.replace(part, destination)


def reconcile():
    candidate_path = STATE / "candidate.json"
    if not candidate_path.exists():
        return
    record = json.loads(candidate_path.read_text())
    stable_path = STATE / "stable.json"
    if stable_path.exists() and json.loads(stable_path.read_text()).get("srcmd5") == record["srcmd5"]:
        return
    if not build_succeeded():
        print("Staging is not ready; stable is unchanged", flush=True)
        return
    require_same_revision(record["srcmd5"], source_md5())
    info = build_revision()
    require_same_revision(expanded_md5(), info)
    directory = ET.fromstring(api(f"/build/{STAGING}/{REPOSITORY}/{ARCHITECTURE}/{PACKAGE}"))
    filename = f"{BINARY_PACKAGE}_{record['package_version']}_amd64.deb"
    if filename not in {binary.attrib.get("filename") for binary in directory}:
        raise ValueError("The expected binary is absent")
    destination = STATE / "binaries" / record["srcmd5"] / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    fetch_binary(filename, destination)
    artifact_sha = sha256(destination)
    run([ROOT / "tools/verify-deb.sh", destination, BINARY_PACKAGE, record["package_version"]])
    if sha256(destination) != artifact_sha:
        raise ValueError("The verified binary changed on disk")
    require_same_revision(record["srcmd5"], source_md5())
    require_same_revision(info, build_revision())
    check = STATE / "recheck"
    check.mkdir(exist_ok=True)
    fetch_binary(filename, check / filename)
    if sha256(check / filename) != artifact_sha:
        raise ValueError("The server artifact changed during verification")
    osc(
        "release",
        STAGING,
        PACKAGE,
        "-r",
        REPOSITORY,
        "-a",
        ARCHITECTURE,
        "--target-project",
        STABLE,
        "--target-repository",
        REPOSITORY,
        "--no-delay",
    )
    record.update(binary_sha256=artifact_sha, verified_at=int(time.time()))
    store_record("stable.json", record)
    prune_state()
    print(f"Released verified {record['package_version']}", flush=True)


def _version_key(package_version):
    match = re.fullmatch(
        r"(\d+(?:\.\d+)+)(?:\+git(\d+)\.[0-9a-f]+)?(?:-0ubuntu(\d+)(?:~obs(\d+))?)?",
        package_version,
    )
    if not match:
        return ((-1,), -1, -1, -1)
    return (
        tuple(int(part) for part in match.group(1).split(".")),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
        int(match.group(4) or 0),
    )


def prune_state(keep=KEEP_STABLE):
    """Keep at most `keep` recent binaries in local `.state/`."""
    records = []
    for filename in ("stable.json", "candidate.json"):
        rec_path = STATE / filename
        if rec_path.exists():
            records.append(json.loads(rec_path.read_text()))
    pinned_md5 = {record["srcmd5"] for record in records if "srcmd5" in record}

    binaries_root = STATE / "binaries"
    if binaries_root.is_dir():
        pattern = re.compile(rf"^{re.escape(BINARY_PACKAGE)}_(.+)_amd64\.deb$")
        debs = []
        for directory in binaries_root.iterdir():
            if not directory.is_dir():
                continue
            for file in directory.iterdir():
                match = pattern.fullmatch(file.name)
                if file.is_file() and match:
                    debs.append((file, match.group(1)))

        ordered = sorted(
            debs,
            key=lambda item: (_version_key(item[1]), item[0].stat().st_mtime_ns),
            reverse=True,
        )
        kept = [item for item in ordered if item[0].parent.name in pinned_md5]
        for item in ordered:
            if len(kept) >= keep:
                break
            if item not in kept:
                kept.append(item)
        kept_files = {file for file, _ in kept}
        kept_dirs = {file.parent for file in kept_files} | {binaries_root / md5 for md5 in pinned_md5}
        for directory in list(binaries_root.iterdir()):
            if not directory.is_dir():
                continue
            if directory not in kept_dirs:
                shutil.rmtree(directory)
                continue
            for file in directory.iterdir():
                if file.is_file() and file not in kept_files:
                    file.unlink()
            if not any(directory.iterdir()):
                directory.rmdir()

    recheck_root = STATE / "recheck"
    if recheck_root.is_dir():
        for item in recheck_root.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()


def init_obs():
    try:
        current = api(f"/source/{STABLE}/_meta")
    except subprocess.CalledProcessError as error:
        if "404" not in error.stderr:
            raise
        raise ValueError("The existing stable project is required") from error
    if "Native AmneziaVPN builds" not in current:
        raise ValueError("The stable project is not owned by this pipeline")
    staging_xml = f'''<project name="{STAGING}"><title>AmneziaVPN Ubuntu staging</title>
<description>Protected AmneziaVPN sources and binaries requiring automated installation and GUI checks before release.</description>
<person userid="dwolfF" role="maintainer"/><publish><disable/></publish>
<repository name="{REPOSITORY}"><releasetarget project="{STABLE}" repository="{REPOSITORY}" trigger="manual"/>
<path project="Ubuntu:26.04" repository="standard"/><path project="Ubuntu:26.04" repository="universe"/>
<path project="Ubuntu:26.04" repository="universe-update"/><arch>{ARCHITECTURE}</arch></repository></project>'''
    try:
        current = api(f"/source/{STAGING}/_meta")
    except subprocess.CalledProcessError as error:
        if "404" not in error.stderr:
            raise
        api(f"/source/{STAGING}/_meta", "PUT", staging_xml)
    else:
        if "Protected AmneziaVPN sources" not in current:
            raise ValueError("The staging project is not owned by this pipeline")
    for name, title in ((PACKAGE, "AmneziaVPN protected build"), ("pipeline-state", "AmneziaVPN pipeline provenance")):
        try:
            api(f"/source/{STAGING}/{name}/_meta")
        except subprocess.CalledProcessError as error:
            if "404" not in error.stderr:
                raise
            build = "<build><disable/></build>" if name == "pipeline-state" else ""
            publish = "<publish><disable/></publish>" if name == "pipeline-state" else ""
            api(
                f"/source/{STAGING}/{name}/_meta",
                "PUT",
                f'<package name="{name}" project="{STAGING}"><title>{title}</title>'
                f"<description>Managed by the AmneziaVPN controller</description>{build}{publish}"
                "<sourceaccess><disable/></sourceaccess></package>",
            )
    for project in (STABLE, STAGING):
        api(f"/source/{project}/_config", "PUT", "PublishFlags: nofailedpackages\n")
    print("OBS staging and stable projects are ready", flush=True)


def upstream_commit():
    output = run(["git", "ls-remote", UPSTREAM_URL, f"refs/heads/{UPSTREAM_BRANCH}"], capture_output=True).stdout
    commit = output.split()[0]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Unexpected upstream revision")
    return commit


def latest_submitted_record():
    for path in (STATE / "candidate.json", STATE / "stable.json", ROOT / "obs/upstream.json"):
        if path.exists():
            return json.loads(path.read_text())
    return {}


def submit_if_needed():
    state_path = ROOT / "obs/upstream.json"
    previous = latest_submitted_record()
    commit = upstream_commit()
    current_packaging = packaging_digest(ROOT)
    if previous.get("commit") == commit and previous.get("packaging_sha256") == current_packaging:
        print(f"Upstream and packaging are unchanged at {commit}", flush=True)
        return False
    run(["python3", "tools/update_obs.py"], cwd=ROOT)
    record = json.loads(state_path.read_text())
    record.update(srcmd5=source_md5(), prepared_at=int(time.time()))
    store_record("candidate.json", record)
    print(f"Submitted {record['package_version']} from {commit}", flush=True)
    return True


def wait_for_builds():
    deadline = time.monotonic() + 5400
    while True:
        candidate_path = STATE / "candidate.json"
        stable_path = STATE / "stable.json"
        if not candidate_path.exists():
            return
        candidate = json.loads(candidate_path.read_text())
        if stable_path.exists() and json.loads(stable_path.read_text()).get("srcmd5") == candidate["srcmd5"]:
            return
        result_list = ET.fromstring(api(f"/build/{STAGING}/_result?package={PACKAGE}"))
        errors = [
            status.attrib["code"]
            for entry in result_list.findall("result")
            if entry.attrib.get("repository") == REPOSITORY
            and entry.attrib.get("arch") == ARCHITECTURE
            and entry.attrib.get("dirty") != "true"
            for status in entry.findall("status")
            if status.attrib.get("package") == PACKAGE
            and status.attrib.get("code") in {"failed", "broken", "unresolvable", "disabled", "excluded"}
        ]
        if errors and time.time() - candidate["prepared_at"] > 180:
            raise ValueError(f"OBS build failed with {errors}; stable is unchanged")
        if build_succeeded():
            reconcile()
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for the OBS build")
        print("Waiting for the OBS build", flush=True)
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init-obs", "discover", "cycle", "reconcile"))
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    STATE.chmod(0o700)
    with (STATE / "pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another controller cycle is active")
            return
        if args.action == "init-obs":
            init_obs()
        elif args.action == "discover":
            print(upstream_commit())
        elif args.action == "reconcile":
            reconcile()
        else:
            try:
                load_remote_state()
                reconcile()
                submit_if_needed()
                wait_for_builds()
            finally:
                prune_state()


if __name__ == "__main__":
    main()
