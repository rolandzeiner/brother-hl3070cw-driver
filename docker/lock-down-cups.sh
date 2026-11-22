#!/bin/sh
# Run in the image build: takes out what CUPS offers every client that a shared
# print server for this driver must not offer.
#
# - Raw printing. CUPS sends a job in a format it does not know, or one that
#   says it is application/vnd.cups-raw, to the printer unchanged, past the
#   driver: whoever may print could send the printer any command. Without the
#   type and the conversions to it, such a job is refused. Every format a
#   client really prints (PDF, PostScript, images, AirPrint's URF and PWG
#   raster, text) has its own type and still goes through the driver.
# - Banner pages. bannertopdf prints a template from whatever path a banner
#   file names, and the files of waiting jobs are readable to the filters: a
#   banner sent as a document could print another user's waiting document.
#   The web interface's Print Test Page was a banner file; it becomes CUPS's
#   test page PDF.
# - Notifiers. A client may ask for job notifications through rss, mailto or
#   dbus, which would make the server connect to any address it names.
#   Notifications that clients fetch themselves (ippget, as AirPrint does) are
#   part of CUPS and stay.
#
# The build stops if CUPS's files are not what this script expects, so a newer
# CUPS cannot quietly bring any of it back.

set -eu

mime=/usr/share/cups/mime
etc=/usr/share/hl3070cw-print-server-etc-cups # copied into /etc/cups at every start
data=/usr/share/cups/data

fail() {
    echo "lock-down-cups: $*" >&2
    exit 1
}

# Lines that are not comments and name the type, in the files given.
uses() {
    type=$1
    shift
    grep -h -- "$type" "$@" 2>/dev/null | grep -v '^[[:space:]]*#' || true
}

# ---- raw printing ------------------------------------------------------------

grep -q '^application/vnd\.cups-raw[[:space:]]' "$mime/mime.types" || fail "no raw type in $mime/mime.types"
[ -n "$(uses 'application/vnd\.cups-raw' "$mime/mime.convs")" ] || fail "no raw conversion in $mime/mime.convs"

for f in "$mime"/*.types "$etc"/*.types; do
    [ -f "$f" ] || continue
    # a type's rules go on over lines that end in a backslash
    awk 'skip { skip = /\\[[:space:]]*$/; next }
         /^application\/vnd\.cups-raw([[:space:]]|$)/ { skip = /\\[[:space:]]*$/; next }
         { print }' "$f" >"$f.new"
    cat "$f.new" >"$f"
    rm -f "$f.new"
done
for f in "$mime"/*.convs "$etc"/*.convs; do
    [ -f "$f" ] || continue
    sed -i '/application\/vnd\.cups-raw/d' "$f"
done
[ -z "$(uses 'application/vnd\.cups-raw' "$mime"/* "$etc"/*.types "$etc"/*.convs)" ] ||
    fail "raw printing is still configured"

# ---- banner pages ------------------------------------------------------------

[ -n "$(uses '^application/vnd\.cups-pdf-banner[[:space:]].*bannertopdf' "$mime"/*.convs)" ] ||
    fail "no banner conversion in $mime"
sed -i '/^application\/vnd\.cups-pdf-banner[[:space:]]/d' "$mime"/*.convs
[ -z "$(uses '^application/vnd\.cups-pdf-banner[[:space:]]' "$mime"/*.convs "$etc"/*.convs)" ] ||
    fail "banner pages are still converted"
rm -f /usr/share/cups/banners/*

head -n 1 "$data/testprint" | grep -q '^#PDF-BANNER' || fail "unexpected $data/testprint"
head -c 5 "$data/default-testpage.pdf" | grep -q '^%PDF-' || fail "no test page PDF in $data"
cp "$data/default-testpage.pdf" "$data/testprint"
chmod 644 "$data/testprint"

# ---- notifiers ---------------------------------------------------------------

rm -f /usr/lib/cups/notifier/*
[ -z "$(ls -A /usr/lib/cups/notifier 2>/dev/null)" ] || fail "notifiers left in /usr/lib/cups/notifier"

echo "lock-down-cups: no raw printing, banner pages or notifiers"
