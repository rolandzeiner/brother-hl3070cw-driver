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
#   PRINTER_UUID      the printer's UUID; default: derived from name and LISTEN,
#                     so it stays the same across restarts (AirPrint clients
#                     and an Avahi service file identify the printer by it)
#   PRINTER_COLOR     yes, or no while a colour toner is empty: clients then
#                     see a black-and-white printer and every job prints in
#                     Mono (default yes)
#   WEB_FROM          addresses that may use the web interface and its
#                     administration, e.g. a reverse proxy that does the
#                     login; administration from there needs no CUPS login
#                     (default: no web interface)
#   LOG_LEVEL         warn, info or debug (default warn); debug logs each
#                     job's settings, Secure Print PIN included
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
    local colour=${PRINTER_COLOR:-yes} web=${WEB_FROM:-} loglevel=${LOG_LEVEL:-warn}

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
    safe "PRINTER_COLOR" "$colour" '^(yes|no)$'
    safe "WEB_FROM" "$web" '^[A-Za-z0-9.:/ -]*$'
    safe "LOG_LEVEL" "$loglevel" '^(warn|info|debug)$'
    local uuid=${PRINTER_UUID:-$(stable_uuid "hl3070cw-print-server/$name/$listen")}
    safe "PRINTER_UUID" "$uuid" '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

    configure_cups "$listen" "$allow" "$web" "$loglevel"
    if [[ $driver == native ]]; then
        copy_brother_data
    fi

    log "Starting CUPS $(dpkg-query -W -f '${Version}' cups-daemon 2>/dev/null || true), filter $("$FILTER" --version)"
    start_cupsd
    setup_printer "$name" "$info" "$location" "$driver" "$options" "$colour"
    # CUPS gives a new printer a random UUID; set the stable one while CUPS is stopped
    stop_cupsd
    sed -i "s|^UUID .*|UUID urn:uuid:$uuid|" /etc/cups/printers.conf
    start_cupsd
    log "Printer $name ready (UUID $uuid, colour: $colour): $PRINTER_URI, shared on $listen with ${allow}"
    if [[ -n $web ]]; then
        log "Web interface and administration for: $web"
    fi
    # wait returns early when a trapped signal (HUP) arrives: keep waiting
    # until CUPS itself has ended
    local status=0
    while kill -0 "$CUPSD_PID" 2>/dev/null; do
        wait "$CUPSD_PID" || status=$?
    done
    exit "$status"
}

start_cupsd() {
    cupsd -f &
    CUPSD_PID=$!
    local i
    for ((i = 0; i < 60; i++)); do
        lpstat -r >/dev/null 2>&1 && return 0
        sleep 0.5
    done
    die "CUPS did not start"
}

stop_cupsd() {
    kill -TERM "$CUPSD_PID"
    wait "$CUPSD_PID" || true
    CUPSD_PID=''
}

# A name-based UUID (version 5 layout from a SHA-1) for a seed string.
stable_uuid() {
    local h v
    h=$(printf '%s' "$1" | sha1sum | cut -c1-32)
    v=$(printf '%x' $((0x${h:16:1} & 0x3 | 0x8)))
    printf '%s-%s-5%s-%s%s-%s\n' "${h:0:8}" "${h:8:4}" "${h:13:3}" "$v" "${h:17:3}" "${h:20:12}"
}

safe() {
    [[ $2 =~ $3 ]] || die "$1 contains characters that are not allowed: '$2'"
}

