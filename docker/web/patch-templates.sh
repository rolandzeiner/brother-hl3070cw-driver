#!/bin/sh
# Run in the image build: the print server's look for CUPS's web interface.
#
# - cups.css replaces CUPS's stylesheet (all languages share it);
# - in every language's header: the print server's mark instead of the link
#   to OpenPrinting, and the page title names the printer;
# - in every language's footer: credit to OpenPrinting CUPS (with its version)
#   and this driver, instead of the copyright line;
# - a printer's status says whether the printer itself is shared: CUPS's
#   server-wide sharing (Browsing) is off here, because the host's Avahi
#   announces the printer, and would make it read "Not Shared";
# - a start page of its own in English and German; the other languages keep
#   CUPS's, with the same header and footer.
#
# The build stops if CUPS's markup is not what this script expects, so a newer
# CUPS cannot quietly end up half styled.

set -eu

web=$(dirname "$0")
cups=/usr/share/cups
version=$(dpkg-query -W -f '${Version}' cups-daemon | sed 's/-.*//')
footer="<div class=\"cups-footer\"><a href=\"https://openprinting.github.io/cups/\">OpenPrinting CUPS $version</a><a href=\"https://github.com/rolandzeiner/brother-hl3070cw-driver\">brother-hl3070cw-driver</a></div>"

fail() {
    echo "patch-templates: $*" >&2
    exit 1
}

header() {
    grep -q '<li><a href="https://openprinting.github.io/cups/" target="_blank">OpenPrinting CUPS</a></li>' "$1" ||
        fail "unexpected header markup in $1"
    sed -i \
        -e 's|<li><a href="https://openprinting.github.io/cups/" target="_blank">OpenPrinting CUPS</a></li>|<li class="brand"><a href="/">HL-3070CW</a></li>|' \
        -e 's|<title>\(.*\) - CUPS [0-9.]*</title>|<title>\1 – HL-3070CW</title>|' "$1"
}

footer() {
    grep -q '<div class="cups-footer">.*</div>' "$1" || fail "unexpected footer markup in $1"
    sed -i "s|<div class=\"cups-footer\">.*</div>|$footer|" "$1"
}

for f in "$cups"/templates/header.tmpl "$cups"/templates/*/header.tmpl; do
    header "$f"
done
for f in "$cups"/templates/trailer.tmpl "$cups"/templates/*/trailer.tmpl; do
    footer "$f"
done
for f in "$cups"/doc-root/*/index.html; do
    header "$f"
    footer "$f"
done

for f in "$cups"/templates/printer.tmpl "$cups"/templates/class.tmpl \
    "$cups"/templates/*/printer.tmpl "$cups"/templates/*/class.tmpl; do
    sed -i 's/{server_is_sharing_printers=0?\([^:]*\):\({printer_is_shared=0?\1:[^}]*}\)}/\2/' "$f"
done
grep -rq server_is_sharing_printers "$cups/templates" && fail "a sharing status was left unpatched"

install -m 644 "$web/cups.css" "$cups/doc-root/cups.css"
sed "s|@CUPS_VERSION@|$version|" "$web/index.html" > "$cups/doc-root/index.html"
sed "s|@CUPS_VERSION@|$version|" "$web/index.de.html" > "$cups/doc-root/de/index.html"
chmod 644 "$cups/doc-root/index.html" "$cups/doc-root/de/index.html"

grep -rq 'OpenPrinting CUPS</a></li>' "$cups/templates" "$cups/doc-root" --include='*.tmpl' --include='index.html' &&
    fail "a header was left unpatched"
echo "patch-templates: CUPS $version web interface styled"
