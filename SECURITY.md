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
- `rastertohl3070cw --extract-brother-data`, which the installer runs as root.
- `install.sh`, `uninstall.sh` and the installer package, which run with administrator rights.

The Python tools in `tools/` are for development only and are not installed.

## Supported versions

Only the latest release gets fixes.
