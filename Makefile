# Native CUPS filter for the Brother HL-3070CW.
#
#   make            universal binary (arm64 + x86_64) in build/
#   make test       byte-for-byte checks against stored reference outputs
#   make oracle-test  the same live against Brother's filter (needs Rosetta)
#   make pkg        installer package in build/pkg/

VERSION  ?= 0.3.0
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

# Installer package for users: build/pkg/HL3070CW-Driver-$(VERSION).pkg (unsigned).
PKG_ID   := io.github.rolandzeiner.hl3070cw-driver
PKG      := build/pkg/HL3070CW-Driver-$(VERSION).pkg

pkg: $(PKG)

$(PKG): $(BIN) ppd/hl3070cw-native.ppd ppd/hl3070cw-postscript.ppd uninstall.sh packaging/postinstall packaging/distribution.xml
	chmod -R u+w build/pkgroot 2>/dev/null || true
	rm -rf build/pkgroot build/pkgscripts build/pkg
	mkdir -p build/pkgroot/Library/Printers/HL3070CW-Native build/pkgroot/Library/Printers/PPDs/Contents/Resources build/pkgscripts build/pkg
	install -m 755 $(BIN) build/pkgroot/Library/Printers/HL3070CW-Native/rastertohl3070cw
	install -m 755 uninstall.sh build/pkgroot/Library/Printers/HL3070CW-Native/uninstall.sh
	install -m 644 ppd/hl3070cw-native.ppd "build/pkgroot/Library/Printers/PPDs/Contents/Resources/Brother HL-3070CW native.ppd"
	install -m 644 ppd/hl3070cw-postscript.ppd "build/pkgroot/Library/Printers/PPDs/Contents/Resources/Brother HL-3070CW PostScript.ppd"
	install -m 755 packaging/postinstall build/pkgscripts/postinstall
	# folder modes as macOS has them, so the package changes none of them
	chmod 755 build/pkgroot/Library build/pkgroot/Library/Printers/PPDs build/pkgroot/Library/Printers/PPDs/Contents \
	  build/pkgroot/Library/Printers/PPDs/Contents/Resources build/pkgroot/Library/Printers/HL3070CW-Native
	chmod 555 build/pkgroot/Library/Printers
	pkgbuild --root build/pkgroot --scripts build/pkgscripts --identifier $(PKG_ID) --version $(VERSION) \
	  --install-location / --ownership recommended build/pkg/driver.pkg
	cp LICENSE packaging/resources/LICENSE.txt
	productbuild --distribution packaging/distribution.xml --resources packaging/resources \
	  --package-path build/pkg --version $(VERSION) $(PKG)
	rm build/pkg/driver.pkg

clean:
	chmod -R u+w build/pkgroot 2>/dev/null || true
	rm -rf build

.PHONY: all test oracle-test fixtures pkg clean
