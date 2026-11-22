# Print server for the Brother HL-3070CW: CUPS with this project's native
# driver, sharing the printer over IPP (AirPrint, IPP Everywhere). See
# docker/README.md.
#
# The image holds no file of Brother's: its Linux driver package is mounted at
# /brother and unpacked at every start.
#
# Debian testing (forky) by default: it carries the current CUPS 2.4 release
# with its security fixes, while stable (trixie) stays on 2.4.10 with a
# backlog of open CUPS advisories. --build-arg DEBIAN=trixie-slim builds on
# stable.
ARG DEBIAN=forky-slim

FROM debian:${DEBIAN} AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libcups2-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY Makefile ./
COPY src ./src
RUN make && build/rastertohl3070cw --version
# the gate in front of CUPS's web programs (docker/web-gate.c)
COPY docker/web-gate.c ./
RUN cc -O2 -std=c11 -D_XOPEN_SOURCE=700 -Wall -Wextra -Werror -fstack-protector-strong -D_FORTIFY_SOURCE=3 \
      -fPIE -pie -Wl,-z,relro,-z,now -o build/web-gate web-gate.c

FROM debian:${DEBIAN}
# CUPS (scheduler, PPD lister, socket backend) and the filters that turn PDF,
# text and images into page rasters; bsdtar unpacks Brother's .rpm (dpkg-deb,
# for a .deb, is part of the base). No recommends: no Avahi, no other drivers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends cups cups-client cups-filters ghostscript poppler-utils \
      libarchive-tools \
 && rm -rf /var/lib/apt/lists/* \
 # no search for network printers (needs Avahi, which the container has not got), and
 # no driver programs, which cups-driverd runs for a PPD name any client may ask for
 && rm -f /usr/lib/cups/driver/* \
 # CUPS's configuration as installed: the entrypoint restores it into the
 # writable /etc/cups at every start (the container runs read-only)
 && cp -a /etc/cups /usr/share/hl3070cw-print-server-etc-cups
COPY --from=build /src/build/rastertohl3070cw /usr/lib/cups/filter/rastertohl3070cw
COPY ppd/linux/hl3070cw-native.ppd ppd/hl3070cw-postscript.ppd /usr/share/ppd/hl3070cw/
# no raw printing, banner pages or notifiers: see the script
RUN --mount=type=bind,source=docker/lock-down-cups.sh,target=/tmp/lock-down-cups.sh sh /tmp/lock-down-cups.sh
COPY docker/entrypoint.sh /usr/local/bin/print-server
RUN chmod 755 /usr/lib/cups/filter/rastertohl3070cw /usr/local/bin/print-server \
 && chmod 644 /usr/share/ppd/hl3070cw/*.ppd
# the web interface's look: stylesheet, start page, header and footer
RUN --mount=type=bind,source=docker/web,target=/tmp/web sh /tmp/web/patch-templates.sh
# every web program gets the gate in front of it
COPY --from=build /src/build/web-gate /usr/local/sbin/web-gate
RUN set -eu; cd /usr/lib/cups/cgi-bin; install -d -m 755 ../cgi-real; n=0; \
    for f in *.cgi; do mv "$f" "../cgi-real/$f"; install -m 755 /usr/local/sbin/web-gate "$f"; n=$((n + 1)); done; \
    [ "$n" -ge 5 ]

EXPOSE 631
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD lpstat -p "${PRINTER_NAME:-HL3070CW}" >/dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/print-server"]
