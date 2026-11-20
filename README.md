# Brother HL-3070CW driver for Apple Silicon

A native macOS (arm64 + x86_64) CUPS driver for the Brother HL-3070CW colour laser printer.

Brother's own macOS driver for this printer ships an Intel-only filter (`rastertobrother3040`)
that runs through Rosetta 2. Apple keeps Rosetta generally available only through macOS 27,
so the printer would stop working on later macOS versions. This project replaces that filter
with an open, native one.

## Status

**Work in progress, not packaged yet.**

| | |
|---|---|
| Mono, 600 dpi | done: output is byte-identical to Brother's filter, printed on a real HL-3070CW |
| All 22 paper sizes, tray / manual feed, media types, Toner Save, Improve Output | done (Mono) |
| Colour | next |
| Fine (2400 dpi class) | later |
| PPD and installer package | later |

## How it works

The printer speaks Brother's host-based "XL2HB" language: PJL plus a small subset of HP's
documented PCL XL, carrying 1-bit K/C/M/Y bands in an undocumented compression format. That
format was worked out by black-box testing against Brother's own filter and is described in
[docs/FORMAT.md](docs/FORMAT.md). No Brother code is used or redistributed.

The halftone patterns are Brother's: the driver reads them at run time from Brother's driver
package, which therefore stays installed (its data files work without Rosetta; only its filter
does not).

## Building and testing

```sh
make            # build/rastertohl3070cw, universal binary
make test       # compare with stored outputs of Brother's filter (no Rosetta needed)
make oracle-test  # compare live with Brother's filter (needs its driver and Rosetta 2)
```

Run the filter by hand on a CUPS raster file:

```sh
build/rastertohl3070cw 1 user title 1 "BRMonoColor=Mono" page.ras > page.prn
```

## Repository layout

- `src/`: the CUPS filter (C): job writer and line encoder (`xl2hb.c`), halftoning (`halftone.c`)
- `tools/`: Python tools used to work out and check the format: raster writer, PCL XL parser,
  band decoder and encoder, measurement scripts, byte-for-byte comparison with Brother's filter
- `tests/fixtures/`: reference outputs of Brother's filter for `make test`
- `docs/FORMAT.md`: the printer language

## License

MIT. Brother and HL-3070CW are trademarks of Brother Industries, Ltd. This project is not
affiliated with or endorsed by Brother.
