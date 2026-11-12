# Controller operations

This page is for the person maintaining the AmneziaVPN OBS pipeline. It does not contain host addresses, local usernames, credential paths, or client configuration values.

## Components

- Controller: a self-hosted Linux machine with Docker and `osc`.
- Checkout: `/path/to/amnezia-vpn-obs` on that machine.
- Staging: `home:dwolfF:amnezia-vpn:staging`.
- Stable: `home:dwolfF:amnezia-vpn`.
- OBS package: `amneziavpn-secure`.
- Binary package: `amneziavpn` for Ubuntu 26.04 `amd64`.
- Packaging source: `lmdeuser/amnezia-vpn-ubuntu`, branch `dev`.

The official `amnezia-vpn/amnezia-client` repository is read-only. Nothing is pushed to it.

## What a release does

The controller checks `refs/heads/dev`. When the commit changes, it creates a new source package and uploads it to protected OBS staging. OBS builds the package in a clean Ubuntu 26.04 worker, runs all 31 upstream tests, checks staged runtime dependencies, and runs `lintian --fail-on error`.

The controller then downloads the exact `.deb` tied to that source revision and checks it in a disposable Ubuntu container:

- installation and `apt-get check`;
- privileged-service startup;
- unresolved shared libraries and RPATH;
- a visible GUI window and SVG plugins;
- embedded Premium and self-hosted configuration;
- removal and reinstallation.

Finally, it downloads the server artifact again and compares SHA-256 with the verified file. Only a match is released to stable. Any failure leaves the previous stable package in place. No upload happens when upstream is unchanged.

Staging publishing and direct stable builds are disabled.

## Schedule and locking

The controller has its own cron block. The checkout path is filled in by `tools/install_cron.py`:

```text
# BEGIN AMNEZIA OBS
37 * * * * /usr/bin/timeout 100m /path/to/amnezia-vpn-obs/tools/cron-cycle.sh
# END AMNEZIA OBS
```

Other projects' cron jobs must be preserved. Cron and manual runs share locks, so only one publisher can run at a time.

Useful commands on the controller:

```bash
crontab -l
cat /path/to/amnezia-vpn-obs/.state/controller.log
/path/to/amnezia-vpn-obs/tools/run-controller.sh
python3 /path/to/amnezia-vpn-obs/tools/install_cron.py
```

Run a manual cycle only when no other cycle is active. Do not publish `.state`, logs, credentials, session cookies, or the protected client environment.

## Credentials and client configuration

`tools/run-controller.sh` reads `OSC_CONFIG` and `XDG_CONFIG_HOME` from the environment or from an ignored `.state/controller.env` file. The existing `osc` configuration is mounted read-only and is never copied into this repository.

The protected client environment lives in `.state/client-config.env` with restricted permissions. It is excluded from Git and included only in protected OBS source archives. Public users can download binaries and APT metadata, but unauthenticated source requests receive HTTP `403`.

`tools/extract_client_config.py` is the bootstrap for the official AmneziaVPN 5.1.0.6 client configuration. It verifies the APK checksum, uses offsets established by disassembly, and validates both public keys with OpenSSL. Production and development keys must have different fingerprints. Review this procedure when upstream changes its configuration layout.

## Update guards

Routine source and pinned submodule updates are automatic. An update stops before upload when upstream changes:

- a Conan dependency version or adds an unreviewed dependency;
- Conan recipes;
- the Conan manifest beyond the supported system-library overrides;
- the libssh target override or remote-repository override in CMake;
- the pinned Conan source or its checksum.

These changes need a manual vendor review. The controller does not fix itself or bypass failed checks.

## Versioning

Automatic versions have this form:

```text
<upstream-version>+git<UTC-YYYYMMDD>.<short-commit>-0ubuntu1~obs1
```

Each upstream commit therefore has unique source archive names and a unique Debian version. Packaging-only fixes need a higher packaging revision instead. Always regenerate source archives, Debian metadata, and `.dsc` checksums together.

## Recovery

Before editing the controller, disable only the AmneziaVPN cron block and wait for the active process to finish. Do not edit a running publisher or touch other projects' schedules.

Inspect staging with an authenticated `osc` client:

```bash
osc results home:dwolfF:amnezia-vpn:staging amneziavpn-secure
osc remotebuildlog home:dwolfF:amnezia-vpn/amneziavpn-secure xUbuntu_26.04 x86_64
```

Staging sources and logs are protected. Do not paste configuration values or credential-bearing log fragments into tickets or chat.

After a failure, the previous stable package remains available. Fix the cause, run one complete cycle, and confirm a verified release before restoring cron. `obs/upstream.json` and the protected OBS `pipeline-state` package record non-secret revisions. An OBS `succeeded` status alone does not prove that release verification passed.

## What has been verified

- all 31 upstream tests and Lintian;
- staged `ldd` and bundled RPATH checks;
- installation and removal on a real Ubuntu 26.04 VM;
- privileged service and visible GUI startup without `LD_LIBRARY_PATH`;
- SVG loading and production API HTTP `200`;
- migration from the official `.run` installer with preserved settings and legacy-unit backup;
- removal of legacy and packaged payloads while preserving user configuration;
- APT installation and upgrade from the public stable repository.

A valid Premium subscription and a real self-hosted VPN configuration were not available. API availability and embedded configuration are verified; an actual Premium account session and a self-hosted VPN tunnel are not claimed as verified.
