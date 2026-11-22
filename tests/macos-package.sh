#!/bin/bash
# Test the macOS installer package on a GitHub build machine: install it next
# to a made-up copy of Brother's driver, print through CUPS into a local
# socket, update it (also with a damaged copy of Brother's driver), uninstall
# it. It overwrites /Library/Printers/Brother, so it refuses
# to run anywhere else.
#
#   tests/macos-package.sh build/pkg/NAME.pkg
#
# Exit status: 0 = passed, 1 = failed, 2 = could not start.
# Written for macOS's /bin/bash 3.2.

set -Eeuo pipefail

readonly BROTHER=/Library/Printers/Brother
readonly DRIVER_DIR=/Library/Printers/HL3070CW-Native
readonly MODELS=Library/Printers/PPDs/Contents/Resources

WORK=''
NC_PID=''

main() {
    (($# == 1)) || die "usage: ${0##*/} PACKAGE"
    [[ ${GITHUB_ACTIONS:-} == true && ! -e $BROTHER ]] ||
        die "only for a throwaway build machine without Brother's driver"
    local pkg=$1 src
    src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
    WORK=$(mktemp -d "${TMPDIR:-/tmp}/hl3070cw-test.XXXXXX")

    python3 -I - "$src/tools" "$WORK/made" "$WORK/Brother" <<'PY'
import os
import shutil
import sys

sys.path.insert(0, sys.argv[1])
import selftest

made, top = sys.argv[2:4]
selftest.make_data(made)
for sub in ("Brother LUT", "Profiles", "Filter/rastertobrother3040.bundle/Contents/MacOS"):
    os.makedirs(os.path.join(top, sub))
for name in os.listdir(made):
    if name.endswith("_cache08.bin"):
        shutil.copyfile(os.path.join(made, name), os.path.join(top, "Brother LUT", name))
with open(os.path.join(top, "Filter/rastertobrother3040.bundle/Contents/MacOS/rastertobrother3040"), "wb") as f:
    f.write(selftest.brother_tables())
# any valid RGB profile will do for macOS's colour matching
for name in ("NM", "NM_IG_ON", "Fi", "Fi_IG_ON"):
    shutil.copyfile("/System/Library/ColorSync/Profiles/sRGB Profile.icc",
                    os.path.join(top, "Profiles", f"broch08_PL_{name}.icm"))
PY
    sudo mkdir -p /Library/Printers
    sudo cp -R "$WORK/Brother" "$BROTHER"
    sudo chown -R root:wheel "$BROTHER"
    sudo chmod -R u=rwX,go=rX "$BROTHER"

    sudo installer -pkg "$pkg" -target /
    local files
    files=$(find "$DRIVER_DIR/data" -type f | wc -l | tr -d ' ')
    [[ $files == 32 ]] || fail "$files data files, want 32"

    local ppd
    for ppd in "Brother HL-3070CW native" "Brother HL-3070CW PostScript"; do
        # no waivers: everything the PPDs name is installed now
        cupstestppd "/$MODELS/$ppd.ppd" || fail "cupstestppd refuses $ppd"
    done

    sudo lpadmin -p hl_native -E -v socket://127.0.0.1:9101/?waiteof=false -m "$MODELS/Brother HL-3070CW native.ppd"
    sudo lpadmin -p hl_ps -E -v socket://127.0.0.1:9101/?waiteof=false -m "$MODELS/Brother HL-3070CW PostScript.ppd"
    print_job hl_native 'XL2HB' -o BRMonoColor=Mono
    print_job hl_native 'XL2HB' -o BRMonoColor=FullColor -o BRResolution=600x2400dpi
    print_job hl_ps 'POSTSCRIPT' -o BRMonoColor=Mono

    # updating over itself: the printers keep their settings
    sudo lpadmin -p hl_native -o BRMonoColor=Mono
    sudo installer -pkg "$pkg" -target /
    sudo grep -q '^\*DefaultBRMonoColor: Mono' /etc/cups/ppd/hl_native.ppd || fail "updating lost the printer's setting"
    print_job hl_native 'XL2HB'

    # Brother's driver damaged: a complete earlier copy keeps serving ...
    sudo rm -f "$BROTHER/Brother LUT/0600-k_cache08.bin"
    sudo installer -pkg "$pkg" -target /
    [[ -f "/$MODELS/Brother HL-3070CW native.ppd" ]] || fail "a failed copy removed the native PPD"
    print_job hl_native 'XL2HB'
    # ... an incomplete one does not
    sudo rm -f "$DRIVER_DIR/data/0600-k_cache08.bin"
    sudo installer -pkg "$pkg" -target /
    [[ ! -e "/$MODELS/Brother HL-3070CW native.ppd" ]] || fail "native PPD installed without complete data"
    printf 'OK   a failed copy keeps complete older data, and only that\n'

    sudo "$DRIVER_DIR/uninstall.sh"
    [[ ! -e $DRIVER_DIR ]] || fail "uninstall left $DRIVER_DIR"
    printf 'OK   installed, printed, updated and uninstalled\n'
}

# print_job QUEUE LANGUAGE [lp options]
print_job() {
    local queue=$1 language=$2 i
    shift 2
    nc -l 127.0.0.1 9101 >"$WORK/job" </dev/null &
    NC_PID=$!
    sleep 1
    printf 'HL-3070CW package test\n' >"$WORK/page.txt"
    lp -d "$queue" "$@" "$WORK/page.txt" >/dev/null
    for ((i = 0; i < 120; i++)); do
        kill -0 "$NC_PID" 2>/dev/null || break
        sleep 1
    done
    if ! grep -a -q "ENTER LANGUAGE=$language" "$WORK/job"; then
        sudo tail -n 40 /var/log/cups/error_log >&2 || true
        fail "nothing usable printed on $queue"
    fi
    grep -a -q '@PJL EOJ' "$WORK/job" || fail "the job on $queue was not closed"
    NC_PID=''
    printf 'OK   %s printed %s\n' "$queue" "$language"
}

fail() {
    printf 'FAIL %s\n' "$*" >&2
    exit 1
}

die() {
    printf '%s\n' "$*" >&2
    exit 2
}

# shellcheck disable=SC2317,SC2329  # called by the EXIT trap
on_exit() {
    local status=$?
    set +e
    if [[ -n $NC_PID ]]; then
        kill "$NC_PID" 2>/dev/null
    fi
    if [[ -n $WORK && -d $WORK ]]; then
        rm -rf -- "${WORK:?}"
    fi
    exit "$status"
}

trap on_exit EXIT
trap 'exit 130' INT TERM HUP

main "$@"
exit
