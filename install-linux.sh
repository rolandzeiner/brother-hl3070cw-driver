#!/usr/bin/env bash
# Install the Brother HL-3070CW driver on Linux (Debian, Raspberry Pi OS,
# Ubuntu and others with CUPS 2.x): the native filter (Brother quality, needs
# Brother's data files) and the PostScript PPD (works without them).
#
#   sudo ./install-linux.sh --brother-package hl3070cwlpr-1.1.2-1.i386.rpm
#                                  install, taking Brother's data from its Linux
#                                  driver package (.rpm or .deb, any processor:
#                                  the package is only unpacked, never run)
#   sudo ./install-linux.sh        install; Brother's data from an installed
#                                  Brother driver or an earlier installation
#   ... --queue NAME --uri URI     also create printer NAME (socket://IP:9100)
#   ... --queue NAME --postscript  use the PostScript PPD for that printer
#   sudo ./install-linux.sh --uninstall   remove the driver (printers stay)
#   ... --dry-run                  show what would be done
#
# Printers that already use one of this driver's PPDs get the new PPD and keep
# their settings. Build the filter first with: make
# Exit status: 0 = done, 1 = finished with problems, 2 = could not start.

set -Eeuo pipefail
shopt -s inherit_errexit

readonly FILTER_DIR=/usr/lib/cups/filter
readonly PPD_DIR=/usr/share/ppd/hl3070cw
readonly SHARE_DIR=/usr/share/hl3070cw-native
readonly DATA_DIR=$SHARE_DIR/data
readonly UNPACK_DIR=$SHARE_DIR/unpack # where the filter looks for a package (--unpacked)
readonly QUEUE_PPDS=/etc/cups/ppd
readonly BROTHER_INSTALLED=/opt/brother/Printers/hl3070cw
readonly NATIVE_NICK="Brother HL-3070CW, native driver (open source)"
readonly PS_NICK="Brother HL-3070CW, PostScript (BR-Script 3)"

UNPACKING=0 # set in copy_brother_data: on_exit removes UNPACK_DIR

main() {
    DRY_RUN=0
    UNINSTALL=0
    QUEUE=''
    URI=''
    USE_PS=0
    PACKAGE=''
    PROBLEMS=0
    parse_args "$@"

    [[ $(uname -s) == Linux ]] || die "This installer is for Linux; on a Mac use install.sh or the .pkg."
    if ((EUID != 0)) && ((!DRY_RUN)); then
        die "Run it as root: sudo $0 $*"
    fi
    command -v lpadmin >/dev/null || die "CUPS is not installed (Debian, Raspberry Pi OS: sudo apt install cups)"

    if ((UNINSTALL)); then
        uninstall
        exit 0
    fi

    local src_dir bin=''
    src_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || die "cannot find the installer's folder"
    for candidate in "$src_dir/build/rastertohl3070cw" "$src_dir/rastertohl3070cw"; do
        if [[ -x $candidate ]]; then
            bin=$candidate
            break
        fi
    done
    [[ -n $bin ]] || die "rastertohl3070cw not found next to the installer; build it with: make"
    local native_ppd="$src_dir/ppd/linux/hl3070cw-native.ppd" ps_ppd="$src_dir/ppd/hl3070cw-postscript.ppd"
    [[ -f $native_ppd && -f $ps_ppd ]] || die "PPD files missing in $src_dir/ppd"
    # What gets installed as root, and run as root, must not be changeable by others.
    local f
    for f in "$bin" "$(dirname -- "$bin")" "$native_ppd" "$ps_ppd" "$src_dir/ppd" "$src_dir/ppd/linux"; do
        check_source "$f"
    done
    local version
    if ! version=$("$bin" --version 2>&1); then
        die "the driver does not run on this computer ($(uname -m); it needs CUPS, and the package for this processor): $version"
    fi
    log "Filter: $version"

    log "Installing the filter into $FILTER_DIR"
    run install -d -m 755 "$FILTER_DIR" "$PPD_DIR" "$SHARE_DIR"
    run install -m 755 -o root -g root "$bin" "$FILTER_DIR/rastertohl3070cw"

    local have_data=0
    if copy_brother_data; then
        have_data=1
    fi

    log "Installing the PPD files into $PPD_DIR"
    run install -m 644 -o root -g root "$ps_ppd" "$PPD_DIR/hl3070cw-postscript.ppd"
    if ((have_data)); then
        run install -m 644 -o root -g root "$native_ppd" "$PPD_DIR/hl3070cw-native.ppd"
    else
        run rm -f -- "$PPD_DIR/hl3070cw-native.ppd"
    fi

    refresh_queues
    if [[ -n $QUEUE ]]; then
        setup_queue "$have_data"
    fi

    if ((PROBLEMS)); then
        printf '\nFinished with problems (see warnings above).\n'
        exit 1
    fi
    printf '\nDone.'
    if [[ -z $QUEUE ]]; then
        printf ' Add the printer in your system'"'"'s printer settings or with lpadmin, and choose\n'
        printf '"Brother HL-3070CW, native driver (open source)" as the driver.\n'
    else
        printf '\n'
    fi
}

