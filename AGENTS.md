# AmneziaVPN project instructions

## Public and private work

- `lmdeuser/amnezia-vpn-ubuntu` is the public repository for the team and external users. Keep it free of sensitive information.
- A separate private working repository exists for internal operations. Never make it public, publish its history, or copy its commits without a full content and metadata review.
- Do not publish internal IP addresses, hostnames, local usernames, checkout paths, credential locations, private maintainer identities, or other deployment details.
- Do not commit OBS passwords, session cookies, tokens, private keys, protected client configuration, or secret-bearing logs.
- The approved public maintainer identity is `Dmitriy Volkov <dennshield@duck.com>`. Do not substitute other personal email addresses.
- Public upstream example keys, test fixtures, license contacts, and technical examples are not project credentials. Do not treat them as a reason to remove required vendored sources.

## Builds and releases

- The official `amnezia-vpn/amnezia-client` repository is read-only. Never push to it.
- Compilation, upstream tests, and Debian package creation run only in OBS. Do not build the application locally.
- The self-hosted controller only prepares sources and verifies artifacts. Do not expose its address or local configuration in public files.
- OBS staging sources and logs must remain protected with `sourceaccess=disable`. Direct stable builds and staging publication stay disabled.
- Release only the exact `.deb` that passed installation, service, GUI, configuration, removal, and reinstall checks. Failed checks leave the previous stable package in place.
- Do not run two publishers concurrently. Preserve unrelated cron jobs and OBS projects.

## Changes and verification

- Keep project code and documentation in English. Russian is allowed only in chat.
- Before publishing, inspect both file contents and commit metadata for sensitive data. A clean working tree does not make old history safe.
- Check `.gitignore` before adding generated files. `.state/` and `debian/client-config.env` must remain untracked.
- Keep `OSC_CONFIG`, `CLIENT_CONFIG_FILE`, and controller-specific settings in ignored local state, not in committed scripts.
- Run relevant static checks for changed scripts. OBS must pass all upstream tests, staged runtime checks, and `lintian --fail-on error` before release.
- Document what was actually verified. Do not claim a Premium account session or a self-hosted VPN tunnel was tested without a real user configuration.
- Update this file when these boundaries or the release process change.
