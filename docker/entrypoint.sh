#!/usr/bin/env bash
# Print server entrypoint: CUPS with the native HL-3070CW driver, configured
# from the environment at every start (see docker/README.md):
#
#   PRINTER_URI       the printer, e.g. socket://192.0.2.10:9100   (required)
#   PRINTER_NAME      queue name                       (default HL3070CW)
#   PRINTER_INFO      name the clients show            (default Brother HL-3070CW)
#   PRINTER_LOCATION  where it stands                  (default empty)
#   PRINTER_DRIVER    native or postscript             (default native)
#   PRINTER_OPTIONS   default options, e.g. "BRMonoColor=Mono"
#   LISTEN            address:port to listen on, e.g. 10.13.10.3:631 (default *:631)
#   ALLOW_FROM        who may print: addresses or networks (default @LOCAL)
#
# Brother's Linux driver package for the HL-3070CW (hl3070cwlpr, .rpm or .deb)
# is expected in /brother; its files are only unpacked, never run.

set -Eeuo pipefail
shopt -s inherit_errexit

readonly FILTER=/usr/lib/cups/filter/rastertohl3070cw
readonly DATA_DIR=/usr/share/hl3070cw-native/data
readonly CUPS_TEMPLATE=/usr/share/hl3070cw-print-server-etc-cups

CUPSD_PID=''

main() {
    : "${PRINTER_URI:?set PRINTER_URI to the printer, e.g. socket://192.0.2.10:9100}"
    local name=${PRINTER_NAME:-HL3070CW} info=${PRINTER_INFO:-Brother HL-3070CW}
    local location=${PRINTER_LOCATION:-} driver=${PRINTER_DRIVER:-native}
    local listen=${LISTEN:-*:631} allow=${ALLOW_FROM:-@LOCAL} options=${PRINTER_OPTIONS:-}

    # Values that end up in cupsd.conf or on lpadmin's command line: plain
    # characters only, so no setting can add a directive of its own.
    safe "PRINTER_NAME" "$name" '^[A-Za-z0-9_-]{1,64}$'
    safe "PRINTER_URI" "$PRINTER_URI" '^(socket|ipp|lpd)://[A-Za-z0-9.:_/-]+$'
    safe "PRINTER_DRIVER" "$driver" '^(native|postscript)$'
    safe "LISTEN" "$listen" '^[]A-Za-z0-9.:*[]+$'  # ] first: inside brackets it is literal there
    safe "ALLOW_FROM" "$allow" '^[A-Za-z0-9.:/@ *-]+$'
    safe "PRINTER_OPTIONS" "$options" '^[A-Za-z0-9=_. -]*$'
    safe "PRINTER_INFO" "$info" '^[^"\\[:cntrl:]]{0,127}$'
    safe "PRINTER_LOCATION" "$location" '^[^"\\[:cntrl:]]{0,127}$'

    configure_cups "$listen" "$allow"
    if [[ $driver == native ]]; then
        copy_brother_data
    fi

    log "Starting CUPS $(cupsd -v 2>&1 | head -n 1 || true), filter $("$FILTER" --version)"
    cupsd -f &
    CUPSD_PID=$!
    local i
    for ((i = 0; i < 60; i++)); do
        lpstat -r >/dev/null 2>&1 && break
        sleep 0.5
    done
    lpstat -r >/dev/null 2>&1 || die "CUPS did not start"

    setup_printer "$name" "$info" "$location" "$driver" "$options"
    log "Printer $name ready: $PRINTER_URI, shared on $listen with ${allow}"
    wait "$CUPSD_PID"
}

safe() {
    [[ $2 =~ $3 ]] || die "$1 contains characters that are not allowed: '$2'"
}

