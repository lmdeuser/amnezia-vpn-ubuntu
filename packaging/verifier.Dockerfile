FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive TMPDIR=/var/tmp/amnezia-vpn
RUN mkdir -p "$TMPDIR" && chmod 1777 "$TMPDIR" && apt-get update && apt-get install -y --no-install-recommends \
 ca-certificates python3 procps dpkg-dev apt-utils dbus-x11 xvfb xauth x11-utils \
 desktop-file-utils patchelf libc6 iptables iproute2 libxkbcommon-x11-0 libsecret-1-0 \
 libxcb-icccm4 libxcb-image0 libxcb-render-util0 libxcb-keysyms1 libxcb-shape0 \
 libxcb-xfixes0 libxcb-sync1 libxcb-xinerama0 libxcb-xkb1 \
 && useradd --create-home tester && rm -rf /var/lib/apt/lists/*
COPY tools/container-check.sh /usr/local/bin/container-check
COPY tools/window_check.py /usr/local/bin/window-check.py
ENTRYPOINT ["/usr/local/bin/container-check"]
