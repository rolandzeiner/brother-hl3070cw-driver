# Brother HL-3070CW driver for Apple Silicon

A native macOS (arm64 + x86_64) CUPS driver for the Brother HL-3070CW colour laser printer.

Brother's own macOS driver for this printer ships an Intel-only filter (`rastertobrother3040`)
that runs through Rosetta 2. Apple keeps Rosetta generally available only through macOS 27,
so the printer would stop working on later macOS versions. This project replaces that filter
with an open, native one.

**Status: work in progress, not usable yet.** Step one, the mono driver, is being built.

## How it works

The printer speaks Brother's host-based "XL2HB" language: PJL plus a small subset of HP's
documented PCL XL, carrying 1-bit C/M/Y/K bands in an undocumented compression format.
That format was worked out by black-box testing against Brother's own filter; it is
described in [docs/FORMAT.md](docs/FORMAT.md). No Brother code is used or redistributed.

## Repository layout

- `tools/`: Python tools used to work out and check the format (raster writer, PCL XL parser,
  band decoder, round-trip checker against Brother's filter)
- `src/`: the native CUPS filter (C)
- `ppd/`: the PPD file
- `tests/`: fixtures and tests

## License

MIT. Brother and HL-3070CW are trademarks of Brother Industries, Ltd. This project is not
affiliated with or endorsed by Brother.
