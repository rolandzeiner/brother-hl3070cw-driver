# The XL2HB printer language of the Brother HL-3070CW

This is what the HL-3070CW expects from a host, as far as worked out by
black-box testing: synthetic pages went through Brother's own macOS filter
(`rastertobrother3040`, driver package 5.0.0), and its output was decoded
until every pixel could be accounted for. No Brother code was disassembled,
copied or redistributed.

Status: **600 dpi Mono and colour and the Fine mode are implemented** in
`src/`. Mono output at 600 dpi is byte-identical to Brother's; colour is
byte-identical for colours on the edges of Brother's colour-table cells, greys
and black, and differs by one tone level for about 7 % of other colours (see
[Colour](#6-colour) and [Verification](#verification)). Fine prints exactly
Brother's dots (colour: as at 600 dpi); its line compression is fully decoded,
and a model of Brother's encoder writes about 95 % of lines byte for byte like
Brother's (see [Fine](#7-fine-600x2400-dpi-class)).

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

Colour jobs also send `@PJL SET IMPROVEGRAY=ON` and `@PJL SET
UCRGCRFORIMAGE=ON` (see [Colour](#6-colour)).

**Secure Print.** A job with a PIN replaces `@PJL SET HOLD=OFF` with five
lines; the printer then keeps the job until the PIN is entered on its panel:

```
@PJL SET COLLATE=OFF
@PJL COPIES=1                            no SET, as Brother writes it
@PJL SET HOLD=STORE
@PJL SET HOLDTYPE=PRIVATE
@PJL SET HOLDKEY=<PIN>                   4 digits
```

`JOBNAME` and `USERNAME` that follow are what the panel lists. Brother's
filter takes the PIN and both names from its own print dialog extension
(`com.brother.print.PrintSettings.secureprint`, `password`, and `username` /
`jobname` as arrays of character codes), and only together with Brother's
PPD; without the names it crashes. A PIN that is not 4 characters long makes
it print the job without one. The printer's PJL variables allow HOLDKEY 0 to
9999 (`@PJL INFO VARIABLES`). This driver takes the PIN from the job's IPP
`job-password` and refuses any PIN other than 4 digits. Lines end in `\n` only. Brother's filter cuts the title to
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
| BeginImage `b0` | ColorMapping ubyte 0; ColorDepth ubyte 0 (1 bit; 1 = 4 bit in Fine mode); SourceWidth uint16; SourceHeight uint16; DestinationSize uint16_xy (same values); CommentData uint16_array of 23 (plane table, below); PageCopies uint16 1 |
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

### Custom paper

A paper that is not one of the printer's sizes goes as `CustomMediaSize` in
tenths of a millimetre (`CustomMediaSizeUnits` 2). Brother's filter takes the
header's integer `PageSize` (points) and truncates twice: down to whole 1/120
inch, then down to whole tenths, `floor(floor(pt * 120 / 72) * 254 / 120)`
(all 685 values measured between 198 and 1152 pt). 100 x 250 mm, 283 x 708 pt,
goes as 996 x 2497. The range is the one of Brother's PPD: 198-612 x 328-1152
pt.

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
grey  = 0.299 R + 0.587 G + 0.114 B               double precision (no fused multiply-add),
        rounded to the nearest integer,           exact halves rounded down
level = tone_curve[255 - grey]                    256 entries, see src/halftone.c
dot   = tile[level][y mod 80][x mod 80]           tile anchored at the image origin
```

The tiles come from Brother's driver package:
`/Library/Printers/Brother/Brother LUT/0600-k_cache08.bin` (normal) and
`0600-k-TS_cache08.bin` (Toner Save). These "BRCD" files are
`"BRCD" "0\0" u16le width u16le height`, then 256 one-bit tiles (one per
toner level, `height` rows of ⌈width/8⌉ bytes, MSB first). The driver reads
them at run time; they are not part of this repository. The tone curve was
measured; 13 of its 256 entries could be either of two neighbouring levels
with identical 600 dpi tiles, and the Fine tiles settle five of them.

Ties: 528 colours whose grey is exactly k + 0.5 in double precision all went
to k wherever the two levels' tiles differ (Fine and 600 dpi alike), for odd
and even k. Rounding half to even, which the first version used, agrees only
where k is even.

## 5. Brother's non-deterministic output

Brother's filter output varies between runs of the same job:

* about 20 % of jobs use method 4 throughout (see above);
* about 5 % carry an extra `@PJL SET MANUALDPX=ON`, whatever the options.

The verification reruns Brother's filter until it produces the common variant.

## 6. Colour

ReadImage `CommentData` gives the plane (0 K, 1 C, 2 M, 3 Y). PJL:
`RENDERMODE=COLOR`, `COLORADAPT=ON` for Color/Mono = Auto, and
`@PJL SET IMPROVEGRAY=ON` after `APTMODE` when Improve Gray is on, then
`@PJL SET UCRGCRFORIMAGE=ON` when Enhance Black Printing is on (Color and Auto,
at 600 dpi and in Fine; never in Mono), both right before `RESOLUTION`; the
third value of the plane table in BeginImage is 1. Enhance Black changes
nothing in the image data; the printer acts on the PJL line.

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

## 7. Fine (600x2400 dpi class)

Print Quality = Fine (`BRResolution=600x2400dpi`) keeps the 600 x 600 dpi
raster but sends **4 bits per pixel**, values 0 to 15 (the tiles below only
use 0, 2, 4, ..., 14 and 15). Two pixels per byte, the first in the high
nibble. Brother's Fine output does not vary between runs (neither method 4
nor `MANUALDPX`).

**Job.** `@PJL SET APTMODE=ON4` instead of `OFF`. BeginImage: ColorDepth 1
(`e4Bit`); SourceWidth = image width rounded up to a multiple of 8 pixels
(not 32); plane table entries `1, 5, p, 12, 0` instead of `1, 5, p, 4,
method/unit`. Everything else is as at 600 dpi, including the banding (one band
per plane and run of non-blank rows, 27000-byte limit).

**Bands.** Same layout as at 600 dpi with header `u16 0x000c`, `u16 0`,
bytes per line (= width / 2), rows, total length. Lines use the scheme below.

**Halftone.** `capt-{k,c,m,y}[-TS]_cache08.bin`, BRCD files with `"1\0"` as
version: one byte per pixel, the value in the low nibble; the width field
counts bits, so K and Y tiles are 12 x 12 pixels and C and M 20 x 20. Anchored
at the image origin; value = `tile[level][y mod h][x mod w]`. Mono uses the
grey and tone curve of section 4, colour the `CAPT` tables (same names with
`CAPT` in place of `600dpi`) with the interpolation of section 6. Measured:
every grey in Mono and Toner Save; table-edge colours in every colour option
identical; arbitrary colours 0.04 % of pixels off, as at 600 dpi.

### Fine lines

A line is a sequence of one-byte **tokens**, each standing for whole bytes of
the line, and **headers** that repeat tokens. `V[q]` = 2, 4, 6, 8, 10, 12, 14,
15 for q = 0..7.

| Token | Bytes |
|---|---|
| `0001 c kkk` | k+1 bytes `00` (c = 0) or `FF` (c = 1) |
| `0010 k qqq` | k+1 bytes `00`, then (V[q], F) |
| `0011 k qqq` | k+1 bytes `00`, then (0, V[q]) |
| `01 hhh qqq` | (2h, V[q]) |
| `100 kk qqq` | k+1 bytes `FF`, then (2q, 0) |
| `101 kk qqq` | k bytes `00`, then (V[q], 0) |
| `110 kk qqq` | k bytes `FF`, then (F, 2q) |
| `111 kk qqq` | k+1 bytes `FF`, then (2q, F) |

(a, b) is one byte with a in the high nibble.

Headers are `0000 xxx1`, a count byte (with 0xFF extension bytes as in
section 3: `ff ff ff fd` = 1018) and then tokens. With n = count + offset:

| Header | Offset | Meaning |
|---|---|---|
| `03 c X` | 6 | X repeated n times |
| `07 c X Y` | 5 | X Y repeated n times |
| `0f c X Y Z` | 3 | X Y Z repeated n times |
| `09 c X t1 .. tn` | 4 | X t1 X t2 ... X tn |
| `0b c X t1 .. t2n` | 4 | X t1 t2 X t3 t4 ... |
| `0d c X Y t1 .. tn` | 3 | X Y t1 X Y t2 ... |

Brother never repeats more than 1024 times in one header. A line encodes all
its bytes; the decoder (`tools/xl2hb_fine.py`) reproduces every line of
Brother's output tested (over 60 000).

**Brother's tokens** (exact on every line tested): runs of `00` and `FF` go
out in tokens of 8 bytes, the remainder last. A byte with a partial nibble
takes in run bytes in front of it, as many as its token allows (`101`: 3
zeros, `0011` and `0010`: 2, `110`: 3 `FF`, `100` and `111`: 4), the rest of
the run going out before it. Special cases: an `FF` after a zero run is
written as `0010 k 111` only after one or two zeros, otherwise it starts an FF
run; `FF..FF 00` becomes one `100 kk 000` token only when the whole FF run
fits (up to 4).

**Brother's choice of headers** is a greedy left-to-right pass that always
takes the longest repeat of the kind it picks. This model (`encode_tokens` in
`tools/xl2hb_fine.py`, ported to `src/fine.c`) matches 99 % of the lines of a
macOS-rendered text page, 94 % of a smooth gradient and 93 % of colour
patches:

1. A run of 12 or more equal tokens: `03`.
2. Otherwise the first of `0f`, `07`, `09`, `0d`, `0b` that covers 12 tokens
   or more (`07` never for two equal tokens). For `0b` Brother also looks two
   tokens further and moves there if that saves as many bytes or more.
3. Otherwise, at a run of 6 to 11 equal tokens, `0f` from 3 repeats.
4. Otherwise the first of `0f`, `07`, `0d`, `09`, `0b` that fits decides. At
   3, 5, 3, 4, 4 or more periods it is written, except when the token two
   places on starts a run of 3 or more (then step 5) or the run here is 6 or
   longer (then it counts as a near miss). A near miss (`0f`, `07`, `0d` from
   2 periods, `09` from 3) goes out as literals: all the tokens it would have
   covered.
5. Otherwise a run of 3 or more equal tokens as literals, or one token.

The remaining differences are in this choice, never in what is printed;
`tools/finecheck.py` lists them per case.

## Verification

* `make test` compares the filter with checksums of 65 outputs of Brother's
  filter (`tests/fixtures.sha256`; inputs are regenerated from fixed seeds):
  dots, random black/white pages on A6 and A4, all 256 greys, 1500 random
  colours in Mono, Toner Save, Improve Output, manual feed, media types, all
  22 paper sizes, multi-page jobs, title and user, and in colour: table-edge
  colours in every colour option, greys and black content; Secure Print and
  Enhance Black; three custom paper sizes; and twelve Fine jobs in Mono and colour. Fine checksums cover what is printed (the job without
  its band encoding, plus every decoded row, `tools/fineimage.py`), the others
  the bytes. Works without Rosetta. The outputs themselves contain Brother's
  halftone patterns and are not in the repository; `make fixtures` keeps them
  in `tests/fixtures-local/`.
* `make oracle-test` runs the same against Brother's filter live, plus a
  smooth gradient and real text documents rendered by macOS (A4, Letter, A5,
  3.5 MB each). Needs Brother's driver and Rosetta 2.
* `make check` needs nothing of Brother's: the filter, built with
  AddressSanitizer and UndefinedBehaviorSanitizer, runs on made-up tiles and
  tables (`tools/selftest.py`). Black-and-white pages must decode to what went
  in, at 600 dpi and in Fine; all paper sizes must give jobs that parse;
  damaged print data and data files must end in an error message; and the C
  Fine encoder must write what `tools/xl2hb_fine.py` writes.
* `tools/colorcheck.py` reports how many dots differ for arbitrary colours.
* `tools/finecheck.py` compares Fine jobs with Brother's: image, frame and the
  share of lines encoded alike.
* `tools/roundtrip.py` checks the decoder (`tools/xl2hb.py`) on random pages.

## Open points

* **Fine header choice** for the lines the model in section 7 gets wrong
  (about 5 %). They print correctly; only the bytes differ.
* **Colour interpolation** with two or three channels between nodes (above).
* **The printer also has PCL, PCL XL and BR-Script 3 (PostScript 3)
  interpreters** (SNMP `prtInterpreterTable`). This project's PostScript PPD
  uses BR-Script 3; a PostScript page wrapped in `@PJL SET RENDERMODE=GRAYSCALE`
  / `@PJL ENTER LANGUAGE=POSTSCRIPT` prints correctly in Mono.
