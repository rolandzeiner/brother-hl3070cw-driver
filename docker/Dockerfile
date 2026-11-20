# Print server for the Brother HL-3070CW: CUPS with this project's native
# driver, sharing the printer over IPP (AirPrint, IPP Everywhere). See
# docker/README.md.
#
# The image holds no file of Brother's: its Linux driver package is mounted at
# /brother and unpacked at every start.

FROM debian:trixie-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libcups2-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY Makefile ./
COPY src ./src
RUN make && build/rastertohl3070cw --version

FROM debian:trixie-slim
# CUPS (scheduler, PPD lister, socket backend) and the filters that turn PDF,
# text and images into page rasters; bsdtar unpacks Brother's .rpm (dpkg-deb,
# for a .deb, is part of the base). No recommends: no Avahi, no other drivers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends cups cups-client cups-filters ghostscript poppler-utils \
      libarchive-tools \
 && rm -rf /var/lib/apt/lists/* \
 # CUPS's configuration as installed: the entrypoint restores it into the
 # writable /etc/cups at every start (the container runs read-only)
 && cp -a /etc/cups /usr/share/hl3070cw-print-server-etc-cups
COPY --from=build /src/build/rastertohl3070cw /usr/lib/cups/filter/rastertohl3070cw
COPY ppd/linux/hl3070cw-native.ppd ppd/hl3070cw-postscript.ppd /usr/share/ppd/hl3070cw/
COPY docker/entrypoint.sh /usr/local/bin/print-server
RUN chmod 755 /usr/lib/cups/filter/rastertohl3070cw /usr/local/bin/print-server \
 && chmod 644 /usr/share/ppd/hl3070cw/*.ppd

EXPOSE 631
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD lpstat -p "${PRINTER_NAME:-HL3070CW}" >/dev/null || exit 1
ENTRYPOINT ["/usr/local/bin/print-server"]
