#!/bin/bash
# Remove the HL-3070CW driver (installed by the package or by install.sh).
# Printer queues that use it are left alone; remove them in System Settings.
#
#   sudo /Library/Printers/HL3070CW-Native/uninstall.sh
set -euo pipefail

readonly DRIVER_DIR=/Library/Printers/HL3070CW-Native
readonly PPD_DIR=/Library/Printers/PPDs/Contents/Resources

if ((EUID != 0)); then
    echo "Run it with sudo: sudo $0" >&2
    exit 2
fi
/bin/rm -f -- "$PPD_DIR/Brother HL-3070CW native.ppd" "$PPD_DIR/Brother HL-3070CW PostScript.ppd"
case "${DRIVER_DIR:?}" in
/Library/Printers/?*) /bin/rm -rf -- "${DRIVER_DIR:?}" ;;
*) exit 2 ;;
esac
/usr/sbin/pkgutil --forget io.github.rolandzeiner.hl3070cw-driver >/dev/null 2>&1 || true
echo "Removed the HL-3070CW driver. Printers that used it need a new driver: remove and add them again in System Settings."
