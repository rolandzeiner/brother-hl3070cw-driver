"""Generate the PPD files in ppd/.

    python3 -I tools/genppd.py

ppd/hl3070cw-native.ppd        raster driver: this project's filter, Brother quality
ppd/hl3070cw-postscript.ppd    the printer's own PostScript (BR-Script 3), no filter
ppd/linux/hl3070cw-native.ppd  the raster driver for Linux: the filter from CUPS's
                               filter folder, no ICC profiles (Brother's Linux
                               driver has none); the PostScript PPD serves both
ppd/siblings/, ppd/linux/siblings/
                               the raster driver for the printers with the same
                               Brother engine and filter (tools/siblings.py
                               compares them). Untested on hardware, no fax.

The texts are English with German translations (*de., in UTF-8, as CUPS wants
them).
Option keywords and choices follow Brother's own PPD, so presets and saved
lpoptions keep working when a queue switches drivers.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))



def makefile_version() -> str:
    """The driver version: the one place it is written down is the Makefile."""
    with open(os.path.join(ROOT, "Makefile"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("VERSION"):
                return line.split("=", 1)[1].strip()
    raise ValueError("no VERSION in the Makefile")


VERSION = makefile_version()

# Brother's model (MDL) of the printers that share the HL-3070CW's filter,
# tables and profiles (cupsModelNumber 3). Their PostScript PPDs are not made:
# two of them have no BR-Script, and none was tested.
SIBLINGS = ["HL-3040CN series", "HL-3045CN series", "HL-3075CW series", "DCP-9010CN", "MFC-9010CN", "MFC-9120CN",
            "MFC-9125CN", "MFC-9320CW", "MFC-9325CW"]
CUSTOM = (198, 328.32, 612, 1152)  # points: narrowest, shortest, widest, longest, as in Brother's PPD

GERMAN_OPTIONS = {
    "PageSize": "Papierformat", "PageRegion": "Papierformat", "InputSlot": "Papierquelle", "MediaType": "Druckmedium",
    "BRResolution": "Druckqualität", "BRMonoColor": "Farbe / Einfarbig", "BRColorMatching": "Farbmodus",
    "BRGray": "Graustufen verbessern", "BREnhanceBlkPrt": "Schwarzdruck verbessern",
    "TonerSaveMode": "Tonersparmodus", "BRImproveOutput": "Druckergebnis verbessern",
}
GERMAN = {  # English choice text -> German; what is not here reads the same in both
    "A5 Long Edge": "A5 lange Kante", "DL Envelope": "DL-Umschlag", "C5 Envelope": "C5-Umschlag",
    "Com-10 Envelope": "Com-10-Umschlag", "Monarch Envelope": "Monarch-Umschlag", "A4 Long": "A4 lang",
    "DL Long Edge": "DL lange Kante", "Envelope #4": "Umschlag Nr. 4", "Envelope MAX": "Umschlag MAX",
    "Tray 1": "Kassette 1", "Manual Feed": "Manuelle Zufuhr",
    "Plain Paper": "Normalpapier", "Thin Paper": "Dünnes Papier", "Thick Paper": "Dickes Papier",
    "Thicker Paper": "Dickeres Papier", "Bond Paper": "Briefpapier", "Envelopes": "Umschläge",
    "Env. Thick": "Umschläge, dick", "Env. Thin": "Umschläge, dünn", "Recycled Paper": "Recyclingpapier",
    "Label": "Etiketten", "Postcard": "Postkarte",
    "Normal (600 x 600 dpi)": "Normal (600 x 600 dpi)", "Fine (2400 dpi class)": "Fein (2400-dpi-Klasse)",
    "Auto": "Automatisch", "Color": "Farbe", "Mono": "Einfarbig", "Vivid": "Lebendig", "None": "Keiner",
    "On": "Ein", "Off": "Aus", "Reduce Paper Curl": "Papierwellung verringern",
    "Improve Toner Fixing": "Tonerfixierung verbessern",
}
DRIVER_DIR = "/Library/Printers/HL3070CW-Native"
MARGIN = 12  # points, all sides

# keyword, display name, width, height (points)
SIZES = [
    ("A4", "A4", 595, 842),
    ("Letter", "Letter", 612, 792),
    ("Legal", "Legal", 612, 1008),
    ("Executive", "Executive", 522, 756),
    ("A5", "A5", 420, 595),
    ("A5Rotated", "A5 Long Edge", 595, 420),
    ("A6", "A6", 297, 420),
    ("ISOB5", "B5 (ISO)", 499, 709),
    ("ISOB6", "B6 (ISO)", 355, 499),
    ("B5", "B5 (JIS)", 516, 729),
    ("B6", "B6 (JIS)", 363, 516),
    ("EnvDL", "DL Envelope", 312, 624),
    ("EnvC5", "C5 Envelope", 459, 649),
    ("Env10", "Com-10 Envelope", 297, 684),
    ("EnvMonarch", "Monarch Envelope", 279, 540),
    ("3x5", "3 x 5", 216, 360),
    ("210x405mm", "A4 Long", 595, 1148),
    ("FanFoldGermanLegal", "Folio", 612, 936),
    ("EnvPRC5Rotated", "DL Long Edge", 624, 312),
    ("Postcard", "Hagaki", 284, 419),
    ("EnvYou4", "Envelope #4", 298, 666),
    ("EnvChou3", "Envelope MAX", 340, 666),
]

MEDIA_TYPES = [  # keyword, display, cupsMediaType, the printer's own name (BR-Script, PJL MEDIATYPE)
    ("Plain", "Plain Paper", 0, "REGULAR"), ("Thin", "Thin Paper", 1, "THIN"), ("Thick", "Thick Paper", 2, "THICK"),
    ("Thicker", "Thicker Paper", 3, "THICK2"), ("BOND", "Bond Paper", 6, "BOND"), ("Env", "Envelopes", 7, "ENVELOPES"),
    ("EnvThick", "Env. Thick", 9, "ENVTHICK"), ("EnvThin", "Env. Thin", 8, "ENVTHIN"),
    ("Recycled", "Recycled Paper", 5, "RECYCLED"), ("Label", "Label", 11, "LABEL"), ("PostCard", "Postcard", 10, "POSTCARD"),
]


def header(model: str, nick: str, short: str, pcfile: str, product: str = "HL-3070CW series",
           device_id: str = "MFG:Brother;CMD:PJL,PCL,PCLXL;MDL:HL-3070CW series;CLS:PRINTER;") -> list[str]:
    return [
        '*PPD-Adobe: "4.3"',
        f"*% Generated by tools/genppd.py, brother-hl3070cw-driver {VERSION}. MIT licence.",
        "*% Not made or endorsed by Brother. Brother and HL-3070CW are trademarks of Brother Industries, Ltd.",
        '*FormatVersion: "4.3"',
        f'*FileVersion: "{VERSION}"',
        "*LanguageVersion: English",
        "*LanguageEncoding: ISOLatin1",
        f'*PCFileName: "{pcfile}"',
        '*Manufacturer: "Brother"',
        f'*Product: "({product})"',
        f'*ModelName: "{model}"',
        f'*ShortNickName: "{short}"',
        f'*NickName: "{nick}"',
        f'*1284DeviceID: "{device_id}"',
        '*PSVersion: "(3010.000) 0"',
        '*LanguageLevel: "3"',
        "*ColorDevice: True",
        "*DefaultColorSpace: RGB",
        "*FileSystem: False",
        '*Throughput: "20"',
        "*LandscapeOrientation: Plus90",
        "*TTRasterizer: Type42",
        "*cupsVersion: 2.3",
        "*cupsManualCopies: True",
        '*cupsLanguages: "en de"',
    ]


def page_sizes() -> list[str]:
    out = ["*OpenUI *PageSize/Media Size: PickOne", "*OrderDependency: 10 AnySetup *PageSize", "*DefaultPageSize: A4"]
    for k, name, w, h in SIZES:
        out.append(f'*PageSize {k}/{name}: "<</PageSize[{w} {h}]/ImagingBBox null>>setpagedevice"')
    out += ["*CloseUI: *PageSize", "",
            "*OpenUI *PageRegion/Media Size: PickOne", "*OrderDependency: 10 AnySetup *PageRegion", "*DefaultPageRegion: A4"]
    for k, name, w, h in SIZES:
        out.append(f'*PageRegion {k}/{name}: "<</PageSize[{w} {h}]/ImagingBBox null>>setpagedevice"')
    out += ["*CloseUI: *PageRegion", "", "*DefaultImageableArea: A4"]
    for k, name, w, h in SIZES:
        out.append(f'*ImageableArea {k}/{name}: "{MARGIN} {MARGIN} {w - MARGIN} {h - MARGIN}"')
    out += ["", "*DefaultPaperDimension: A4"]
    for k, name, w, h in SIZES:
        out.append(f'*PaperDimension {k}/{name}: "{w} {h}"')
    return out


def custom_size() -> list[str]:
    """Paper of the user's own size, within the printer's range."""
    w0, h0, w1, h1 = CUSTOM
    return ["", "*VariablePaperSize: True", "*LeadingEdge Short: \"\"", "*DefaultLeadingEdge: Short",
            f'*MaxMediaWidth: "{w1}"', f'*MaxMediaHeight: "{h1}"', f"*HWMargins: {MARGIN} {MARGIN} {MARGIN} {MARGIN}",
            "*NonUIOrderDependency: 10 AnySetup *CustomPageSize",
            '*CustomPageSize True: "pop pop pop <</PageSize[5 -2 roll]/ImagingBBox null>>setpagedevice"',
            f"*ParamCustomPageSize Width: 1 points {w0} {w1}", f"*ParamCustomPageSize Height: 2 points {h0} {h1}",
            "*ParamCustomPageSize WidthOffset: 3 points 0 0", "*ParamCustomPageSize HeightOffset: 4 points 0 0",
            "*ParamCustomPageSize Orientation: 5 int 0 3"]


def german(lines: list[str]) -> list[str]:
    """*de. lines for every option and choice in lines."""
    out, option = ["*% German"], None
    for line in lines:
        opened = re.match(r"\*(?:JCL)?OpenUI \*(\w+)/", line)
        if opened:
            option = opened.group(1)
            out.append(f'*de.Translation {option}/{GERMAN_OPTIONS[option]}: ""')
        elif line.startswith(("*CloseUI", "*JCLCloseUI")):
            option = None
        elif option:
            choice = re.match(rf"\*{option} ([^/]+)/([^:]+):", line)
            if choice:
                out.append(f'*de.{option} {choice.group(1)}/{GERMAN.get(choice.group(2), choice.group(2))}: ""')
    if any(line.startswith("*CustomPageSize") for line in lines):
        out.append('*de.PageSize Custom/Eigenes Format: ""')
        for key, text in (("Width", "Breite"), ("Height", "Höhe"), ("WidthOffset", "Versatz in der Breite"),
                          ("HeightOffset", "Versatz in der Höhe"), ("Orientation", "Ausrichtung")):
            out.append(f'*de.ParamCustomPageSize {key}/{text}: ""')
    return out


def pick_one(keyword: str, text: str, order: int, default: str, choices: list[tuple[str, str, str]],
             section: str = "AnySetup", jcl: bool = False) -> list[str]:
    o = "*JCLOpenUI" if jcl else "*OpenUI"
    c = "*JCLCloseUI" if jcl else "*CloseUI"
    out = [f"{o} *{keyword}/{text}: PickOne", f"*OrderDependency: {order} {section} *{keyword}", f"*Default{keyword}: {default}"]
    for k, name, code in choices:
        out.append(f'*{keyword} {k}/{name}: "{code}"')
    out.append(f"{c}: *{keyword}")
    return out


def fonts() -> list[str]:
    return ["*DefaultFont: Courier",
            '*Font Courier: Standard "(002.004S)" Standard ROM',
            '*Font Helvetica: Standard "(001.006S)" Standard ROM',
            '*Font Times-Roman: Standard "(001.007S)" Standard ROM']


def native(linux: bool = False, sibling: str | None = None) -> str:
    pd = lambda key, val: f"<</{key} {val}>>setpagedevice"  # noqa: E731
    if sibling:
        name = sibling.removesuffix(" series")
        lines = header(f"Brother {name} native", f"Brother {name}, native driver (open source, untested)",
                       f"{name} native", name[0] + name.replace("-", "")[-6:] + "N.PPD", sibling,
                       f"MFG:Brother;MDL:{sibling};")
        lines.append("*% Untested on hardware: printer data as for the HL-3070CW, which Brother's filter writes for it too")
    else:
        lines = header("Brother HL-3070CW native", "Brother HL-3070CW, native driver (open source)",
                       "HL-3070CW native", "HL3070NA.PPD")
    lines += [
        # Linux: a bare name, found in CUPS's own filter folder (/usr/lib/cups/filter)
        f'*cupsFilter: "application/vnd.cups-raster 0 {"" if linux else DRIVER_DIR + "/"}rastertohl3070cw"',
        "*% Secure Print: the print dialog's \"Print with PIN\", a PIN of 4 digits",
        '*cupsJobPassword: "1111"',
        "",
    ]
    if not linux:
        lines += [
            "*% macOS colour matching with Brother's ICC profiles (copied into the driver folder at install)",
            "*cupsICCQualifier2: BRGray",
            "*cupsICCQualifier3: BRResolution",
            f'*cupsICCProfile RGB../Normal: "{DRIVER_DIR}/data/profiles/broch08_PL_NM_IG_ON.icm"',
            f'*cupsICCProfile .ON.600dpi/Normal, Improve Gray: "{DRIVER_DIR}/data/profiles/broch08_PL_NM_IG_ON.icm"',
            f'*cupsICCProfile .OFF.600dpi/Normal: "{DRIVER_DIR}/data/profiles/broch08_PL_NM.icm"',
            f'*cupsICCProfile .ON.600x2400dpi/Fine, Improve Gray: "{DRIVER_DIR}/data/profiles/broch08_PL_Fi_IG_ON.icm"',
            f'*cupsICCProfile .OFF.600x2400dpi/Fine: "{DRIVER_DIR}/data/profiles/broch08_PL_Fi.icm"',
            "",
        ]
    lines += ["*DefaultResolution: 600dpi"]
    raster = "/HWResolution[600 600]/cupsColorOrder 0/cupsColorSpace 1/cupsBitsPerColor 8"
    lines += pick_one("BRResolution", "Print Quality", 10, "600dpi",
                      [("600dpi", "Normal (600 x 600 dpi)", f"<<{raster}/cupsInteger4 0>>setpagedevice"),
                       ("600x2400dpi", "Fine (2400 dpi class)", f"<<{raster}/cupsInteger4 1>>setpagedevice")])
    lines += [""] + page_sizes() + custom_size() + [""]
    lines += pick_one("InputSlot", "Paper Source", 20, "Tray1",
                      [("Tray1", "Tray 1", "<</ManualFeed false/MediaPosition 1>>setpagedevice"),
                       ("Manual", "Manual Feed", "<</ManualFeed true/MediaPosition 4>>setpagedevice")])
    lines += [""] + pick_one("MediaType", "Media Type", 20, "Plain",
                             [(k, n, pd("cupsMediaType", v)) for k, n, v, _ in MEDIA_TYPES])
    lines += [""] + pick_one("BRMonoColor", "Color / Mono", 20, "Auto",
                             [("Auto", "Auto", pd("cupsInteger3", 0)), ("FullColor", "Color", pd("cupsInteger3", 1)),
                              ("Mono", "Mono", pd("cupsInteger3", 2))])
    lines += [""] + pick_one("BRColorMatching", "Color Mode", 20, "Normal",
                             [("Normal", "Normal", pd("cupsInteger5", 0)), ("Vivid", "Vivid", pd("cupsInteger5", 1)),
                              ("None", "None", pd("cupsInteger5", 2))])
    lines += [""] + pick_one("BRGray", "Improve Gray Color", 20, "ON",
                             [("OFF", "Off", pd("cupsInteger6", 2)), ("ON", "On", pd("cupsInteger6", 1))])
    lines += [""] + pick_one("BREnhanceBlkPrt", "Enhance Black Printing", 20, "OFF",
                             [("OFF", "Off", pd("cupsInteger7", 0)), ("ON", "On", pd("cupsInteger7", 1))])
    lines += [""] + pick_one("TonerSaveMode", "Toner Save Mode", 20, "OFF",
                             [("OFF", "Off", pd("cupsInteger1", 0)), ("ON", "On", pd("cupsInteger1", 1))])
    lines += [""] + pick_one("BRImproveOutput", "Improve Print Output", 20, "OFF",
                             [("OFF", "Off", pd("cupsInteger2", 0)),
                              ("BRLessPaperCurl", "Reduce Paper Curl", pd("cupsInteger2", 1)),
                              ("BRFixIntensity", "Improve Toner Fixing", pd("cupsInteger2", 2))])
    lines += [""] + german(lines)
    if linux:
        lines += [""] + airprint_presets()
    lines += [""] + fonts()
    return "\n".join(lines) + "\n"


def airprint_presets() -> list[str]:
    """How CUPS maps the standard IPP choices of AirPrint / IPP Everywhere
    clients (print-color-mode x print-quality) onto this PPD's options. Only
    in the Linux PPD: shared from a print server, clients see no PPD options.
    Colour means Brother's Auto (the printer decides per page); draft quality
    is Toner Save, best quality is Fine."""
    lines = ["*% AirPrint / IPP Everywhere: print-color-mode x print-quality -> options"]
    for mode, colour, text in (("monochrome", "Mono", "Black and White"), ("color", "Auto", "Color")):
        for quality, extra, qtext in (("low", "*BRResolution 600dpi *TonerSaveMode ON", "Draft"),
                                      ("mid", "*BRResolution 600dpi", "Normal"),
                                      ("high", "*BRResolution 600x2400dpi", "Best")):
            name = f"{'Gray' if mode == 'monochrome' else 'Color'}_{qtext}"
            lines.append(f'*APPrinterPreset {name}/{text}, {qtext}: "*BRMonoColor {colour} {extra} '
                         f'com.apple.print.preset.graphicsType General com.apple.print.preset.quality {quality} '
                         f'com.apple.print.preset.output-mode {mode}"')
    return lines


def postscript() -> str:
    pjl = lambda s: f"@PJL SET {s}<0A>"  # noqa: E731
    lines = header("Brother HL-3070CW BR-Script", "Brother HL-3070CW, PostScript (BR-Script 3)",
                   "HL-3070CW PostScript", "HL3070PS.PPD")
    lines += [
        '*JCLBegin: "<1B>%-12345X@PJL JOB<0A>"',
        '*JCLToPSInterpreter: "@PJL ENTER LANGUAGE=POSTSCRIPT<0A>"',
        '*JCLEnd: "<1B>%-12345X@PJL EOJ<0A><1B>%-12345X"',
        # CUPS writes the user name into PJL's DISPLAY text without cleaning its quotes, so a
        # client's user name could add to the PJL command; "none" leaves DISPLAY out
        '*cupsPJLDisplay: "none"',
        "",
    ]
    lines += pick_one("BRMonoColor", "Color / Mono", 10, "FullColor",
                      [("FullColor", "Color", pjl("RENDERMODE=COLOR")), ("Mono", "Mono", pjl("RENDERMODE=GRAYSCALE"))],
                      section="JCLSetup", jcl=True)
    lines += [""] + pick_one("TonerSaveMode", "Toner Save Mode", 10, "OFF",
                             [("OFF", "Off", pjl("ECONOMODE=OFF")), ("ON", "On", pjl("ECONOMODE=ON"))],
                             section="JCLSetup", jcl=True)
    lines += [""] + page_sizes() + [""]
    lines += pick_one("InputSlot", "Paper Source", 20, "Tray1",
                      [("Tray1", "Tray 1", "<</ManualFeed false>>setpagedevice"),
                       ("Manual", "Manual Feed", "<</ManualFeed true>>setpagedevice")])
    # the native PPD's keywords, so presets carry over; the code is what Brother's BR-Script PPD sends
    lines += [""] + pick_one("MediaType", "Media Type", 20, "Plain",
                             [(k, n, f"<</MediaType ({ps})>>setpagedevice") for k, n, _, ps in MEDIA_TYPES])
    lines += [""] + german(lines)
    lines += [""] + fonts()
    return "\n".join(lines) + "\n"


def main() -> int:
    """Write the PPD files; with --check only report whether they are up to date."""
    check = sys.argv[1:] == ["--check"]
    stale = 0
    os.makedirs(os.path.join(ROOT, "ppd"), exist_ok=True)
    files = [("hl3070cw-native.ppd", native()), ("hl3070cw-postscript.ppd", postscript()),
             ("linux/hl3070cw-native.ppd", native(linux=True))]
    for model in SIBLINGS:
        slug = model.removesuffix(" series").lower().replace("-", "")
        files += [(f"siblings/{slug}-native.ppd", native(sibling=model)),
                  (f"linux/siblings/{slug}-native.ppd", native(linux=True, sibling=model))]
    for name, text in files:
        path = os.path.join(ROOT, "ppd", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if check:
            if not os.path.exists(path):
                print(f"{path} is missing: run python3 -I tools/genppd.py")
                stale = 1
                continue
            with open(path, encoding="utf-8") as f:
                if f.read() != text:
                    print(f"{path} is out of date: run python3 -I tools/genppd.py")
                    stale = 1
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote", path)
    return stale


if __name__ == "__main__":
    sys.exit(main())
