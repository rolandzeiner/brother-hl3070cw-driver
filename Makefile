# Native CUPS filter for the Brother HL-3070CW.
#
#   make            universal binary (arm64 + x86_64) in build/
#   make test       byte-for-byte checks against stored reference outputs
#   make oracle-test  the same live against Brother's filter (needs Rosetta)

VERSION  ?= 0.2.0-dev
ARCHS    ?= -arch arm64 -arch x86_64
CC       ?= clang
# -ffp-contract=off: no fused multiply-add, so the grey conversion rounds
# exactly like Brother's filter (see src/halftone.c).
CFLAGS   ?= -O2 -g
CFLAGS   += $(ARCHS) -std=c11 -Wall -Wextra -Wpedantic -Wno-deprecated-declarations \
            -ffp-contract=off -mmacosx-version-min=11.0 -DDRIVER_VERSION='"$(VERSION)"'
LDLIBS   += -lcups

SRC      := src/rastertohl3070cw.c src/xl2hb.c src/halftone.c src/color.c src/fsutil.c
HDR      := src/xl2hb.h src/halftone.h src/color.h src/fsutil.h
BIN      := build/rastertohl3070cw

all: $(BIN)

$(BIN): $(SRC) $(HDR)
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $(SRC) $(LDLIBS)

# Compare with the stored reference outputs (works without Rosetta).
test: $(BIN)
	python3 -I tools/fixtures.py check

# Compare live against Brother's filter, real macOS-rendered documents included.
oracle-test: $(BIN)
	python3 -I tools/jobcheck.py --real

# Regenerate tests/fixtures.sha256 from Brother's filter (needs Rosetta).
fixtures: $(BIN) build/faketime.dylib
	python3 -I tools/fixtures.py make

build/faketime.dylib: tools/faketime.c
	@mkdir -p build
	$(CC) -arch x86_64 -dynamiclib -o $@ $<

clean:
	rm -rf build

.PHONY: all test oracle-test fixtures clean
