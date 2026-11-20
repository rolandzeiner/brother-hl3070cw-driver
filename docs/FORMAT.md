# The XL2HB printer language of the Brother HL-3070CW

This is what the HL-3070CW expects from a host, as far as worked out by
black-box testing: synthetic pages went through Brother's own macOS filter
(`rastertobrother3040`, driver package 5.0.0), and its output was decoded
until every pixel could be accounted for. No Brother code was disassembled,
copied or redistributed.

Status: **600 dpi Mono and colour are implemented** in `src/`. Mono output is
byte-identical to Brother's; colour is byte-identical for colours on the edges
of Brother's colour-table cells, greys and black, and differs by one tone
level for about 7 % of other colours (see [Colour](#6-colour) and
[Verification](#verification)). The "Fine" mode is not worked out yet.

All multi-byte numbers in the band format are **big-endian**; everything in the
PCL XL layer is **little-endian** (PCL XL's `eBinaryLowByteFirst`).

## 1. Job structure

```
UEL @PJL header … @PJL ENTER LANGUAGE=XL2HB
) BROTHER XL2HB;1;0\n
PCL XL: BeginSession, OpenDataSource
        per page: BeginPage, SetPageOrigin, BeginImage, ReadImage…, EndImage, EndPage
        CloseDataSource, EndSession
UEL @PJL EOJ NAME="<title>"\n UEL
```

`UEL` is `ESC %-12345X`.

### PJL header (Mono)

```
ESC%-12345X@PJL \n                       (note the space)
@PJL SET HOLD=OFF
@PJL SET JOBNAME="<title>"
@PJL SET USERNAME="<user>"
@PJL JOB NAME="<title>"
@PJL PRINTLOG ITEM = 1,PRINTER
@PJL PRINTLOG ITEM = 2,<Day>,<d> <Mon> <yyyy> <h>:<m>:<s>     UTC, no zero padding: "Thu,1 Jan 2026 1:5:5"
@PJL PRINTLOG ITEM = 3,<user>
@PJL PRINTLOG ITEM = 4,Macintosh
@PJL SET STRINGCODESET=HPROMAN8
@PJL SET LOGINUSER="<user>"
@PJL SET ECONOMODE=OFF                   always OFF, toner save works through the halftone
@PJL SET RENDERMODE=GRAYSCALE            COLOR for colour jobs
@PJL SET COLORADAPT=OFF                  ON for Color/Mono = Auto
@PJL SET LESSPAPERCURL=OFF               ON for Improve Output = Reduce Paper Curl
@PJL SET FIXINTENSITYUP=OFF              ON for Improve Output = Improve Toner Fixing
@PJL SET APTMODE=OFF                     ON4 for the Fine (2400 dpi class) mode
@PJL SET RESOLUTION=600
@PJL ENTER LANGUAGE=XL2HB
```

Colour jobs also send `@PJL SET IMPROVEGRAY=ON` (its position and rules are
not checked yet). Lines end in `\n` only. Brother's filter cuts the title to
80 bytes and does not escape quotes; this driver also replaces `"` with `'`
and control characters with spaces.

### PCL XL operators

Byte sequences as Brother writes them. Attribute order and data types are
kept exactly as Brother sends them; whether the printer also accepts other
valid PCL XL encodings has not been tested.

| Operator | Attributes |
|---|---|
| BeginSession `41` | Measure ubyte 0 (`c0 00 f8 86`), UnitsPerMeasure uint16_xy 600,600 (`d1 58 02 58 02 f8 89`) |
| OpenDataSource `48` | SourceType ubyte 0, DataOrg ubyte 1 |
| BeginPage `43` | Orientation ubyte 0; MediaSource (`c1 e9 03` = uint16 1001 for tray 1, `c0 02` = ubyte 2 for manual feed); MediaSize (see below); MediaType ubyte_array (see below); SimplexPageMode ubyte 0 |
| SetPageOrigin `75` | PageOrigin sint16_xy 100,100 (the 12 pt margin at 600 dpi) |
| BeginImage `b0` | ColorMapping ubyte 0; ColorDepth ubyte 0 (1 bit; 1 = 2 bit in Fine mode); SourceWidth uint16; SourceHeight uint16; DestinationSize uint16_xy (same values); CommentData uint16_array of 23 (plane table, below); PageCopies uint16 1 |
| ReadImage `b1` | StartLine uint16; BlockHeight uint16; CompressMode ubyte 1; CommentData uint16 = plane (0 = K); then the band as embedded data: `fb <len>` below 256 bytes, else `fa <uint32 len>` |
| EndImage `b2` | none |
| EndPage `44` | PageCopies uint16 1 |
| CloseDataSource `49`, EndSession `42` | none |

**Page geometry.** The image covers the imageable area (every PPD size has
12 pt margins). SourceWidth = imageable width in pixels rounded up to a
multiple of 32; bytes per line = SourceWidth / 8; pixels past the real width
are 0. SourceHeight = ⌊imageable height in points × 600 / 72⌋; macOS rasters
can carry one more row, which is dropped.

**MediaSize.** A PCL XL code where one exists (ubyte), a name string (ubyte_array),
or a custom size in tenths of a millimetre (CustomMediaSize uint16_xy `f8 2f`,
then CustomMediaSizeUnits ubyte 2 `f8 30`):

| PPD size | Sent as |
|---|---|
| Letter, Legal, A4, Executive | 0, 1, 2, 3 |
| Com-10, Monarch, C5, DL | 6, 7, 8, 9 |
| JIS B5, ISO B5, Hagaki (Postcard), A5, A6 | 11, 12, 14, 16, 17 |
| 3x5, A4 Long, Folio, DL Long Edge, Envelope #4, Envelope MAX | strings `3x5`, `A4Long`, `Folio`, `DL Long Edge`, `Envelope #4`, `Envelope MAX` |
| A5 Long Edge, ISO B6, JIS B6 | custom 2097×1481, 1250×1758, 1280×1820 |

**MediaType** strings: Plain `dRegular`, Thin `dThin`, Thick `dThick`,
Thicker `dThick2`, Recycled `dRecycled`, Bond `dBond`, Envelopes `dEnvelopes`,
Env. Thin `dEnvthin`, Env. Thick `dEnvthick`, Postcard `dPostcard`, Label `dLabel`.

**Plane table** (BeginImage CommentData): `0, 3, colour, ` then for each plane
`p = 0..3`: `1, 5, p, 4, method << 8 | unit`. `colour` is 0 for Mono, 1 for
colour jobs. Planes are K, C, M, Y. Brother sends `0x020c, 0x0214, 0x040a,
0x020c` (method 2 with 12-pixel units for K and Y, 20 for C; method 4 with
10-pixel units for M). These unit widths look like the halftone cell widths,
so that halftoned areas compress as repeats.

## 2. Bands

One ReadImage carries one band of one plane:

```
u16  0x0004
u16  method << 8 | unit         e.g. 0x020c
u16  bytes per line
u16  rows in the band
u32  total band length (header and checksum included)
rows x:
  u16  length of the previous line's data (0 for the first)
  u16  length of this line's data
  data, padded with zeros to a multiple of 4
u16  length of the last line's data
u16  0
u8   checksum: the sum of all band bytes is 0 mod 256
```

The records form a doubly linked list. Brother's banding:

* each plane has its own bands; a band is a run of consecutive **non-blank**
  rows of that plane; blank rows are never sent,
  a page with no ink has BeginImage/EndImage and no ReadImage;
* a band is written as soon as it ends; when several planes' bands end on the
  same row they are written in the order C, M, Y, K;
* before adding a row, a new band starts once the band (12-byte header plus
  records so far) has reached **27000 bytes**.

## 3. Line compression

A line is cut into units of `unit` pixels (MSB first, the last unit padded with
0); every unit is a bit field of `unit` bits. Commands, all starting on a byte
boundary:

| Command | Encoding |
|---|---|
| repeat a unit *n* times | method 2: nibble `1rrr`; method 4: `1` + (15 − unit) count bits, so command plus unit are 16 bits. Then the unit. *n* = r + 1; at the maximum r, *n* = max + 1 + ext |
| literal, *n* ≥ 2 units | byte `01rrrrrr`, *n* = r + 2 (r = 63: *n* = 65 + ext), then *n* units, then pad to a byte |
| copy *n* units from back in the line | byte `00rrrrrr`, *n* = r + 1 (r = 63: *n* = 64 + ext); unit *i* = unit *i* − 2 in method 2, *i* − 4 in method 4 |

`ext` is an extension count that follows the command (for repeat: after the
unit, at the next byte boundary): bytes are added while they are `0xff`, the
first byte below `0xff` ends it (`ff 85` = 255 + 133). Units before the line
start read as 0 for a copy. Verified for method 2 with 12- and 20-pixel units
and method 4 with 8- and 10-pixel units, all four planes.

Examples, method 2 / 12-pixel units, 192 units per line:

```
88 00 f0 00 b7        pixel 0 set: repeat 0x800 x1, repeat 0x000 x(8+183)
40 12 34 56 f0 00 b6  literal 0x123 0x456, then 190 blank units
```

**Brother's encoder** (reproduced exactly by `xl_encode_line`): walk the units.
Method 2 emits a repeat when the next units repeat (run ≥ 2), otherwise a copy
when at least 2 units match the ones `distance` back, otherwise collects literal
units. Method 4 checks the copy first, then the repeat, even where the repeat
would be longer. A copy may reach before the line start (units read as 0), but
the first unit of a line is never a copy. A single literal unit is written as a
repeat ×1.

**Method 4.** Brother's filter picks method 4 (`0x0408` for every plane) for
about one job in five, at random, apparently from uninitialised memory. The
printer prints both. This driver always uses method 2.

## 4. Mono halftoning

Brother's filter receives RGB (8 bits per channel) and, in Mono mode, does:

```
grey  = lrint(0.299 R + 0.587 G + 0.114 B)        double precision, round half to even
level = tone_curve[255 - grey]                    256 entries, see src/halftone.c
dot   = tile[level][y mod 80][x mod 80]           tile anchored at the image origin
```

The tiles come from Brother's driver package:
`/Library/Printers/Brother/Brother LUT/0600-k_cache08.bin` (normal) and
`0600-k-TS_cache08.bin` (Toner Save). These "BRCD" files are
`"BRCD" "0\0" u16le width u16le height`, then 256 one-bit tiles (one per
toner level, `height` rows of ⌈width/8⌉ bytes, MSB first). The driver reads
them at run time; they are not part of this repository. The tone curve was
measured; 13 of its 256 entries could be either of two neighbouring levels,
which give identical tiles in both files.

## 5. Brother's non-deterministic output

Brother's filter output varies between runs of the same job:

* about 20 % of jobs use method 4 throughout (see above);
* about 5 % carry an extra `@PJL SET MANUALDPX=ON`, whatever the options.

The verification reruns Brother's filter until it produces the common variant.

## 6. Colour

ReadImage `CommentData` gives the plane (0 K, 1 C, 2 M, 3 Y). PJL:
`RENDERMODE=COLOR`, `COLORADAPT=ON` for Color/Mono = Auto, and
`@PJL SET IMPROVEGRAY=ON` after `APTMODE` when Improve Gray is on; the third
value of the plane table in BeginImage is 1.

**Halftone.** `0600-{k,c,m}_cache08.bin` hold 80 x 80 tiles,
`0600-y_cache08.bin` 24 x 24 tiles (`-TS` for Toner Save), all anchored at the
image origin. The tile index is the plane's level from the colour step.

**RGB → C, M, Y, K.** Brother's filter keeps 17 x 17 x 17 tables after names
such as `HL-30xxC 600dpi ImpGray=ON Ver1.01 (2011/03/29) Match Monitor` and
their terminating zero: nodes in R, G, B order (R slowest), four little-endian
u16 per node in the order C, M, Y, K. Color Mode Normal / Vivid / None selects
`Match Monitor` / `Vivid` / `None (Table Type)`, Improve Gray selects
`ImpGray=ON` / `OFF`; `CAPT` tables belong to the Fine mode. Enhance Black and
Toner Save do not change the table.

Interpolation is tetrahedral (Kuhn split: sort the in-cell fractions), with
nodes every 16 input steps (255 counts as 256) and the result rounded half up.
The weights behave like 12-bit fixed point: in 1/4096 of a cell
W(f) = 256 f + e(f), e = 0 at f = 4, 8, 12, small integers elsewhere,
e(16 - f) = -e(f). Fitted tables (in `src/color.c`) reproduce every measured
point with one channel between nodes. Points with two or three channels between
nodes fit no model found: on random colours 93 % come out exact and the others
one level off in one plane, which makes 0.03-0.04 % of all dots differ.
Finding the exact arithmetic would mean reading Brother's code, which this
project does not do.

## Verification

* `make test` compares the filter with checksums of 45 outputs of Brother's
  filter (`tests/fixtures.sha256`; inputs are regenerated from fixed seeds):
  dots, random black/white pages on A6 and A4, all 256 greys, 1500 random
  colours in Mono, Toner Save, Improve Output, manual feed, media types, all
  22 paper sizes, multi-page jobs, title and user, and in colour: table-edge
  colours in every colour option, greys and black content. Works without
  Rosetta. The outputs themselves contain Brother's halftone patterns and are
  not in the repository; `make fixtures` keeps them in `tests/fixtures-local/`.
* `make oracle-test` runs the same against Brother's filter live, plus a
  smooth gradient and real text documents rendered by macOS (A4, Letter, A5,
  3.5 MB each). Needs Brother's driver and Rosetta 2.
* `tools/colorcheck.py` reports how many dots differ for arbitrary colours.
* `tools/roundtrip.py` checks the decoder (`tools/xl2hb.py`) on random pages.

## Open points

* **Fine (2400 dpi class).** `APTMODE=ON4`, ColorDepth 1 (2 bits per pixel),
  plane table entries `12, 0`, band header `0x000c`, `capt-*` halftone files and
  `CAPT` colour tables. Format not worked out.
* **Colour interpolation** with two or three channels between nodes (above).
* **Enhance Black Printing** changed nothing in any test so far.
* **The printer also has PCL, PCL XL and BR-Script 3 (PostScript 3)
  interpreters** (SNMP `prtInterpreterTable`). This project's PostScript PPD
  uses BR-Script 3; a PostScript page wrapped in `@PJL SET RENDERMODE=GRAYSCALE`
  / `@PJL ENTER LANGUAGE=POSTSCRIPT` prints correctly in Mono.
