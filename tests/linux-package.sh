#!/usr/bin/env bash
# Test a Linux release package: install it in a throwaway container, print
# through CUPS into a local socket, uninstall it again.
#
#   docker run --rm -v "$PWD:/src:ro" debian:13 \
#       bash /src/tests/linux-package.sh /src/build/dist/NAME.tar.gz
#
# A second argument names Brother's real package (.rpm or .deb). Without it
# the test makes one up, as hostile as a package can be: every entry, "."
# included, belongs to another user and is writable by everyone.
# Exit status: 0 = passed, 1 = failed, 2 = could not start.

set -Eeuo pipefail
shopt -s inherit_errexit

readonly SHARE_DIR=/usr/share/hl3070cw-native
readonly FILTER=/usr/lib/cups/filter/rastertohl3070cw

WORK=''
SINK_PID=''

main() {
    (($# == 1 || $# == 2)) || die "usage: ${0##*/} TARBALL [BROTHER-PACKAGE]"
    [[ -f /.dockerenv && $EUID == 0 ]] || die "this installs and removes a driver: run it as root in a throwaway container"
    local tarball=$1 package=${2:-} src
    src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
    [[ -f $tarball ]] || die "$tarball does not exist"

    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends cups cups-client cups-bsd cups-filters ghostscript poppler-utils \
        fonts-dejavu-core libarchive-tools python3 >/dev/null 2>&1 || die "cannot install CUPS"

    WORK=$(mktemp -d)
    tar -xzf "$tarball" -C "$WORK"
    local dir
    dir=$(find "$WORK" -mindepth 1 -maxdepth 1 -type d -name 'HL3070CW-Driver-*' -print -quit)
    [[ -x $dir/rastertohl3070cw && -x $dir/install-linux.sh ]] || fail "driver or installer missing in the package"

    local packages=()
    if [[ -n $package ]]; then
        packages=("$package")
    else
        make_packages "$src"
        packages=("$WORK/fake.rpm" "$WORK/fake.deb")
    fi

    cupsd
    local i
    for ((i = 0; i < 60; i++)); do
        [[ $(LC_ALL=C lpstat -r 2>/dev/null) == 'scheduler is running' ]] && break
        sleep 0.5
    done
    start_sink

    local pkg
    for pkg in "${packages[@]}"; do
        "$dir/install-linux.sh" --brother-package "$pkg" --queue native --uri socket://127.0.0.1:9101
        [[ ! -e $SHARE_DIR/unpack ]] || fail "the unpacked package was left behind"
        check_data
        print_job native xl2hb -o BRMonoColor=Mono
        print_job native xl2hb -o BRMonoColor=FullColor -o BRResolution=600x2400dpi
        printf 'OK   native driver, data from %s\n' "${pkg##*/}"
    done
    # without a package: the data of the earlier installation is kept
    "$dir/install-linux.sh" --queue postscript --postscript --uri socket://127.0.0.1:9101
    check_data
    print_job postscript postscript -o BRMonoColor=Mono
    printf 'OK   PostScript driver, update without a package\n'

    "$dir/install-linux.sh" --uninstall
    local left
    for left in "$FILTER" "$SHARE_DIR" /usr/share/ppd/hl3070cw; do
        [[ ! -e $left ]] || fail "uninstall left $left"
    done
    printf 'OK   uninstalled\n'
}

make_packages() {
    local tree=$WORK/tree deb=$WORK/deb
    python3 -I - "$1/tools" "$WORK/made" "$tree/opt/brother/Printers/hl3070cw" <<'PY'
import os
import shutil
import sys

sys.path.insert(0, sys.argv[1])
import selftest

made, top = sys.argv[2:4]
selftest.make_data(made)
os.makedirs(os.path.join(top, "inf/lut"))
os.makedirs(os.path.join(top, "lpd"))
for name in os.listdir(made):
    if name.endswith("_cache08.bin"):
        shutil.copyfile(os.path.join(made, name), os.path.join(top, "inf/lut", name))
with open(os.path.join(top, "lpd/brhl3070cwfilter"), "wb") as f:
    f.write(selftest.brother_tables())
PY
    chown -R 1234:1234 "$tree"
    chmod -R 0777 "$tree"
    tar -C "$tree" -cf "$WORK/fake.rpm" . # bsdtar goes by the content, not the name
    cp -a "$tree" "$deb"
    mkdir -m 755 "$deb/DEBIAN"
    printf '%s\n' 'Package: hl3070cwlpr' 'Version: 1' 'Architecture: all' \
        'Maintainer: Test <test@example.invalid>' 'Description: made up for a test' >"$deb/DEBIAN/control"
    chmod 644 "$deb/DEBIAN/control"
    dpkg-deb -Zgzip --build "$deb" "$WORK/fake.deb" >/dev/null 2>&1
}

check_data() {
    local bad count
    bad=$(find "$SHARE_DIR" \( ! -user root -o -perm -002 -o -perm -020 \) -print)
    [[ -z $bad ]] || fail "unsafe owner or mode: $bad"
    count=$(find "$SHARE_DIR/data" -type f | wc -l)
    ((count >= 28)) || fail "only $count data files"
}

start_sink() {
    python3 -I -c '
import socket, sys, os
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 9101))
s.listen(5)
open(os.path.join(sys.argv[1], "listening"), "w").close()
n = 0
while True:
    c, _ = s.accept()
    n += 1
    with open(os.path.join(sys.argv[1], "job.part"), "wb") as f:
        while True:
            b = c.recv(65536)
            if not b:
                break
            f.write(b)
    c.close()
    os.rename(os.path.join(sys.argv[1], "job.part"), os.path.join(sys.argv[1], "job"))
' "$WORK" &
    SINK_PID=$!
    local i
    for ((i = 0; i < 50; i++)); do
        [[ -e $WORK/listening ]] && return 0
        sleep 0.2
    done
    fail "the test's socket did not open"
}

# print_job QUEUE KIND [lp options]
print_job() {
    local queue=$1 kind=$2 i
    shift 2
    rm -f -- "${WORK:?}/job"
    printf 'HL-3070CW package test\n' >"$WORK/page.txt"
    lp -d "$queue" "$@" "$WORK/page.txt" >/dev/null
    for ((i = 0; i < 240; i++)); do
        [[ -s $WORK/job ]] && break
        sleep 0.5
    done
    if [[ ! -s $WORK/job ]]; then
        tail -n 40 /var/log/cups/error_log >&2 || true
        fail "nothing printed on $queue"
    fi
    python3 -I - "$SRC_TOOLS" "$WORK/job" "$kind" <<'PY' || fail "bad output on $queue"
import sys

sys.path.insert(0, sys.argv[1])
import pxl

raw = open(sys.argv[2], "rb").read()
if sys.argv[3] == "postscript":
    ok = b"@PJL ENTER LANGUAGE=POSTSCRIPT" in raw and b"RENDERMODE=GRAYSCALE" in raw and b"%!" in raw
else:
    names = [op.name for op in pxl.parse(raw).ops]
    ok = names.count("BeginPage") == 1 and names.count("ReadImage") > 0 and raw.endswith(b"\x1b%-12345X")
sys.exit(0 if ok else 1)
PY
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
    if [[ -n $SINK_PID ]]; then
        kill "$SINK_PID" 2>/dev/null
    fi
    if [[ -n $WORK && -d $WORK ]]; then
        rm -rf -- "${WORK:?}"
    fi
    exit "$status"
}

SRC_TOOLS=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../tools" && pwd -P)
readonly SRC_TOOLS
trap on_exit EXIT
trap 'exit 130' INT TERM HUP

main "$@"
exit
