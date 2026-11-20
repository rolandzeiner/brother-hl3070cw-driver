# Brother HL-3070CW driver for Apple Silicon Macs

[![Latest release](https://img.shields.io/github/v/release/rolandzeiner/brother-hl3070cw-driver?label=download)](https://github.com/rolandzeiner/brother-hl3070cw-driver/releases/latest)
![macOS 11 or newer](https://img.shields.io/badge/macOS-11%2B-blue)
![Apple Silicon and Intel](https://img.shields.io/badge/Apple%20Silicon%20%26%20Intel-native-green)
![Status: beta](https://img.shields.io/badge/status-beta-orange)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
[![vibe-coded](https://img.shields.io/badge/vibe-coded-ff69b4?logo=musicbrainz&logoColor=white)](https://en.wikipedia.org/wiki/Vibe_coding)

Keep printing on your Brother HL-3070CW colour laser printer with a current Mac.

Brother's own macOS driver for this printer contains a program for Intel processors. On Apple
Silicon Macs it only runs through Rosetta 2, which Apple keeps available only through macOS 27.
This project is an open-source replacement that runs natively on Apple Silicon and Intel Macs.
Black-and-white pages come out exactly as with Brother's driver, also in Fine quality, and colour
pages practically the same.

This project is not made or endorsed by Brother.

## Contents

- [Install](#install)
- [Add the printer](#add-the-printer)
- [Print](#print)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [What works](#what-works)
- [How it works](#how-it-works)
- [For developers](#for-developers)
- [Security](#security)
- [License and trademarks](#license-and-trademarks)

## Install

You need a Mac with macOS 11 Big Sur or newer and an administrator password. You do not need a
GitHub account or any developer tools.

### 1. Check for Brother's driver

The driver comes in two versions:

| | Brother HL-3070CW native | Brother HL-3070CW PostScript |
|---|---|---|
| Print quality | Same as Brother's driver | The printer renders the page itself; light greys and yellow come out weaker |
| Needs Brother's driver files on the Mac | Yes | No |

The native version uses some data files (halftone patterns, colour tables and colour profiles)
from Brother's own macOS driver for the HL-3070CW. If you have printed with this printer on this
Mac before, those files are almost certainly there already, and you can go on to step 2.

If not, install Brother's driver first:

1. Open Brother's [HL-3070CW download page](https://support.brother.com/g/b/downloadtop.aspx?c=us&lang=en&prod=hl3070cw_all).
   To see your country's version of the page, change the region at the top.
2. Choose **macOS** and your macOS version (or the newest one listed), then download and install
   the **Printer Driver**. This project was tested with Brother's package
   `Brother_PrinterDrivers_ColorLaser.pkg`, version 5.0.0. Only the data files from it are used;
   its Intel program is never run.

If Brother's page offers nothing for macOS, use the PostScript version of this driver. It works
without Brother's files.

### 2. Download the installer

Open the [latest release](https://github.com/rolandzeiner/brother-hl3070cw-driver/releases/latest).
Under **Assets**, click the file ending in `.pkg` (for example `HL3070CW-Driver-0.4.1.pkg`). It
goes to your Downloads folder.

### 3. Open the installer

Double-click the downloaded file. The first time, macOS refuses to open it:

> **"HL3070CW-Driver-0.4.1.pkg" Not Opened**
> Apple could not verify "HL3070CW-Driver-0.4.1.pkg" is free of malware that may harm your Mac or
> compromise your privacy.

macOS shows this for every installer that is not signed with a paid Apple developer certificate,
which this free project does not have. The package is the one built from this repository's code.
To open it anyway:

1. Click **Done**. Do not click **Move to Trash**.
2. Open **System Settings** and click **Privacy & Security** in the sidebar.
3. Scroll down to **Security**. There is a line saying that "HL3070CW-Driver-0.4.1.pkg" was
   blocked to protect your Mac. Click **Open Anyway** next to it. The button appears only for
   about an hour after you tried to open the file; if it is missing, double-click the file again
   first.
4. macOS asks once more: click **Open Anyway** and confirm with your password or Touch ID. The
   installer opens.

On macOS 14 Sonoma and older, right-clicking the file and choosing **Open** also works.

If you are comfortable with Terminal, this removes the download mark from the file instead, after
which a double-click opens it directly:

```sh
xattr -d com.apple.quarantine ~/Downloads/HL3070CW-Driver-0.4.1.pkg
```

### 4. Run the installer

Click through the installer and enter your administrator password when asked. It installs both
driver versions. If Brother's driver files are missing, it installs only the PostScript version.

### Updating

To update, download the newest installer and run it the same way. Printers you have already added
keep their settings. The installer gives them the new version's options (Print Quality came with
0.4.0), so you do not have to remove and add them again.

## Add the printer

macOS cannot change the driver of a printer that is already set up, so if your HL-3070CW is
already in the list, remove it first and add it again.

1. Open **System Settings** > **Printers & Scanners**.
2. If the HL-3070CW is listed, select it and click **Remove Printer** (or the **−** button).
3. Make sure the printer is switched on and connected to your network. Click **Add Printer, Scanner or Fax...**.
4. Select the HL-3070CW in the list.
   - If it does not appear, click the globe icon (**IP**). Enter the printer's IP address, set
     **Protocol** to **HP Jetdirect - Socket**, and leave **Queue** empty. The printer's own
     display shows its IP address in its network settings.
5. In **Use**, choose **Select Software...**, type `HL-3070CW` into the search field, select
   **Brother HL-3070CW native** (or **Brother HL-3070CW PostScript**) and click **OK**.
6. Click **Add**.

## Print

Print as usual. The printer's options are in the print dialog, in the section called
**Printer Options** or **Printer Features** depending on your macOS version:

- **Color / Mono**: *Auto* lets the printer decide, *Color* always prints in colour, *Mono* always
  in black and white. Choose *Mono* if a colour toner cartridge is empty: the printer refuses
  colour jobs then, but still prints black and white.
- **Print Quality**: *Normal* (600 dpi) or *Fine* (2400 dpi class), as in Brother's driver. Fine
  sends more data to the printer, so large pages take longer to start.
- **Color Mode**: *Normal*, *Vivid* or *None*, as in Brother's driver.
- **Improve Gray Color**, **Toner Save Mode** and **Improve Print Output** (less paper curl or
  better toner fixing) work as in Brother's driver.
- **Paper size**, **paper source** (tray or manual feed) and **media type** (plain, thin, thick,
  envelopes, labels and more) are in the usual places.

To make black and white the default, open the print dialog, set **Color / Mono** to **Mono** and
save the settings as a preset.

## Troubleshooting

**macOS says the installer cannot be opened.** See [step 3](#3-open-the-installer).

**"Brother HL-3070CW native" is not in the list of drivers.** Brother's driver files were not found
when you installed. Install Brother's driver ([step 1](#1-check-for-brothers-driver)) and run this
installer again. Until then, use **Brother HL-3070CW PostScript**.

**Print Quality is missing from the print dialog.** The printer was added with an older version of
this driver. Run the newest installer; it updates the printers that are already set up.

**Fine prints the same as Normal.** The files for Fine quality come from Brother's driver. If they
were not on the Mac when you installed, Fine jobs are printed in Normal quality. Install Brother's
driver ([step 1](#1-check-for-brothers-driver)) and run this installer again.

**The printer does not respond or jobs wait in the queue.** Check that the printer is switched on
and on the same network as the Mac. A job sent while the printer is off is printed once it is
switched on (macOS cancels it after three hours).

**The display shows "Replace Toner" and nothing prints.** One toner cartridge is empty. Print with
**Color / Mono** set to **Mono**, or replace the cartridge.

**Faint copies of text or images appear further down the page.** That is "ghosting", caused by an
old toner cartridge or drum unit, not by the driver.

**Something else.** [Open an issue](https://github.com/rolandzeiner/brother-hl3070cw-driver/issues)
and describe what you printed and what happened. A GitHub account is needed for that.

## Uninstall

1. Open **Terminal**: press Cmd+Space, type `Terminal` and press Return.
2. Paste this line, press Return and enter your password (it is not shown while you type):

   ```sh
   sudo /Library/Printers/HL3070CW-Native/uninstall.sh
   ```

3. Remove the printer in **System Settings** > **Printers & Scanners**, or add it again with a
   different driver.

## What works

| | Native driver | PostScript driver |
|---|---|---|
| Black and white | Identical to Brother's driver, byte for byte | The printer's own rendering |
| Colour | Brother's colour tables and halftones; about 99.96 % of all dots identical to Brother's driver | The printer's own rendering |
| Fine quality (2400 dpi class) | The same dots as Brother's driver (in colour: as above); the compressed data matches Brother's for about 95 % of lines | Not available |
| Paper sizes | All 22 of Brother's driver | All 22 |
| Tray and manual feed | Yes | Yes |
| Media types | All 11 | Not yet |
| Color / Mono / Auto, Color Mode, Improve Gray, Improve Print Output | Yes | Color / Mono only |
| Toner Save | Yes | Yes |

The driver has been tested with an HL-3070CW connected over Wi-Fi. Ethernet and USB should work the
same way but have not been tested.

Black-and-white pages have been printed on paper, in Normal and in Fine quality. Colour has so far
only been compared with the data Brother's driver produces, because the test printer's cyan
cartridge is empty. If a colour page looks wrong, please
[open an issue](https://github.com/rolandzeiner/brother-hl3070cw-driver/issues).

Like every macOS printer driver of this kind (Brother's included), it is a PPD-based driver. macOS 27
supports these fully. CUPS, the printing system inside macOS, has marked such drivers as deprecated
for future versions, so a later macOS release could need a different approach.

## How it works

The HL-3070CW expects pages in Brother's own printer language, called XL2HB: a few printer
commands (PJL and parts of HP's PCL XL) around compressed black-and-white bands for each of the four
toner colours. Brother never published this format. It was worked out by feeding test pages to
Brother's driver and decoding what came out, without disassembling Brother's code.
[docs/FORMAT.md](docs/FORMAT.md) describes the format in full.

The driver itself is a small program in C (`rastertohl3070cw`). macOS turns your document into an
image; the driver converts the image into Brother's halftone dots and compresses them the way the
printer expects.

The halftone patterns, colour tables and colour profiles are Brother's. The installer copies them
from Brother's driver on your Mac into the driver's own folder
(`/Library/Printers/HL3070CW-Native/data`), reading the colour tables out of Brother's driver
program file. None of Brother's files are part of this repository, and Brother's Intel program is
never run.

## For developers

You need the Xcode command line tools (`xcode-select --install`). `make lint` also uses
shellcheck and, if it is installed, clang-tidy (`brew install shellcheck llvm`).

```sh
make                 # build/rastertohl3070cw, a universal binary (arm64 + x86_64)
make check           # sanitizer build on made-up data: needs nothing of Brother's
make lint            # clang-tidy or the Clang analyzer, shellcheck, cupstestppd
make test            # compare with checksums of Brother's output (needs Brother's data files, no Rosetta)
make oracle-test     # compare live with Brother's driver (needs it and Rosetta 2)
python3 -I tools/finecheck.py --real   # Fine: image and line-by-line comparison
make pkg             # the installer package, in build/pkg/
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
  compresses Fine lines, `halftone.c` and `color.c` turn pixels into toner dots, `fsutil.c` writes
  files safely when copying Brother's data.
- `ppd/`: the two PPD files, generated by `tools/genppd.py`.
- `packaging/`: the installer package (`make pkg`).
- `tools/`: the Python tools used to work out and check the format: raster writer, PCL XL parser,
  band decoder, measurement scripts and the comparisons with Brother's driver.
- `tests/fixtures.sha256`: checksums of Brother's output for `make test` (for Fine jobs, of the
  decoded image). The outputs themselves contain Brother's halftone patterns and are kept out of the
  repository.
- `tools/selftest.py` and `tests/fine_lines.c`: `make check`. It runs the filter with
  AddressSanitizer and UndefinedBehaviorSanitizer on halftone tiles and colour tables it makes up
  itself, so it also works where Brother's driver is not installed, as on GitHub's build machines.
- `docs/FORMAT.md`: the printer language.

Brother's driver is the reference for the tests, and it only runs under Rosetta 2. Work that needs
it, such as making the Fine compression match Brother's for the remaining lines, has to happen on
macOS 27 or earlier. `tools/finecheck.py` compares Fine output with Brother's line by line.

## Security

The driver reads print jobs from any user who may print, so it checks every page before it
allocates memory or writes anything, and refuses pages larger than the printer can print. It runs
inside the sandbox macOS puts around printer drivers: it reads its data files and the print job,
writes the printer data, and does nothing else.

The code has been reviewed for security problems twice by its authors, with sanitizer builds,
damaged input files and static analysis, and the findings were fixed. No outside party has audited
it. `make check` and `make lint` repeat those tests, and GitHub runs both on every change.

Like Brother's driver, this one sends the title of the document and your macOS user name to the
printer with every job, and the connection to the printer is not encrypted. Use the printer on a
network you trust.

To report a security problem, see [SECURITY.md](SECURITY.md).

## License and trademarks

The code in this repository is under the [MIT License](LICENSE).

Brother and HL-3070CW are trademarks of Brother Industries, Ltd. This project is independent and not
affiliated with or endorsed by Brother. Brother's software and data are not included; the installer
uses the copy of Brother's driver that is installed on your Mac.
