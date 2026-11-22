#!/bin/bash
# Set up the native driver with Brother's data from a package of Brother's,
# without installing that package. Installed as
# /Library/Printers/HL3070CW-Native/add-brother-data.sh
#
#   add-brother-data.sh FILE      FILE: Brother's macOS driver (.pkg) or its
#                                 Linux LPR driver (.rpm: no colour profiles)
#   add-brother-data.sh --ppds-only
#                                 only put the native PPDs in place that fit
#                                 the data there is (the installers use this)
#
# Run it as yourself: it asks for the admin password where needed. The package
# is opened without root; as root only the fixed folder below is used.
# Exit status: 0 = done, 1 = failed, 2 = could not start.
# Written for macOS's /bin/bash 3.2.

set -Eeuo pipefail

readonly DRIVER_DIR=/Library/Printers/HL3070CW-Native
readonly PPD_DIR=/Library/Printers/PPDs/Contents/Resources
readonly FILTER=$DRIVER_DIR/rastertohl3070cw
readonly UNPACK_DIR=$DRIVER_DIR/unpack # where the filter looks for a package (--unpacked)
readonly SUDO_BIN=/usr/bin/sudo INSTALL=/usr/bin/install MKDIR=/bin/mkdir RM=/bin/rm
readonly BSDTAR=/usr/bin/bsdtar PKGUTIL=/usr/sbin/pkgutil

WORK=''
UNPACKING=0

main() {
    (($# == 1)) || usage
    if ((EUID == 0)); then SUDO=(); else SUDO=("$SUDO_BIN"); fi
    [[ -x $FILTER ]] || die "install the HL-3070CW driver first"
    WORK=$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/hl3070cw-data.XXXXXX") || die "cannot create a temporary folder"
    case "$1" in
    --ppds-only) install_ppds ;;
    -*) usage ;;
    *)
        ((EUID != 0)) || die "run it without sudo: Brother's package is not opened as root"
        add_data "$1"
        install_ppds
        printf 'Done. Add the printer in System Settings > Printers & Scanners (Use: Select Software...).\n'
        ;;
    esac
}

add_data() {
    local file=$1 root=$WORK/root found
    [[ -f $file ]] || die "$file does not exist"
    /bin/mkdir -p -- "$root"
    case "$file" in
    *.pkg)
        "$PKGUTIL" --expand-full "$file" "$WORK/pkg" || fail "cannot open $file"
        found=$(/usr/bin/find "$WORK/pkg" -type d \
            \( -path '*/Payload/Library/Printers/Brother' -o -path '*/Payload/Brother' \) -print -quit)
        [[ -n $found ]] || fail "$file holds no Brother printer driver"
        /bin/mkdir -p -- "$root/Library/Printers"
        /bin/mv -- "$found" "$root/Library/Printers/Brother"
        ;;
    *.rpm)
        "$BSDTAR" -xf "$file" -C "$root" || fail "cannot open $file"
        [[ -d $root/opt/brother/Printers/hl3070cw ]] || fail "$file is not Brother's HL-3070CW driver (hl3070cwlpr)"
        printf '%s\n' "The Linux package has no colour profiles: colours, and possibly greys, will look" \
            "slightly different from Brother's Mac driver."
        ;;
    *) die "give Brother's .pkg (open a .dmg first and use the .pkg in it) or its Linux .rpm" ;;
    esac
    COPYFILE_DISABLE=1 "$BSDTAR" -C "$root" -cf "$WORK/data.tar" . || fail "cannot read the unpacked package"

    UNPACKING=1
    as_root "$RM" -rf -- "${UNPACK_DIR:?}"
    as_root "$MKDIR" -m 700 -- "$UNPACK_DIR"
    as_root "$MKDIR" -m 755 -- "$UNPACK_DIR/package"
    as_root "$BSDTAR" --no-same-owner --no-same-permissions -xf "$WORK/data.tar" -C "$UNPACK_DIR/package" ||
        fail "cannot unpack the data"
    as_root "$FILTER" --extract-brother-data --unpacked || fail "Copying Brother's data failed"
}

# The native PPDs: none without data, and without *cupsICC lines when there
# are no colour profiles (macOS would look for the files they name).
install_ppds() {
    local data=0 profiles=0 src name use
    if "$FILTER" --check-data; then data=1; fi
    if [[ -f $DRIVER_DIR/data/profiles/broch08_PL_NM.icm && -f $DRIVER_DIR/data/profiles/broch08_PL_NM_IG_ON.icm ]]; then
        profiles=1
    fi
    for src in "$DRIVER_DIR/ppd/Brother "*" native.ppd"; do
        [[ -f $src ]] || continue
        name=${src##*/}
        if ((!data)); then
            as_root "$RM" -f -- "$PPD_DIR/$name"
            continue
        fi
        use=$src
        if ((!profiles)); then
            use="$WORK/$name"
            /usr/bin/sed '/^\*cupsICC/d' "$src" >"$use" || fail "cannot prepare $name"
        fi
        as_root "$INSTALL" -m 644 -o root -g wheel "$use" "$PPD_DIR/$name"
    done
}

as_root() { "${SUDO[@]+"${SUDO[@]}"}" "$@"; }

usage() {
    printf 'Usage: %s BROTHER-PACKAGE.pkg|.rpm\n       %s --ppds-only\n' "${0##*/}" "${0##*/}" >&2
    exit 2
}
fail() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}
die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 2
}

# shellcheck disable=SC2317,SC2329  # called by the EXIT trap
on_exit() {
    local status=$?
    set +e
    if ((UNPACKING)); then
        as_root "$RM" -rf -- "${UNPACK_DIR:?}"
    fi
    if [[ -n $WORK && -d $WORK ]]; then
        /bin/rm -rf -- "${WORK:?}"
    fi
    exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT TERM HUP

main "$@"
exit
