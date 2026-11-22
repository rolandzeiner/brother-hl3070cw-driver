"""Attack add-brother-data.sh the way another process of the same user can.

    python3 -I tests/add-brother-data.py [HELPER]

macOS. Runs a copy of the helper on folders in a temporary folder, with a
stand-in for sudo that first tampers with everything the user can write to.
Root must never be given such a path. Nothing runs as root, nothing is installed.
Exit status: 0 = passed, 1 = failed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PPD = "Brother HL-3070CW native.ppd"
SECRET = "ROOT-ONLY-SECRET"


def script(path: str, text: str) -> None:
    with open(path, "w") as f:
        f.write("#!/bin/bash\n" + text)
    os.chmod(path, 0o755)


def main() -> int:
    if sys.platform != "darwin":
        print("SKIP add-brother-data: macOS only")
        return 0
    helper = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "packaging", "add-brother-data.sh")
    failed = []
    with tempfile.TemporaryDirectory() as td:
        drv, ppds, tmp, secret = (os.path.join(td, n) for n in ("driver", "ppds", "tmp", "secret"))
        for path in (f"{drv}/ppd", ppds, tmp, f"{td}/package/opt/brother/Printers/hl3070cw"):
            os.makedirs(path)
        with open(secret, "w") as f:
            f.write(SECRET + "\n")
        with open(f"{td}/package/opt/brother/Printers/hl3070cw/data", "w") as f:
            f.write("data\n")
        subprocess.run(["/usr/bin/tar", "-C", f"{td}/package", "-cf", f"{td}/fake.rpm", "."], check=True)
        shutil.copy(os.path.join(ROOT, "ppd", "hl3070cw-native.ppd"), f"{drv}/ppd/{PPD}")
        log, got = f"{td}/root-commands", f"{td}/unpacked"
        script(f"{drv}/rastertohl3070cw", f'''case "$1" in
--extract-brother-data) /bin/cp "{drv}/unpack/package/opt/brother/Printers/hl3070cw/data" "{got}" ;;
esac
''')
        script(f"{td}/sudo", f'''printf '%s\\n' "$*" >>"{log}"
for f in "{tmp}"/hl3070cw-data.*/*; do
    if [[ -f $f ]]; then /bin/ln -sf "{secret}" "$f"; fi
done
exec "$@"
''')
        script(f"{td}/install", '/bin/rm -f -- "$8"\n/bin/cp -- "$7" "$8"\n')
        with open(helper) as f:
            text = f.read()
        for old, new in (("DRIVER_DIR=/Library/Printers/HL3070CW-Native", f"DRIVER_DIR={drv}"),
                         ("PPD_DIR=/Library/Printers/PPDs/Contents/Resources", f"PPD_DIR={ppds}"),
                         ("SUDO_BIN=/usr/bin/sudo", f"SUDO_BIN={td}/sudo"),
                         ("INSTALL=/usr/bin/install", f"INSTALL={td}/install")):
            if text.count(old) != 1:
                print(f"FAIL add-brother-data: the test no longer finds {old}")
                return 1
            text = text.replace(old, new)
        with open(f"{td}/helper", "w") as f:
            f.write(text)
        os.chmod(f"{td}/helper", 0o755)

        for arg in ("--ppds-only", f"{td}/fake.rpm"):
            run = subprocess.run([f"{td}/helper", arg], env={"PATH": "/usr/bin:/bin", "TMPDIR": tmp},
                                 capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if run.returncode:
                failed.append(f"{os.path.basename(arg)} ended with {run.returncode}: {run.stderr.strip()[:200]}")
            installed = os.path.join(ppds, PPD)
            if not os.path.isfile(installed):
                failed.append(f"{os.path.basename(arg)}: no PPD installed")
                continue
            with open(installed, errors="replace") as f:
                shown = f.read()
            if SECRET in shown:
                failed.append(f"{os.path.basename(arg)}: a file only root may read became a readable PPD")
            elif "*PPD-Adobe" not in shown or "\n*cupsICC" in shown:
                failed.append(f"{os.path.basename(arg)}: wrong PPD installed")
        if "tested with" not in run.stdout + run.stderr:
            failed.append("no warning about an unknown package")
        with open(log) as f:
            for command in f:
                if tmp in command:
                    failed.append(f"root was given a path the user can change: {command.strip().replace(td, '')[:140]}")
        if not os.path.isfile(got):
            failed.append("the package's data did not reach the filter")
        if os.path.exists(f"{drv}/unpack"):
            failed.append("the unpacked package was left behind")
    for line in failed:
        print("FAIL add-brother-data:", line)
    if not failed:
        print("OK   add-brother-data: root is given no path the user can change")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
