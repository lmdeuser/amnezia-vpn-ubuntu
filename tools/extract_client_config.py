#!/usr/bin/env python3
import argparse
import hashlib
import ipaddress
import os
import re
import shlex
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "5.1.0.6"
APK_NAME = f"AmneziaVPN_{RELEASE}_android11+_arm64-v8a.apk"
APK_URL = f"https://github.com/amnezia-vpn/amnezia-client/releases/download/{RELEASE}/{APK_NAME}"
APK_SHA256 = "27a937655e0c50a90e0dba1316244914f95a361185cbf446d0e897424a64059d"
NATIVE_LIBRARY = "lib/arm64-v8a/libAmneziaVPN_arm64-v8a.so"
PROD_S3 = (
    "https://s3.eu-north-1.amazonaws.com/amnezia/, "
    "https://storage.googleapis.com/lambda-list/, "
    "https://amnzstrg01.blob.core.windows.net/lambda-list/, "
    "https://objectstorage.eu-zurich-1.oraclecloud.com/n/zrhfyaq6qxvh/b/lambda-list/o/"
)
FALLBACK_S3 = (
    "https://storage.mwsapis.ru/lambda-list/, "
    "https://46.8.209.252/lambda-list/, "
    "https://s3.cloudruserapi.net/lambda-list/"
)


def c_string(data, offset):
    end = data.index(0, offset)
    return data[offset:end].decode()


def pem_at(pems, offset):
    matches = [value for start, value in pems if start == offset]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one public key at offset {offset:#x}")
    return matches[0]


def validate_ipv4(value, label):
    try:
        ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as error:
        raise RuntimeError(f"The {label} legacy endpoint did not match the pinned release layout") from error


def write_secret_file(destination, content):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, destination)


def main():
    parser = argparse.ArgumentParser(description="Extract the public client configuration from an official AmneziaVPN release")
    parser.add_argument("output", type=Path, help="Destination for the owner-readable shell environment file")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="amnezia-client-config-") as temporary:
        apk = Path(temporary) / APK_NAME
        urllib.request.urlretrieve(APK_URL, apk)
        if hashlib.sha256(apk.read_bytes()).hexdigest() != APK_SHA256:
            raise RuntimeError("The official APK failed its SHA-256 check")
        with zipfile.ZipFile(apk) as archive:
            data = archive.read(NATIVE_LIBRARY)

    pems = [
        (match.start(), match.group())
        for match in re.finditer(
            r"-----BEGIN PUBLIC KEY-----\n(?:[A-Za-z0-9+/=]+\n)+-----END PUBLIC KEY-----",
            data.decode("latin1"),
        )
    ]
    if len(pems) != 2:
        raise RuntimeError(f"Expected two public client keys, found {len(pems)}")

    prod_s3_offset = data.index(PROD_S3.encode())
    dev_s3 = "https://s3.eu-north-1.amazonaws.com/amnezia-dev/"
    values = {
        "PROD_AGW_PUBLIC_KEY": pem_at(pems, 0x15EB68),
        "PROD_S3_ENDPOINT": PROD_S3,
        "FALLBACK_S3_ENDPOINT": FALLBACK_S3,
        "DEV_AGW_PUBLIC_KEY": pem_at(pems, 0x158E4A),
        "DEV_AGW_ENDPOINT": "http://gw.dev.amzsvc.com:80/",
        "DEV_S3_ENDPOINT": dev_s3,
        "FREE_V2_ENDPOINT": c_string(data, 0x1502FC),
        "PREM_V1_ENDPOINT": c_string(data, 0x15B005),
    }
    validate_ipv4(values["FREE_V2_ENDPOINT"], "Free V2")
    validate_ipv4(values["PREM_V1_ENDPOINT"], "Premium V1")
    if data.index(values["DEV_AGW_ENDPOINT"].encode()) >= prod_s3_offset:
        raise RuntimeError("The development gateway is not in the expected configuration region")
    if b"http://gw.amnezia.org:80/" not in data:
        raise RuntimeError("The production gateway is missing")

    fingerprints = {}
    for name in ("PROD_AGW_PUBLIC_KEY", "DEV_AGW_PUBLIC_KEY"):
        subprocess.run(("openssl", "pkey", "-pubin", "-noout"), input=values[name].encode(), check=True)
        fingerprints[name] = hashlib.sha256(values[name].encode()).hexdigest()
    if fingerprints["PROD_AGW_PUBLIC_KEY"] == fingerprints["DEV_AGW_PUBLIC_KEY"]:
        raise RuntimeError("Production and development public keys must differ")

    lines = []
    for name, value in values.items():
        if name.endswith("PUBLIC_KEY"):
            value = value.replace("\n", "\\n")
        lines.append(f"export {name}={shlex.quote(value)}\n")
    write_secret_file(args.output, "".join(lines))
    print(f"Wrote {len(values)} validated client configuration variables to {args.output}")
    for name in ("PROD_AGW_PUBLIC_KEY", "DEV_AGW_PUBLIC_KEY"):
        print(f"{name} SHA-256: {fingerprints[name]}")


if __name__ == "__main__":
    main()
