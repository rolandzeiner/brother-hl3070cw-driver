#!/bin/bash
# Install the Brother HL-3070CW driver on macOS: the native filter (Brother
# quality, needs Brother's data files) and the PostScript PPD (works without them).
#
#   ./install.sh                        install, ask for the admin password via sudo
#   ./install.sh --queue NAME           also switch printer queue NAME to the native driver
#   ./install.sh --queue NAME --uri URI create queue NAME for URI (e.g. socket://10.0.0.5:9100)
#   ./install.sh --queue NAME --postscript   use the PostScript PPD for that queue
#   ./install.sh --uninstall            remove the driver (printer queues are left alone)
#   ./install.sh --dry-run ...          show what would be done
#
# Exit status: 0 = done, 1 = finished with problems, 2 = could not start.
# Written for macOS's /bin/bash 3.2.

set -Eeuo pipefail

readonly DRIVER_DIR=/Library/Printers/HL3070CW-Native
readonly PPD_DIR=/Library/Printers/PPDs/Contents/Resources
readonly NATIVE_PPD_NAME="Brother HL-3070CW native.ppd"
readonly PS_PPD_NAME="Brother HL-3070CW PostScript.ppd"
readonly NATIVE_NICK="Brother HL-3070CW, native driver (open source)" # as macOS lists it
readonly PKG_ID=io.github.rolandzeiner.hl3070cw-driver
readonly BROTHER_FILTER=/Library/Printers/Brother/Filter/rastertobrother3040.bundle/Contents/MacOS/rastertobrother3040
readonly BROTHER_LUT="/Library/Printers/Brother/Brother LUT"
# Absolute paths: commands run through sudo must not depend on the caller's PATH.
readonly SUDO_BIN=/usr/bin/sudo MKDIR=/bin/mkdir INSTALL=/usr/bin/install RM=/bin/rm
readonly LPADMIN=/usr/sbin/lpadmin LPSTAT=/usr/bin/lpstat STAT=/usr/bin/stat PKGUTIL=/usr/sbin/pkgutil

main() {
    DRY_RUN=0
    UNINSTALL=0
    QUEUE=''
    URI=''
    USE_PS=0
    PROBLEMS=0
    parse_args "$@"

    [[ $(/usr/bin/uname -s) == Darwin ]] || die "This installer is for macOS."
    if ((EUID == 0)); then SUDO=(); else SUDO=("$SUDO_BIN"); fi

    if ((UNINSTALL)); then
        uninstall
        exit 0
    fi

    local src_dir bin
    src_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || die "cannot find the installer's folder"
    bin=''
    for candidate in "$src_dir/build/rastertohl3070cw" "$src_dir/rastertohl3070cw"; do
        if [[ -x $candidate ]]; then
            bin=$candidate
            break
        fi
    done
    [[ -n $bin ]] || die "rastertohl3070cw not found next to the installer; build it with: make"
    local native_ppd="$src_dir/ppd/hl3070cw-native.ppd" ps_ppd="$src_dir/ppd/hl3070cw-postscript.ppd"
    [[ -f $native_ppd && -f $ps_ppd ]] || die "PPD files missing in $src_dir/ppd"
    # What gets installed as root, and run as root, must not be changeable by others.
    local f
    for f in "$bin" "$(dirname -- "$bin")" "$native_ppd" "$ps_ppd" "$src_dir/ppd"; do
        check_source "$f"
    done
    log "Filter: $("$bin" --version 2>/dev/null || printf 'unknown version')"

    log "Installing the filter into $DRIVER_DIR"
    run "${SUDO[@]+"${SUDO[@]}"}" "$MKDIR" -m 755 -p -- "$DRIVER_DIR"
    run "${SUDO[@]+"${SUDO[@]}"}" "$INSTALL" -m 755 -o root -g wheel "$bin" "$DRIVER_DIR/rastertohl3070cw"

    local have_brother=0
    if [[ -f $BROTHER_FILTER && -d $BROTHER_LUT ]]; then
        have_brother=1
        log "Copying Brother's halftone patterns, colour tables and ICC profiles"
        if ! run "${SUDO[@]+"${SUDO[@]}"}" "$DRIVER_DIR/rastertohl3070cw" --extract-brother-data; then
            if "$bin" --check-data; then
                warn "Copying Brother's data failed; keeping the copy from an earlier installation."
            else
                warn "Copying Brother's data failed; the native driver will not work."
                have_brother=0
            fi
        fi
    elif "$bin" --check-data; then
        have_brother=1
        log "Brother's driver is not installed, but a copy of its data is already in $DRIVER_DIR/data"
    else
        warn "Brother's HL-3070CW driver is not installed, so the native driver cannot be set up."
        warn "Install Brother's driver once (its data files are needed, not its filter), or use the PostScript PPD."
    fi

    log "Installing the PPD files into $PPD_DIR"
    run "${SUDO[@]+"${SUDO[@]}"}" "$INSTALL" -m 644 -o root -g wheel "$ps_ppd" "$PPD_DIR/$PS_PPD_NAME"
    if ((have_brother)); then
        run "${SUDO[@]+"${SUDO[@]}"}" "$INSTALL" -m 644 -o root -g wheel "$native_ppd" "$PPD_DIR/$NATIVE_PPD_NAME"
    fi

    if [[ -n $QUEUE ]]; then
        setup_queue "$have_brother"
    fi

    if ((PROBLEMS)); then
        printf '\nFinished with problems (see warnings above).\n'
        exit 1
    fi
    printf '\nDone.'
    if [[ -z $QUEUE ]]; then
        printf ' Add the printer in System Settings > Printers & Scanners and choose\n'
        printf '"%s" as the driver (Use: Select Software...).\n' "$NATIVE_NICK"
    else
        printf '\n'
    fi
}