# Brother's halftone patterns and colour tables into DATA_DIR. Status 0: the
# native driver has its data.
copy_brother_data() {
    local filter="$FILTER_DIR/rastertohl3070cw"
    if [[ -n $PACKAGE ]]; then
        log "Unpacking Brother's driver package $PACKAGE (its programs are not run)"
        if ((DRY_RUN)); then
            run "$filter" --extract-brother-data --unpacked
            return 0
        fi
        # The package is not trusted. It is unpacked inside a folder only root
        # can enter, and without its owners and modes: its entry for "." could
        # otherwise open that folder to everybody.
        local dest=$UNPACK_DIR/package
        UNPACKING=1
        rm -rf -- "${UNPACK_DIR:?}" || die "cannot remove $UNPACK_DIR"
        mkdir -m 700 -- "$UNPACK_DIR" || die "cannot create $UNPACK_DIR"
        mkdir -m 755 -- "$dest" || die "cannot create $dest"
        case "$PACKAGE" in
        *.rpm)
            command -v bsdtar >/dev/null || die "unpacking an .rpm needs bsdtar (Debian, Raspberry Pi OS: sudo apt install libarchive-tools)"
            (umask 022 && bsdtar --no-same-owner --no-same-permissions -xf "$PACKAGE" -C "$dest") ||
                die "cannot unpack $PACKAGE"
            ;;
        *.deb)
            command -v dpkg-deb >/dev/null || die "unpacking a .deb needs dpkg-deb; use Brother's .rpm instead"
            (umask 022 && dpkg-deb --fsys-tarfile "$PACKAGE" |
                tar --no-same-owner --no-same-permissions -xf - -C "$dest") || die "cannot unpack $PACKAGE"
            ;;
        *) die "$PACKAGE is neither an .rpm nor a .deb" ;;
        esac
        [[ -d $dest$BROTHER_INSTALLED ]] || die "$PACKAGE is not Brother's HL-3070CW driver (hl3070cwlpr)"
        if "$filter" --extract-brother-data --unpacked; then
            return 0
        fi
        warn "Copying Brother's data failed; the native driver will not work."
        return 1
    fi
    if [[ -d $BROTHER_INSTALLED ]]; then
        log "Copying Brother's data from its installed driver"
        if run "$filter" --extract-brother-data; then
            return 0
        fi
        warn "Copying Brother's data failed; the native driver will not work."
        return 1
    fi
    if [[ -f $DATA_DIR/table-600-grayon-normal.bin ]]; then
        log "Brother's data from an earlier installation is still in $DATA_DIR"
        return 0
    fi
    warn "Brother's data files are needed for the native driver. Download Brother's Linux driver for the"
    warn "HL-3070CW (the LPR driver, hl3070cwlpr, .rpm or .deb) from support.brother.com and run:"
    warn "  sudo $0 --brother-package path/to/hl3070cwlpr-1.1.2-1.i386.rpm"
    warn "Until then only the PostScript PPD is installed."
    return 1
}

# The model name CUPS lists one of this driver's PPDs under: distributions
# name the PPD folders differently (Debian: lsb/usr/hl3070cw/...).
ppd_model() {
    local file=$1 name
    name=$(lpinfo -m 2>/dev/null | awk -v f="/hl3070cw/$file" 'index($1, f) == length($1) - length(f) + 1 { print $1; exit }') || true
    [[ -n $name ]] || name="lsb/usr/hl3070cw/$file"
    printf '%s\n' "$name"
}

# A printer keeps its own copy of the PPD from the day it was added. Give every
# printer that uses one of this driver's PPDs the new one, named as a model so
# that CUPS keeps the printer's saved defaults.
refresh_queues() {
    local ppd nick model queue
    for ppd in "$QUEUE_PPDS"/*.ppd; do
        [[ -f $ppd ]] || continue
        nick=$(sed -n 's/^\*NickName: "\(.*\)"$/\1/p' "$ppd") || continue
        case "$nick" in
        "$NATIVE_NICK") model=hl3070cw-native.ppd ;;
        "$PS_NICK") model=hl3070cw-postscript.ppd ;;
        *) continue ;;
        esac
        [[ -f $PPD_DIR/$model ]] || continue
        queue=${ppd##*/}
        queue=${queue%.ppd}
        log "Printer $queue: new $model"
        if ! run lpadmin -p "$queue" -m "$(ppd_model "$model")"; then
            warn "lpadmin failed for printer $queue"
        fi
    done
}

