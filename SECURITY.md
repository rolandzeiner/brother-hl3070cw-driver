# Security policy

## Reporting a problem

Please report security problems privately through GitHub's
[security advisories](https://github.com/rolandzeiner/brother-hl3070cw-driver/security/advisories/new)
for this repository, not in a public issue. Include what you did, what happened and, if you have
one, a file that shows the problem.

## What is in scope

- `rastertohl3070cw`, the CUPS filter. It runs for every print job and reads data that any user
  who can print may send, so crashes, memory errors, very large memory use or hangs caused by a
  print job count as security problems.
- `rastertohl3070cw --extract-brother-data`, which the installers run as root. It must not read or
  write outside Brother's driver folder and the driver's own, whatever is in Brother's package or
  changes while it runs.
- `install.sh`, `install-linux.sh`, `uninstall.sh` and the installer package, which run with
  administrator rights.

The Python tools in `tools/` are for development only and are not installed.

## What the installers do as root

None of them downloads anything or runs a program of Brother's.

The Mac package (`.pkg`):

- puts the filter and `uninstall.sh` into `/Library/Printers/HL3070CW-Native` and two PPDs into
  `/Library/Printers/PPDs/Contents/Resources`,
- runs `packaging/postinstall`, which copies Brother's data with the filter
  (`--extract-brother-data`), checks an older copy (`--check-data`) if there is nothing to copy or
  copying fails, removes the native PPD when there is no complete data, and gives printers that use
  this driver the new PPD (`lpadmin -m`).

`install.sh` runs as you and uses `sudo` for installing the same filter and PPDs, for copying
Brother's data and, with `--uninstall`, for removing them and the package receipt. It calls
`lpadmin` as you.

`add-brother-data.sh` runs as you and opens Brother's package as you. With `sudo` it unpacks only
the result into `/Library/Printers/HL3070CW-Native/unpack`, which only root can enter, runs the
filter's `--extract-brother-data --unpacked`, removes that folder and installs the native PPDs. The
package and `install.sh` call it with `--ppds-only` for the last of these.

`uninstall.sh` removes the driver's folder and both PPDs and forgets the package receipt. Printers
are left as they are.

`install-linux.sh` runs as root:

- runs the filter it is about to install for `--version` and `--check-data`, after checking that
  nobody but you or root can change the file,
- puts the filter into `/usr/lib/cups/filter` and the PPDs into `/usr/share/ppd/hl3070cw`,
- unpacks Brother's package with `bsdtar`, or `dpkg-deb` and `tar`, without its owners and modes, in
  `/usr/share/hl3070cw-native/unpack`, which only root can enter and which is removed afterwards,
  and copies the data out of it,
- gives printers that use this driver the new PPD and creates or changes the printer named with
  `--queue` (`lpadmin`),
- with `--uninstall`, removes the filter, the PPDs and `/usr/share/hl3070cw-native`.

The print server's container starts as root without Linux capabilities it does not need, copies
Brother's data the same way at every start and writes CUPS's configuration. CUPS runs the filter as
`lp`.

## Supported versions

Only the latest release gets fixes.
