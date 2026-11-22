# Brother HL-3070CW driver for macOS and Linux

[![Latest release](https://img.shields.io/github/v/release/rolandzeiner/brother-hl3070cw-driver?label=download)](https://github.com/rolandzeiner/brother-hl3070cw-driver/releases/latest)
![macOS 11 or newer](https://img.shields.io/badge/macOS-11%2B-blue)
![Linux x86_64 and arm64](https://img.shields.io/badge/Linux-x86__64%20%26%20arm64-blue)
![Apple Silicon and Intel](https://img.shields.io/badge/Apple%20Silicon%20%26%20Intel-native-green)
![Status: beta](https://img.shields.io/badge/status-beta-orange)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
[![vibe-coded](https://img.shields.io/badge/vibe-coded-ff69b4?logo=musicbrainz&logoColor=white)](https://en.wikipedia.org/wiki/Vibe_coding)

Keep printing on your Brother HL-3070CW colour laser printer with a current Mac, a Linux PC or a
Raspberry Pi. Nine printers with the same engine are supported too, untested
([Supported printers](#supported-printers)).

Brother's own macOS driver for this printer contains a program for Intel processors. On Apple
Silicon Macs it only runs through Rosetta 2, which Apple keeps available only through macOS 27.
Upgrading to macOS 27 also removed Rosetta until 27.2, so Brother's driver may have stopped already.
This project is an open-source replacement that runs natively on Apple Silicon and Intel Macs.
Black-and-white pages come out exactly as with Brother's driver, also in Fine quality, and colour
pages practically the same. It also runs on Linux, for example on a Raspberry Pi
([Linux and Raspberry Pi](#linux-and-raspberry-pi)).

This project is not made or endorsed by Brother.

## Contents

- [Supported printers](#supported-printers)
- [Install](#install)
- [Add the printer](#add-the-printer)
- [Print](#print)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [Linux and Raspberry Pi](#linux-and-raspberry-pi)
- [What works](#what-works)
- [How it works](#how-it-works)
- [For developers](#for-developers)
- [Security](#security)
- [License and trademarks](#license-and-trademarks)

## Supported printers

| Printer | Native driver | PostScript driver | Tested |
|---|:---:|:---:|:---:|
| HL-3070CW | Yes | Yes | **Yes** |
| HL-3040CN | Yes, from 0.5.2 | No | No |
| HL-3045CN | Yes, from 0.5.2 | No | No |
| HL-3075CW | Yes, from 0.5.2 | No | No |
| DCP-9010CN | Yes, from 0.5.2 | No | No |
| MFC-9010CN | Yes, from 0.5.2 | No | No |
| MFC-9120CN | Yes, from 0.5.2 | No | No |
| MFC-9125CN | Yes, from 0.5.2 | No | No |
| MFC-9320CW | Yes, from 0.5.2 | No | No |
| MFC-9325CW | Yes, from 0.5.2 | No | No |

*Tested* means that this driver has printed on that printer, on paper. On the HL-3070CW that was in
black and white. Colour has not been printed on paper yet ([What works](#what-works)).

The other nine have the same engine. In all 65 of the project's test jobs, Brother's own driver
writes the same data for each of them as for the HL-3070CW. They are marked *untested* in the list
of drivers too. If you have one, please
[tell us whether it prints](https://github.com/rolandzeiner/brother-hl3070cw-driver/issues): the
form asks for the model.

For those nine:

- The driver uses the data files of Brother's HL-3070CW driver. Follow the instructions below as
  they are written, also where they say HL-3070CW, and choose your own model when you add the
  printer.
- Only printing is supported. Faxing and scanning are not.
- The [Docker print server](docker/README.md) supports only the HL-3070CW.

## Install

These steps are for a Mac. On Linux, follow [Linux and Raspberry Pi](#linux-and-raspberry-pi).

You need a Mac with macOS 11 Big Sur or newer and an administrator password. You do not need a
GitHub account or any developer tools.

### 1. Check for Brother's driver

The driver comes in two versions. The PostScript one is for the HL-3070CW only.

| | Native driver | PostScript driver |
|---|---|---|
| Print quality | Same as Brother's driver | The printer renders the page itself; light greys and yellow come out weaker |
| Needs Brother's driver files on the Mac | Yes | No |

The native version uses some data files (halftone patterns, colour tables and colour profiles)
from Brother's own macOS driver for the HL-3070CW. If you have printed with this printer, or one of the
other [supported printers](#supported-printers), using Brother's driver on this Mac before, those files are almost certainly there already, and you can go on to step 2.

If not, install Brother's driver first:

1. Open Brother's [list of older systems for the HL-3070CW](https://support.brother.com/g/b/downloadlistdiscon.aspx?c=us&lang=en&prod=hl3070cw_all).
   The normal download page no longer lists macOS. It links to this list as
   *Cannot see your OS family? Click here.*
2. Choose **macOS 10.15.x**, the newest one there, also if your macOS is newer. Download and install
   the **Printer Driver**, version 1.4.0 of 27 September 2019.

This project was tested with the files of an existing installation of Brother's driver, whose
package is `Brother_PrinterDrivers_ColorLaser`, version 5.0.0. Whether that download contains the
same files, and whether it installs on macOS 27, has not been checked. Only the data files are used;
Brother's Intel program is never run.

From version 0.5.2 you can also take the data out of Brother's package without installing it. Install
this driver (steps 2 to 4), then give the package to this helper, without `sudo`:

- Brother's Mac package, a `.pkg`. If you have a `.dmg`, open it and use the `.pkg` inside. This was
  tested with a package rebuilt from an installed copy of Brother's driver, not yet with Brother's
  own download.
- Or Brother's Linux driver `hl3070cwlpr-1.1.2-1.i386.rpm` from the
  [Linux section](#linux-and-raspberry-pi). It has no colour profiles, so colours, and possibly
  greys, then look slightly different from Brother's Mac driver.

```sh
/Library/Printers/HL3070CW-Native/add-brother-data.sh ~/Downloads/hl3070cwlpr-1.1.2-1.i386.rpm
```

If you cannot get Brother's files and have an HL-3070CW, use the PostScript version of this driver.
It works without them.

### 2. Download the installer

Open the [latest release](https://github.com/rolandzeiner/brother-hl3070cw-driver/releases/latest).
Under **Assets**, click the file ending in `.pkg` (for example `HL3070CW-Driver-0.5.2.pkg`). It
goes to your Downloads folder.

To check that a file was built by GitHub from this repository (releases after 0.5.0, with the
[GitHub CLI](https://cli.github.com)):

```sh
gh attestation verify ~/Downloads/FILE --repo rolandzeiner/brother-hl3070cw-driver
```

### 3. Open the installer

Double-click the downloaded file. The first time, macOS refuses to open it:

> **"HL3070CW-Driver-0.5.2.pkg" Not Opened**
> Apple could not verify "HL3070CW-Driver-0.5.2.pkg" is free of malware that may harm your Mac or
> compromise your privacy.

macOS shows this for every installer that is not signed with a paid Apple developer certificate,
which this free project does not have. GitHub builds the package from this repository's code, and
the release's `SHA256SUMS` file has its checksum. To open it anyway:

1. Click **Done**. Do not click **Move to Trash**.
2. Open **System Settings** and click **Privacy & Security** in the sidebar.
3. Scroll down to **Security**. There is a line saying that "HL3070CW-Driver-0.5.2.pkg" was
   blocked to protect your Mac. Click **Open Anyway** next to it. The button appears only for
   about an hour after you tried to open the file; if it is missing, double-click the file again
   first.
4. macOS asks once more: click **Open Anyway** and confirm with your password or Touch ID. The
   installer opens.

On macOS 14 Sonoma and older, right-clicking the file and choosing **Open** also works.

If you are comfortable with Terminal, this removes the download mark from the file instead, after
which a double-click opens it directly:

```sh
xattr -d com.apple.quarantine ~/Downloads/HL3070CW-Driver-0.5.2.pkg
```

### 4. Run the installer

Click through the installer and enter your administrator password when asked. It installs the
native driver for all [supported printers](#supported-printers) and the PostScript driver for the
HL-3070CW. If Brother's driver files are missing, only the PostScript driver is listed until you
have added the files ([step 1](#1-check-for-brothers-driver)).

### Updating

To update, download the newest installer and run it the same way. Printers you have already added
keep their settings. The installer gives them the new version's options (Print Quality came with
0.4.0), so you do not have to remove and add them again.

## Add the printer

macOS cannot change the driver of a printer that is already set up, so if your printer is already
in the list, remove it first and add it again.

1. Open **System Settings** > **Printers & Scanners**.
2. If your printer is listed, select it and click **Remove Printer** (or the **−** button).
3. Make sure the printer is switched on and connected to your network. Click **Add Printer, Scanner or Fax...**.
4. Select your printer in the list.
   - If it does not appear, click the globe icon (**IP**). Enter the printer's IP address, set
     **Protocol** to **HP Jetdirect - Socket**, and leave **Queue** empty. The printer's own
     display shows its IP address in its network settings.
5. In **Use**, choose **Select Software...**, type your model into the search field, for example
   `HL-3070CW`, select the entry and click **OK**:
   - HL-3070CW: **Brother HL-3070CW, native driver (open source)**, or
     **Brother HL-3070CW, PostScript (BR-Script 3)**.
   - The other nine: the entry with your model that ends in
     **native driver (open source, untested)**, for example
     **Brother HL-3040CN, native driver (open source, untested)**.

   The entries ending in *CUPS* and *BR-Script3* (without a space) are Brother's own.
6. Click **Add**.

## Print

Print as usual. The printer's options are in the print dialog, in the section called
**Printer Options** or **Printer Features** depending on your macOS version. The list is for the
native driver; [What works](#what-works) shows which of them the PostScript driver has.

- **Color / Mono**: *Auto* lets the printer decide, *Color* always prints in colour, *Mono* always
  in black and white. Choose *Mono* if a colour toner cartridge is empty: the printer refuses
  colour jobs then, but still prints black and white.
- **Print Quality**: *Normal* (600 dpi) or *Fine* (2400 dpi class), as in Brother's driver. Fine
  sends more data to the printer, so large pages take longer to start.
- **Color Mode**: *Normal*, *Vivid* or *None*, as in Brother's driver.
- **Improve Gray Color**, **Enhance Black Printing**, **Toner Save Mode** and **Improve Print
  Output** (less paper curl or better toner fixing) work as in Brother's driver. Enhance Black
  Printing applies to colour jobs only.
- **Custom paper sizes** (from version 0.5.2) from 70 x 116 mm to 215.9 x 406.4 mm work with the
  native driver. The data matches what Brother's driver sends. Choosing them in the print dialog,
  and printing them on paper, has not been tested.
- **Paper size**, **paper source** (tray or manual feed) and **media type** (plain, thin, thick,
  envelopes, labels and more) are in the usual places.

From version 0.5.2 the options are in English and German, following the language of your system. The
names in this guide are the English ones.

To make black and white the default, open the print dialog, set **Color / Mono** to **Mono** and
save the settings as a preset.

### Secure Print

Secure Print keeps a document in the printer until you are there to collect it. In the print
dialog, open **Print Job Security**, turn on **Print with PIN** and enter 4 digits. The printer
stores the job and prints nothing. To print it, press **Secure Print** on the printer, choose
your user name and the document with **+** and **−**, and enter the PIN.

- The PIN must be 4 digits. A job with any other PIN is not printed at all. (Brother's driver
  prints such a job without a PIN.)
- The printer lists your user name and the title of the document.
- Secure Print works with the native driver. The PostScript driver does not offer it.
- From Terminal: `lp -o job-password=1234 document.pdf`.

## Troubleshooting

**macOS says the installer cannot be opened.** See [step 3](#3-open-the-installer).

**"Brother HL-3070CW, native driver (open source)" is not in the list of drivers.** Brother's driver
files were not found or not complete when you installed. The same goes for the entries of the other
printers. Either install Brother's driver and run this installer again, or take the files from
Brother's package with `add-brother-data.sh` (both in [step 1](#1-check-for-brothers-driver)). Until
then, an HL-3070CW can use **Brother HL-3070CW, PostScript (BR-Script 3)**.

**"The printer software is not compatible with this device."** The printer still uses a driver for
Intel processors, usually Brother's own: it was added before you installed this driver, or Brother's
entry was picked in the list. Remove the printer and add it again with **Select Software...**, as in
[Add the printer](#add-the-printer).

**The print dialog still shows the old options after an update.** Apps remember a printer's options
while they run. Quit the app (Cmd+Q), open it again and print.

**Print Quality is missing from the print dialog.** The printer was added with an older version of
this driver. Run the newest installer; it updates the printers that are already set up.

**Fine prints the same as Normal.** The files for Fine quality come from Brother's driver. If they
were not on the Mac when you installed, Fine jobs are printed in Normal quality. Add them as in
[step 1](#1-check-for-brothers-driver).

**The printer does not respond or jobs wait in the queue.** Check that the printer is switched on
and on the same network as the Mac. A job sent while the printer is off is printed once it is
switched on (macOS cancels it after three hours).

**The display shows "Replace Toner" and nothing prints.** One toner cartridge is empty. Print with
**Color / Mono** set to **Mono**, or replace the cartridge.

**Faint copies of text or images appear further down the page.** That is "ghosting", caused by an
old toner cartridge or drum unit, not by the driver.

**You want to see what the installer did.** This line in Terminal shows whether Brother's data was
copied and which printers got the new driver files:

```sh
grep -E "postinstall: (Brother|Copying|Printer|Could not)" /var/log/install.log
```

**Something else.** [Open an issue](https://github.com/rolandzeiner/brother-hl3070cw-driver/issues)
and describe your printer model, what you printed and what happened. A GitHub account is needed for
that.

## Uninstall

1. Open **Terminal**: press Cmd+Space, type `Terminal` and press Return.
2. Paste this line, press Return and enter your password (it is not shown while you type). It
   removes the driver for all supported printers:

   ```sh
   sudo /Library/Printers/HL3070CW-Native/uninstall.sh
   ```

3. Remove the printer in **System Settings** > **Printers & Scanners**, or add it again with a
   different driver.

## Linux and Raspberry Pi

The driver also runs on Linux with CUPS, for example on a Raspberry Pi, which can then offer the
printer to every computer and phone in the house. Each release has a package for 64-bit ARM and one
for 64-bit Intel and AMD, both with the native driver for all
[supported printers](#supported-printers) and the PostScript driver for the HL-3070CW. They need Debian 12,
Raspberry Pi OS 12, Ubuntu 24.04 or newer. Each is installed and printed through CUPS automatically
on Debian 12, Debian 13 and Ubuntu 24.04 before a release. 32-bit systems are not supported.

1. For the native driver, download Brother's Linux driver for the HL-3070CW, also if you have one of
   the other supported printers, from Brother's
   [HL-3070CW download page](https://support.brother.com/g/b/downloadtop.aspx?c=us&lang=en&prod=hl3070cw_all):
   choose **Linux**, then the **LPR printer driver** as an rpm or a deb package. Brother made it
   for Intel PCs, but the installer only takes the halftone patterns and colour tables out of it
   and never runs Brother's program, so it serves a Raspberry Pi as well. This project was tested
   with `hl3070cwlpr-1.1.2-1.i386.rpm`.
2. From the [latest release](https://github.com/rolandzeiner/brother-hl3070cw-driver/releases/latest),
   download the package for your processor (`uname -m` shows it): `linux-arm64` for `aarch64`,
   `linux-x86_64` for `x86_64`. Install what it needs and unpack it, here for a Raspberry Pi:

   ```sh
   sudo apt install cups cups-filters libarchive-tools
   tar -xzf ~/Downloads/HL3070CW-Driver-0.5.2-linux-arm64.tar.gz
   cd HL3070CW-Driver-0.5.2-linux-arm64
   ```

3. Install it with the path of Brother's package. To add the printer at the same time, give it a
   name and the printer's IP address:

   ```sh
   sudo ./install-linux.sh --brother-package ~/Downloads/hl3070cwlpr-1.1.2-1.i386.rpm \
       --queue HL3070CW --uri socket://192.0.2.10:9100
   ```

   For an rpm other than the one this was tested with, the installer prints a warning and goes on.

   Without `--queue`, add the printer in your system's printer settings and choose
   **Brother HL-3070CW, native driver (open source)** as the driver.

   The PostScript driver needs no files of Brother's. `--postscript` works only together with
   `--queue`:

   ```sh
   sudo ./install-linux.sh --postscript --queue HL3070CW --uri socket://192.0.2.10:9100
   ```

   Without Brother's files the installer warns that the native driver is missing and ends with
   "Finished with problems". The PostScript printer is set up all the same.

   `--queue` always sets up an HL-3070CW. For one of the other nine printers, run the installer with
   `--brother-package` only, then create the printer with the PPD of your model. The file name is
   the model in lower case without the hyphen, here for an MFC-9320CW:

   ```sh
   sudo lpadmin -p MFC9320CW -E -v socket://192.0.2.10:9100 \
       -P /usr/share/ppd/hl3070cw/mfc9320cw-native.ppd
   ```

All options work as on a Mac, Fine and Secure Print included (`lp -o job-password=1234 file`). Two
differences:

- On a Mac, Brother's colour profiles adjust colours before the driver gets the page. Brother's
  Linux driver has no colour profiles, so colours, and possibly greys, can look slightly different
  from a Mac.
- If a firewall on the Linux machine blocks outgoing connections, allow port 9100 (printing) and
  161/udp (printer status) to the printer.

To update, unpack the newest release and run its `sudo ./install-linux.sh`; printers keep their
settings, and Brother's package is not needed again. To remove the driver:
`sudo ./install-linux.sh --uninstall`.

To build it yourself instead of step 2:

```sh
sudo apt install build-essential libcups2-dev cups cups-filters libarchive-tools git
umask 022    # the installer refuses files that others may change
git clone https://github.com/rolandzeiner/brother-hl3070cw-driver.git
cd brother-hl3070cw-driver
make
```

To share an HL-3070CW with every computer and phone in the house over AirPrint, run it as a print
server in Docker, for example on a Raspberry Pi: see [docker/README.md](docker/README.md). Use 0.5.2
or newer for it: the earlier ones have security flaws.

## What works

This is for the HL-3070CW. The native driver gives the other [supported printers](#supported-printers)
the same data, untested on paper.

| | Native driver | PostScript driver |
|---|---|---|
| Black and white | Identical to Brother's driver, byte for byte | The printer's own rendering |
| Colour | Brother's colour tables and halftones; about 99.96 % of all dots identical to Brother's driver | The printer's own rendering |
| Fine quality (2400 dpi class) | The same dots as Brother's driver (in colour: as above); the compressed data matches Brother's for about 95 % of lines | Not available |
| Paper sizes | All 22 of Brother's driver, and custom sizes from 0.5.2 | All 22 |
| Tray and manual feed | Yes | Yes |
| Media types | All 11 | All 11 |
| Color / Mono / Auto, Color Mode, Improve Gray, Enhance Black, Improve Print Output | Yes | Color / Mono only |
| Toner Save | Yes | Yes |
| Secure Print (PIN) | Yes | No |
| Sleep Time (the printer's power-saving delay) | No, set it on the printer | No, set it on the printer |
| Option names in German | From 0.5.2 | From 0.5.2 |

The driver has been tested with an HL-3070CW connected over Wi-Fi. Ethernet and USB should work the
same way but have not been tested.

With versions 0.4.0 and 0.4.1, black-and-white pages have been printed on paper from a Mac and
through a Raspberry Pi, in Normal and in Fine quality, and as Secure Print jobs released on the
printer's panel with their PIN. Later versions give the same printer data for such pages in the
project's tests and have not been printed on paper yet. Colour has so far only been compared with
the data Brother's driver produces, because the test printer's cyan cartridge is empty. If a colour
page looks wrong, please
[open an issue](https://github.com/rolandzeiner/brother-hl3070cw-driver/issues).

Like other printer drivers of this kind (Brother's included), it is a PPD-based driver. macOS 27 and
CUPS 2.4, as in current Linux distributions, support these. CUPS, the printing system of macOS and
Linux, has marked such drivers as deprecated, so a later version of either system could need a
different approach.

## How it works

The HL-3070CW expects pages in Brother's own printer language, called XL2HB: a few printer
commands (PJL and parts of HP's PCL XL) around compressed black-and-white bands for each of the four
toner colours. Brother never published this format. It was worked out by feeding test pages to
Brother's driver and decoding what came out, without disassembling Brother's code.
[docs/FORMAT.md](docs/FORMAT.md) describes the format in full.

The driver itself is a small program in C (`rastertohl3070cw`). The printing system turns your
document into an image; the driver converts the image into Brother's halftone dots and compresses them the way the
printer expects.

The halftone patterns, colour tables and colour profiles are Brother's. On a Mac, the installer
copies them from Brother's installed driver, or `add-brother-data.sh` from a package of Brother's,
into `/Library/Printers/HL3070CW-Native/data`. All supported printers share them. Without profiles
(data from the Linux package), the driver's PPDs go in without colour matching. On Linux,
it takes the patterns and tables from Brother's Linux package or installed driver into
`/usr/share/hl3070cw-native/data`; there are no profiles there. The colour tables are read out of
Brother's driver program file. None of Brother's files are part of this repository or its releases,
and Brother's Intel program is never run.

## For developers

On a Mac you need the Xcode command line tools (`xcode-select --install`). `make lint` also uses
shellcheck and, if it is installed, clang-tidy (`brew install shellcheck llvm`). On Linux, install
`build-essential libcups2-dev python3` for `make`, `make check` and `make dist`. The other commands
below are for a Mac.

```sh
make                 # build/rastertohl3070cw (on a Mac universal: arm64 + x86_64)
make check           # sanitizer build on made-up data: needs nothing of Brother's
                     # (Raspberry Pi OS: make check SANITIZE=undefined)
make lint            # clang-tidy or the Clang analyzer, shellcheck, cupstestppd
make test            # compare with checksums of Brother's output (needs Brother's data files, no Rosetta)
make oracle-test     # compare live with Brother's driver (needs it and Rosetta 2)
python3 -I tools/siblings.py           # the other printers against the same checksums (needs the same)
python3 -I tools/finecheck.py --real   # Fine: image and line-by-line comparison
                     # (exits 1: random colours differ slightly, see docs/FORMAT.md)
make pkg             # macOS: the installer package, in build/pkg/
make dist            # Linux: the release package for this processor, in build/dist/
./install.sh         # install from the source tree (asks for the admin password)
./install.sh --queue NAME                              # also switch printer queue NAME to the native driver
./install.sh --queue NAME --uri socket://192.0.2.10:9100   # create a queue
./install.sh --uninstall
```

Run the filter by hand on a CUPS raster file:

```sh
build/rastertohl3070cw 1 user title 1 "BRMonoColor=Mono" page.ras > page.prn
```

Repository layout:

- `src/`: the CUPS filter. `xl2hb.c` writes the printer language and compresses lines, `fine.c`
  compresses Fine lines, `halftone.c` and `color.c` turn pixels into toner dots, `fsutil.c` reads
  and writes files safely when copying Brother's data.
- `ppd/`: the PPD files, generated by `tools/genppd.py`: the native one for macOS, its Linux version
  in `ppd/linux/`, and the PostScript one for both systems. `siblings/` in both folders holds the
  other printers'. A new one goes into `SIBLINGS` in `tools/genppd.py`.
- `install.sh`, `uninstall.sh`: install from the source tree and uninstall, on a Mac.
- `install-linux.sh`: the Linux installer.
- `docker/`: the print server.
- `tests/print-server/`: attacks the print server's access rules from an allowed client, the proxy,
  an outsider and a program on the server's machine. GitHub runs it on every push to `main` and `dev`.
- `tests/linux-package.sh`: installs a Linux release package in a throwaway container, prints
  through CUPS and uninstalls it again. GitHub runs it for both processors.
- `tests/macos-package.sh`: the same for the Mac installer, on GitHub's build machines only.
- `packaging/`: the installer package (`make pkg`) and `add-brother-data.sh`.
- `tools/`: the Python tools used to work out and check the format: raster writer, PCL XL parser,
  band decoder, measurement scripts and the comparisons with Brother's driver.
- `tests/fixtures.sha256`: checksums of Brother's output for `make test` (for Fine jobs, of the
  decoded image). The outputs themselves contain Brother's halftone patterns and are kept out of the
  repository.
- `tools/selftest.py` and `tests/fine_lines.c`: `make check`. It runs the filter with
  AddressSanitizer and UndefinedBehaviorSanitizer on halftone tiles and colour tables it makes up
  itself, so it also works where Brother's driver is not installed, as on GitHub's build machines.
  It also tests cancelling and attacks the copying of Brother's data. After `make check`,
  `sudo python3 -I tools/selftest.py` adds the checks that only work as root.
- `docs/FORMAT.md`: the printer language.

Brother's driver is the reference for the tests, and it only runs under Rosetta 2. Work that needs
it, such as making the Fine compression match Brother's for the remaining lines, has to happen on
macOS 27 or earlier. `tools/finecheck.py` compares Fine output with Brother's line by line.

## Security

The driver reads print jobs from any user who may print, so it checks every page before it
allocates memory or writes anything, and refuses pages larger than the printer can print. It reads
its data files and the print job, writes the printer data, and does nothing else. On a Mac it runs
inside the sandbox macOS puts around printer drivers. Linux has no such sandbox: there the driver is
confined only by the unprivileged account CUPS runs it as (usually `lp`).

The installers and `add-brother-data.sh` run one step of the driver as root: copying Brother's
data. (The helper opens Brother's package as you and gives root no path that you could change.)
That step takes no paths from its command line, follows no symbolic links inside Brother's package and uses only
files that belong to root and are not writable by everyone.

The code has been reviewed for security problems by its authors, with sanitizer builds, damaged
input files and static analysis. Those reviews are not a guarantee: they missed flaws in that
copying step, which were found with CodeQL's help and fixed in 0.5.0, and flaws in the Docker print
server's access rules, fixed in 0.5.2. No outside party has audited the code. `make check` and
`make lint` repeat the tests. GitHub runs both on every push to `main` and `dev`, along with CodeQL,
which scans the Mac build.

Like Brother's driver, this one sends the title of the document and your user name to the
printer with every job, and the connection to the printer is not encrypted. Use the printer on a
network you trust.

A Secure Print PIN keeps a printout from people at the printer, not from people who can read the
network or use your computer. It travels to the printer unencrypted like the rest of the job. When a
job fails, CUPS writes the job's settings, the PIN included, into its log file
`/var/log/cups/error_log`. Every user of a Mac can read that file; on Debian and Ubuntu, root and
members of the `adm` group can. The Docker print server switches this logging off, unless you set
its `LOG_LEVEL` to `debug`.

To report a security problem, see [SECURITY.md](SECURITY.md).

## License and trademarks

The code in this repository is under the [MIT License](LICENSE).

Brother and HL-3070CW are trademarks of Brother Industries, Ltd. This project is independent and not
affiliated with or endorsed by Brother. Brother's software and data are not included; the installers
use your own copy of Brother's driver.