configure_cups() {
    local listen=$1 allow=$2 a
    # /etc/cups is an empty tmpfs: start from the configuration the package installed
    cp -a "$CUPS_TEMPLATE/." /etc/cups/
    {
        printf '%s\n' \
            '# Written by the print server at every start; changes here do not last.' \
            'LogLevel warn' \
            '# no dump of a failed job'"'"'s settings into the log: they hold its Secure Print PIN' \
            'LogDebugHistory 0' \
            'MaxLogSize 0' \
            'AccessLogLevel config' \
            'PageLogFormat ""' \
            'ErrorPolicy retry-job' \
            '# nothing of a finished job is kept: CUPS stores the PIN with the job' \
            'PreserveJobHistory No' \
            'PreserveJobFiles No' \
            '# AirPrint is announced by the host'"'"'s Avahi (docker/README.md), not by CUPS' \
            'Browsing No' \
            'BrowseLocalProtocols none' \
            'WebInterface No' \
            'DefaultShared Yes' \
            'ServerAlias *' \
            'DefaultAuthType Basic' \
            'Listen /run/cups/cups.sock' \
            'Listen 127.0.0.1:631'
        if [[ $listen == '*:631' ]]; then
            printf 'Port 631\n'
        else
            printf 'Listen %s\n' "$listen"
        fi
        printf '<Location />\n  Order allow,deny\n  Allow from 127.0.0.1\n'
        for a in $allow; do
            printf '  Allow from %s\n' "$a"
        done
        printf '</Location>\n'
        # administration only from inside the container
        printf '<Location /admin>\n  Order allow,deny\n  Allow from 127.0.0.1\n</Location>\n'
        printf '<Location /admin/conf>\n  AuthType Default\n  Require user @SYSTEM\n  Order allow,deny\n  Allow from 127.0.0.1\n</Location>\n'
        printf '%s\n' \
            '<Policy default>' \
            '  JobPrivateAccess default' \
            '  JobPrivateValues default' \
            '  SubscriptionPrivateAccess default' \
            '  SubscriptionPrivateValues default' \
            '  <Limit Create-Job Print-Job Print-URI Validate-Job>' \
            '    Order deny,allow' \
            '  </Limit>' \
            '  <Limit Send-Document Send-URI Hold-Job Release-Job Restart-Job Purge-Jobs Set-Job-Attributes Create-Job-Subscription Renew-Subscription Cancel-Subscription Get-Notifications Reprocess-Job Cancel-Current-Job Suspend-Current-Job Resume-Job Cancel-My-Jobs Close-Job CUPS-Move-Job CUPS-Get-Document>' \
            '    Require user @OWNER @SYSTEM' \
            '    Order deny,allow' \
            '  </Limit>' \
            '  <Limit Cancel-Job CUPS-Authenticate-Job>' \
            '    Require user @OWNER @SYSTEM' \
            '    Order deny,allow' \
            '  </Limit>' \
            '  <Limit CUPS-Add-Modify-Printer CUPS-Delete-Printer CUPS-Add-Modify-Class CUPS-Delete-Class CUPS-Set-Default CUPS-Get-Devices Pause-Printer Resume-Printer Enable-Printer Disable-Printer Pause-Printer-After-Current-Job Hold-New-Jobs Release-Held-New-Jobs Deactivate-Printer Activate-Printer Restart-Printer Shutdown-Printer Startup-Printer Promote-Job Schedule-Job-After Cancel-Jobs CUPS-Accept-Jobs CUPS-Reject-Jobs>' \
            '    AuthType Default' \
            '    Require user @SYSTEM' \
            '    Order deny,allow' \
            '  </Limit>' \
            '  <Limit All>' \
            '    Order deny,allow' \
            '  </Limit>' \
            '</Policy>'
    } >/etc/cups/cupsd.conf
    # logs to the container's output; no access log beyond configuration changes
    sed -i -e 's|^#\{0,1\}ErrorLog .*|ErrorLog stderr|' -e 's|^#\{0,1\}AccessLog .*|AccessLog stderr|' \
        -e 's|^#\{0,1\}PageLog .*|PageLog stderr|' /etc/cups/cups-files.conf
    grep -q '^ErrorLog stderr' /etc/cups/cups-files.conf || printf 'ErrorLog stderr\nAccessLog stderr\nPageLog stderr\n' >>/etc/cups/cups-files.conf
}

copy_brother_data() {
    local pkg tmp
    pkg=$(find /brother -maxdepth 1 -type f \( -name 'hl3070cwlpr*.rpm' -o -name 'hl3070cwlpr*.deb' \) 2>/dev/null | head -n 1)
    [[ -n $pkg ]] || die "Brother's Linux driver package (hl3070cwlpr .rpm or .deb) is not in /brother; mount the folder that holds it at /brother, or set PRINTER_DRIVER=postscript"
    tmp=$(mktemp -d)
    case "$pkg" in
    *.rpm) bsdtar -xf "$pkg" -C "$tmp" ;;
    *.deb) dpkg-deb -x "$pkg" "$tmp" ;;
    esac
    if ! "$FILTER" --extract-brother-data "$DATA_DIR" "$tmp" >/dev/null; then
        rm -rf -- "${tmp:?}"
        die "copying Brother's data from ${pkg##*/} failed"
    fi
    rm -rf -- "${tmp:?}"
    log "Brother's data taken from ${pkg##*/}"
}

setup_printer() {
    local name=$1 info=$2 location=$3 driver=$4 options=$5 file model opt
    file=hl3070cw-$driver.ppd
    model=$(lpinfo -m 2>/dev/null | awk -v f="/hl3070cw/$file" 'index($1, f) == length($1) - length(f) + 1 { print $1; exit }') || true
    [[ -n $model ]] || die "CUPS does not list $file"
    lpadmin -p "$name" -v "$PRINTER_URI" -m "$model" -D "$info" -L "$location" -E \
        -o printer-is-shared=true -o printer-error-policy=retry-job 2>&1 | grep -v 'deprecated' || true
    lpstat -p "$name" >/dev/null 2>&1 || die "lpadmin could not create printer $name"
    for opt in $options; do
        lpadmin -p "$name" -o "$opt" 2>&1 | grep -v 'deprecated' || true
    done
    lpadmin -d "$name"
}

log() { printf '[print-server] %s\n' "$*"; }
die() {
    printf '[print-server] ERROR: %s\n' "$*" >&2
    exit 1
}

# shellcheck disable=SC2317,SC2329  # called by the TERM trap
stop() {
    if [[ -n $CUPSD_PID ]]; then
        kill -TERM "$CUPSD_PID" 2>/dev/null || true
        wait "$CUPSD_PID" 2>/dev/null || true
    fi
    exit 0
}
trap stop TERM INT

main "$@"