setup_queue() {
    local have_brother=$1 ppd
    if ((USE_PS)); then
        ppd="$PPD_DIR/$PS_PPD_NAME"
    elif ((have_brother)); then
        ppd="$PPD_DIR/$NATIVE_PPD_NAME"
    else
        warn "Queue $QUEUE: native driver not available, using the PostScript PPD"
        ppd="$PPD_DIR/$PS_PPD_NAME"
    fi
    # The PPD is named as a model (its path without the leading slash), not
    # handed over as a file: only then does CUPS carry the queue's saved
    # defaults (Color / Mono, paper size ...) over into the new PPD.
    local args
    args=(-p "$QUEUE" -m "${ppd#/}")
    if [[ -n $URI ]]; then
        # a new queue: enabled, and not shared on the network
        args+=(-v "$URI" -E -o printer-is-shared=false)
    elif ! "$LPSTAT" -p "$QUEUE" >/dev/null 2>&1; then
        warn "Queue $QUEUE does not exist; give --uri to create it"
        return 0
    fi
    log "Switching printer queue $QUEUE to ${ppd##*/}"
    if ! run "$LPADMIN" "${args[@]}"; then
        warn "lpadmin failed for queue $QUEUE"
    fi
}

uninstall() {
    log "Removing the driver"
    local f
    for f in "$PPD_DIR/$NATIVE_PPD_NAME" "$PPD_DIR/$PS_PPD_NAME"; do
        if [[ -e $f ]]; then
            run "${SUDO[@]+"${SUDO[@]}"}" "$RM" -f -- "$f"
        fi
    done
    # DRIVER_DIR is a fixed constant; the guard only protects against editing mistakes.
    case "${DRIVER_DIR:?}" in
    /Library/Printers/?*) ;;
    *) die "refusing to remove unexpected path $DRIVER_DIR" ;;
    esac
    if [[ -d $DRIVER_DIR ]]; then
        run "${SUDO[@]+"${SUDO[@]}"}" "$RM" -rf -- "${DRIVER_DIR:?}"
    fi
    # the installer package's receipt, as uninstall.sh does
    if "$PKGUTIL" --pkg-info "$PKG_ID" >/dev/null 2>&1; then
        run "${SUDO[@]+"${SUDO[@]}"}" "$PKGUTIL" --forget "$PKG_ID" || warn "could not forget the package receipt"
    fi
    local queues
    queues=$("$LPSTAT" -v 2>/dev/null | /usr/bin/grep -i "HL3070CW\|hl-3070" || true)
    if [[ -n $queues ]]; then
        printf 'Printer queues are left as they are; switch or delete them in System Settings:\n%s\n' "$queues"
    fi
}

# Refuse a source file or folder that belongs to someone other than the caller
# (or root) or that group or others may write to.
check_source() {
    local path=$1 owner mode
    owner=$("$STAT" -f %u -- "$path") || die "cannot check $path"
    mode=$("$STAT" -f %Lp -- "$path") || die "cannot check $path"
    if [[ $owner != "$(/usr/bin/id -u)" && $owner != 0 ]]; then
        die "$path belongs to another user; refusing to install it as root"
    fi
    if ((8#$mode & 8#022)); then
        die "$path is writable by group or others; refusing to install it as root"
    fi
}

usage() {
    cat <<EOF
Usage: ${0##*/} [--queue NAME [--uri URI] [--postscript]] [--dry-run]
       ${0##*/} --uninstall [--dry-run]
EOF
}

parse_args() {
    while (($# > 0)); do
        case "$1" in
        -n | --dry-run) DRY_RUN=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --postscript) USE_PS=1 ;;
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

# shellcheck disable=SC2329  # called by the ERR trap
on_err() {
    printf '[ERROR] line %s: "%s" failed\n' "$1" "$2" >&2
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

main "$@"
exit