configure_cups() {
    local listen=$1 allow=$2 web=$3 loglevel=$4 a
    # /etc/cups is an empty tmpfs: start from the configuration the package installed
    cp -a "$CUPS_TEMPLATE/." /etc/cups/
    {
        printf '%s\n' \
            '# Written by the print server at every start; changes here do not last.' \
            "LogLevel $loglevel" \
            '# no dump of a failed job'"'"'s settings into the log: they hold its Secure Print PIN' \
            'LogDebugHistory 0' \
            'MaxLogSize 0' \
            'AccessLogLevel config' \
            'PageLogFormat ""' \
            'ErrorPolicy retry-job' \
            '# a finished job stays listed for a day: an iPhone asks for its job after' \
            '# printing and, when the job is gone, sends it again, over and over. Its' \
            '# document is deleted; its record keeps a Secure Print PIN, on the tmpfs' \
            '# only, readable by root and never returned to clients' \
            'PreserveJobHistory 86400' \
            'PreserveJobFiles No' \
            '# AirPrint is announced by the host'"'"'s Avahi (docker/README.md), not by CUPS' \
            'Browsing No' \
            'BrowseLocalProtocols none' \
            'DefaultShared Yes' \
            'ServerAlias *' \
            'DefaultAuthType Basic' \
            'Listen /run/cups/cups.sock'
        if [[ $listen == '*:631' ]]; then
            printf 'Port 631\n' # every address, localhost included
        else
            printf 'Listen 127.0.0.1:631\nListen %s\n' "$listen"
        fi
        if [[ -z $web ]]; then
            printf 'WebInterface No\n<Location />\n  Order allow,deny\n  Allow from 127.0.0.1\n'
            for a in $allow; do
                printf '  Allow from %s\n' "$a"
            done
            printf '</Location>\n'
            # administration only from inside the container
            printf '<Location /admin>\n  Order allow,deny\n  Allow from 127.0.0.1\n</Location>\n'
        else
            # Printing and the read-only status pages for the clients and
            # WEB_FROM; administration for WEB_FROM only
            printf 'WebInterface Yes\n<Location />\n  Order allow,deny\n  Allow from 127.0.0.1\n'
            for a in $allow $web; do
                printf '  Allow from %s\n' "$a"
            done
            printf '</Location>\n'
            printf '<Location /admin>\n  Order allow,deny\n  Allow from 127.0.0.1\n'
            for a in $web; do
                printf '  Allow from %s\n' "$a"
            done
            printf '</Location>\n'
        fi
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
            '    Require user @OWNER @SYSTEM'
        trusted_web "$web"
        printf '%s\n' \
            '  </Limit>' \
            '  <Limit CUPS-Add-Modify-Printer Set-Printer-Attributes CUPS-Delete-Printer CUPS-Add-Modify-Class CUPS-Delete-Class CUPS-Set-Default CUPS-Get-Devices Pause-Printer Resume-Printer Enable-Printer Disable-Printer Pause-Printer-After-Current-Job Hold-New-Jobs Release-Held-New-Jobs Deactivate-Printer Activate-Printer Restart-Printer Shutdown-Printer Startup-Printer Promote-Job Schedule-Job-After Cancel-Jobs CUPS-Accept-Jobs CUPS-Reject-Jobs>' \
            '    AuthType Default' \
            '    Require user @SYSTEM'
        trusted_web "$web"
        printf '%s\n' \
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

# Inside a policy Limit: WEB_FROM passes by its address alone (its proxy did
# the login); everyone else still needs what the Limit requires.
trusted_web() {
    local a
    if [[ -z $1 ]]; then
        printf '    Order deny,allow\n'
        return
    fi
    printf '    Satisfy any\n    Order deny,allow\n    Deny from all\n    Allow from 127.0.0.1\n'
    for a in $1; do
        printf '    Allow from %s\n' "$a"
    done
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
    local name=$1 info=$2 location=$3 driver=$4 options=$5 colour=$6 ppd opt
    # The PPD is handed over as a file (the printer is new at every start, so
    # there are no saved settings to keep), adapted first where needed.
    ppd=/tmp/print-server.ppd
    cp "/usr/share/ppd/hl3070cw/hl3070cw-$driver.ppd" "$ppd"
    if [[ $colour == no ]]; then
        # a black-and-white printer for the clients, and Mono whatever they ask for
        sed -i -e 's/^\*ColorDevice: .*/*ColorDevice: False/' -e 's/^\*DefaultBRMonoColor: .*/*DefaultBRMonoColor: Mono/' \
            -e '/^\*APPrinterPreset /s/\*BRMonoColor [A-Za-z]*/*BRMonoColor Mono/' "$ppd"
    fi
    lpadmin -p "$name" -v "$PRINTER_URI" -P "$ppd" -D "$info" -L "$location" -E \
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

# shellcheck disable=SC2317,SC2329  # called by the HUP trap
reload() {
    if [[ -n $CUPSD_PID ]]; then
        kill -HUP "$CUPSD_PID" 2>/dev/null || true
    fi
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
trap reload HUP # docker kill -s HUP print-server: CUPS rereads its configuration

main "$@"