setup_queue() {
    local have_data=$1 model
    if ((USE_PS)); then
        model=hl3070cw-postscript.ppd
    elif ((have_data)); then
        model=hl3070cw-native.ppd
    else
        warn "Printer $QUEUE: native driver not available, using the PostScript PPD"
        model=hl3070cw-postscript.ppd
    fi
    local args
    args=(-p "$QUEUE" -m "$(ppd_model "$model")")
    if [[ -n $URI ]]; then
        # a new printer: enabled, and not shared on the network
        args+=(-v "$URI" -E -o printer-is-shared=false)
    elif ! lpstat -p "$QUEUE" >/dev/null 2>&1; then
        warn "Printer $QUEUE does not exist; give --uri to create it"
        return 0
    fi
    log "Printer $QUEUE: $model"
    if ! run lpadmin "${args[@]}"; then
        warn "lpadmin failed for printer $QUEUE"
    fi
}

uninstall() {
    log "Removing the driver"
    run rm -f -- "$FILTER_DIR/rastertohl3070cw"
    # The folders are fixed constants; the guards only protect against editing mistakes.
    local d
    for d in "${PPD_DIR:?}" "${SHARE_DIR:?}"; do
        case "$d" in
        /usr/share/?*/*|/usr/share/hl3070cw-native) ;;
        *) die "refusing to remove unexpected path $d" ;;
        esac
        if [[ -d $d ]]; then
            run rm -rf -- "$d"
        fi
    done
    local queues
    queues=$(lpstat -v 2>/dev/null | grep -i -e hl3070cw -e hl-3070 || true)
    if [[ -n $queues ]]; then
        printf 'Printers are left as they are; remove them or give them another driver:\n%s\n' "$queues"
    fi
}

# Refuse a source file or folder that belongs to someone other than the caller
# (or root) or that group or others may write to.
check_source() {
    local path=$1 owner mode caller
    owner=$(stat -c %u -- "$path") || die "cannot check $path"
    mode=$(stat -c %a -- "$path") || die "cannot check $path"
    caller=${SUDO_UID:-$EUID}
    if [[ $owner != "$caller" && $owner != 0 ]]; then
        die "$path belongs to another user; refusing to install it as root"
    fi
    if ((8#$mode & 8#022)); then
        die "$path is writable by group or others; refusing to install it as root"
    fi
}

usage() {
    cat <<EOF
Usage: sudo ${0##*/} [--brother-package FILE] [--queue NAME [--uri URI] [--postscript]] [--dry-run]
       sudo ${0##*/} --uninstall [--dry-run]
EOF
}

parse_args() {
    while (($# > 0)); do
        case "$1" in
        -n | --dry-run) DRY_RUN=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --postscript) USE_PS=1 ;;
        --brother-package)
            (($# > 1)) || die "--brother-package needs a file"
            PACKAGE=$2
            [[ -f $PACKAGE ]] || die "$PACKAGE does not exist"
            PACKAGE=$(realpath -- "$PACKAGE")
            shift
            ;;
        --queue)
            (($# > 1)) || die "--queue needs a name"
            QUEUE=$2
            shift
            ;;
        --uri)
            (($# > 1)) || die "--uri needs a value"
            URI=$2
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            die "Unknown argument: $1"
            ;;
        esac
        shift
    done
    if [[ -n $URI && -z $QUEUE ]]; then die "--uri needs --queue"; fi
    if ((USE_PS)) && [[ -z $QUEUE ]]; then die "--postscript needs --queue"; fi
}

log() { printf '[INFO] %s\n' "$*"; }
warn() {
    printf '[WARN] %s\n' "$*" >&2
    PROBLEMS=1
}
die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 2
}

# Run a state-changing command, or only print it under --dry-run.
run() {
    if ((DRY_RUN)); then
        printf 'DRY-RUN:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

# shellcheck disable=SC2317,SC2329  # called by the EXIT trap (older shellcheck: SC2317)
on_exit() {
    local status=$?
    set +e
    if ((UNPACKING)); then
        rm -rf -- "${UNPACK_DIR:?}"
    fi
    exit "$status"
}
# shellcheck disable=SC2317,SC2329  # called by the ERR trap (older shellcheck: SC2317)
on_err() {
    printf '[ERROR] line %s: "%s" failed\n' "$1" "$2" >&2
}
trap on_exit EXIT
trap 'exit 130' INT TERM HUP
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

main "$@"
exit
