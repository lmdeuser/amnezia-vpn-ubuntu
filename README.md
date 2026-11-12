# AmneziaVPN for Ubuntu

Native Debian packages for [AmneziaVPN](https://github.com/amnezia-vpn/amnezia-client) on Ubuntu 26.04 (`amd64`). The upstream repository is read-only. Builds and tests run in the Open Build Service (OBS); a small self-hosted controller prepares sources and checks the resulting packages before publishing them.

## Install

```bash
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL 'https://download.opensuse.org/repositories/home:/dwolfF:/amnezia-vpn/xUbuntu_26.04/Release.key' \
  | sudo tee /etc/apt/keyrings/amnezia-obs.asc >/dev/null
printf '%s\n' 'deb [arch=amd64 signed-by=/etc/apt/keyrings/amnezia-obs.asc] https://download.opensuse.org/repositories/home:/dwolfF:/amnezia-vpn/xUbuntu_26.04/ /' \
  | sudo tee /etc/apt/sources.list.d/amnezia-obs.list >/dev/null
sudo apt update
sudo apt install amneziavpn
```

Future updates arrive through `sudo apt update && sudo apt upgrade`. The OBS key verifies our repository, not the upstream project. Packages and APT metadata are public; protected source archives and build logs are not.

## Package layout

The application and its privileged service are installed in `/opt/AmneziaVPN`. The package also installs a desktop entry, an icon, `/usr/bin/AmneziaVPN`, and the `AmneziaVPN.service` systemd unit.

When a `.run` installation is found, `preinst` backs up user settings and the old unit, moves the legacy nested configuration if needed, and removes the old installer payload before unpacking the package. User configurations and logs are preserved.

The Debian source uses `3.0 (quilt)` with four inputs:

- the upstream `orig` archive;
- `orig-vendor` with pinned native dependencies, Go modules, and Conan recipes;
- `orig-conan` with Conan 2.28.0 sources;
- `debian.tar` with packaging and maintainer scripts.

Conan is installed locally with `--no-index`, and its remotes are disabled. OBS installs system build dependencies from Ubuntu. The OBS `build.script` runs `dpkg-buildpackage -b`, which avoids rebuilding and conflicting with the uploaded source package.

## Premium and self-hosted support

Both modes are included. Eight production, development, and legacy client variables are supplied at build time; their values are not stored in Git. `tools/extract_client_config.py` documents the bootstrap using the official AmneziaVPN 5.1.0.6 APK. It checks the APK checksum and both public keys with OpenSSL and writes an owner-readable environment file without printing its contents.

The OBS package `amneziavpn-secure` uses `sourceaccess=disable`. This keeps source archives and build logs private while allowing public binary downloads. A valid subscription is still required for Premium features.

## Updates

The self-hosted controller checks upstream `dev` once an hour. A new commit produces a versioned source package and updated submodule snapshots. If nothing changed, no upload happens.

After the OBS build, the controller downloads the exact `.deb`, checks it in a disposable Ubuntu 26.04 container, and releases it only after installation, service, GUI, SVG, embedded configuration, removal, and reinstall checks pass. The verified artifact is downloaded once more and compared by SHA-256 before release. Failed checks leave the previous stable package untouched.

Changes to Conan dependencies, recipes, or files that need offline-specific overrides stop the update for manual review. This prevents an upstream dependency change from silently replacing the reviewed offline set.

See [Controller operations](docs/OPERATIONS.md) for the schedule, credentials, recovery procedure, and current verification limits.

## Quality checks

OBS runs all 31 upstream tests and `lintian --fail-on error`. Packaging also checks staged `ldd` output and bundled RPATH values. A failed test, unresolved dependency, or lintian error stops the build.

Source archives, Debian metadata, and `.dsc` checksums must be regenerated together. Do not edit generated archives without refreshing the `.dsc`.

## OBS projects

- Stable: [`home:dwolfF:amnezia-vpn`](https://build.opensuse.org/project/show/home:dwolfF:amnezia-vpn)
- Staging: [`home:dwolfF:amnezia-vpn:staging`](https://build.opensuse.org/project/show/home:dwolfF:amnezia-vpn:staging)
- Package: `amneziavpn-secure` (binary name: `amneziavpn`)
- Target: Ubuntu 26.04 (`resolute`), `amd64`, with `standard`, `universe`, and `universe-update`

Direct stable builds and staging publication are disabled. Compilation and tests run in OBS; source preparation and release verification run on the self-hosted controller.
