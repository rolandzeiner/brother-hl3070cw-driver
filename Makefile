# Native CUPS filter for the Brother HL-3070CW, for macOS and Linux.
#
#   make            build/rastertohl3070cw: on macOS a universal binary (arm64 +
#                   x86_64), on Linux for the machine it is built on
#   make test       byte-for-byte checks against stored reference outputs
#                   (needs Brother's data files on this Mac)
#   make check      sanitizer build on made-up data: needs nothing of Brother's
#   make lint       static analysis of the C code, the scripts and the PPDs
#   make oracle-test  the same as test, live against Brother's filter (needs Rosetta)
#   make pkg        installer package in build/pkg/

VERSION  ?= 0.4.1
OS       := $(shell uname -s)
# -ffp-contract=off: no fused multiply-add, so the grey conversion rounds
# exactly like Brother's filter (see src/halftone.c).
CFLAGS   ?= -O2 -g
WARN     := -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion -Wformat=2 -Wstrict-prototypes \
            -Wmissing-prototypes -Wvla -Wno-deprecated-declarations
# The filter reads print data from any user who may print: stack protectors
# on every function with a buffer, and no uninitialised stack memory.
HARDEN   := -fstack-protector-strong -ftrivial-auto-var-init=zero -Werror=format-security
ifeq ($(OS),Darwin)
ARCHS    ?= -arch arm64 -arch x86_64
PLATFORM := -mmacosx-version-min=11.0
else
# Linux: POSIX and X/Open names (realpath) from the C library, and Debian's own hardening (fortified
# libc calls, a position-independent executable, read-only relocations)
ARCHS    ?=
PLATFORM := -D_XOPEN_SOURCE=700
HARDEN   += -D_FORTIFY_SOURCE=3 -fPIE
LDFLAGS  += -pie -Wl,-z,relro,-z,now
LDLIBS   += -lm
endif
BASE     := -std=c11 $(WARN) -ffp-contract=off $(PLATFORM) -DDRIVER_VERSION='"$(VERSION)"'
CFLAGS   += $(ARCHS) $(BASE) $(HARDEN)
LDLIBS   += -lcups

PKG_ID   := io.github.rolandzeiner.hl3070cw-driver

SRC      := src/rastertohl3070cw.c src/xl2hb.c src/fine.c src/halftone.c src/color.c src/fsutil.c
HDR      := src/xl2hb.h src/fine.h src/halftone.h src/color.h src/fsutil.h
BIN      := build/rastertohl3070cw

all: $(BIN)

$(BIN): $(SRC) $(HDR)
	@mkdir -p build
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(SRC) $(LDLIBS)
ifeq ($(OS),Darwin)
	# ad-hoc signature (no certificate) with the hardened runtime: no injected libraries, no debugger
	codesign --force --sign - --options runtime --identifier $(PKG_ID).filter $@
endif

# Checks without Brother's data: the filter with sanitizers and without
# Brother's paths, on made-up tiles and tables (tools/selftest.py).
# AddressSanitizer cannot start on Raspberry Pi OS (its kernel has a 39-bit
# address space); there: make check SANITIZE=undefined. CI runs both.
SANITIZE    ?= address,undefined
CHECK_FLAGS := -O1 -g -fsanitize=$(SANITIZE) -fno-sanitize-recover=all -fno-omit-frame-pointer $(BASE) \
               -DBROTHER_LUT_DIR='"/nonexistent/"' -DBROTHER_FILTER='"/nonexistent/filter"' -DHL3070CW_TEST_HOOKS

build/check/rastertohl3070cw: $(SRC) $(HDR)
	@mkdir -p build/check
	$(CC) $(CHECK_FLAGS) -o $@ $(SRC) $(LDLIBS) $(if $(filter Linux,$(OS)),-lm)

build/check/fine_lines: tests/fine_lines.c src/fine.c src/xl2hb.c $(HDR)
	@mkdir -p build/check
	$(CC) $(CHECK_FLAGS) -o $@ tests/fine_lines.c src/fine.c src/xl2hb.c

check: build/check/rastertohl3070cw build/check/fine_lines
	python3 -I tools/selftest.py

# clang-tidy (.clang-tidy) comes with LLVM (brew install llvm), not with Apple's
# tools; without it, the analyzer built into Apple's clang runs alone.
TIDY     ?= $(firstword $(shell command -v clang-tidy) $(wildcard /opt/homebrew/opt/llvm/bin/clang-tidy) \
            $(wildcard /usr/local/opt/llvm/bin/clang-tidy))
SCRIPTS  := install.sh install-linux.sh uninstall.sh packaging/postinstall

lint:
ifneq ($(TIDY),)
	$(TIDY) --quiet --warnings-as-errors='*' $(SRC) tests/fine_lines.c -- $(BASE) $(if $(filter Darwin,$(OS)),-isysroot $$(xcrun --show-sdk-path))
else
	for f in $(SRC) tests/fine_lines.c; do \
	  $(CC) --analyze -Xclang -analyzer-output=text -Xclang -analyzer-werror $(BASE) -o /dev/null $$f || exit 1; done
endif
	shellcheck $(SCRIPTS)
	for s in $(SCRIPTS); do /bin/bash -n $$s || exit 1; done
	# filters, profiles: the PPD names files of an installed driver, which a build machine has not got
	cupstestppd -W filters -W profiles -W translations ppd/hl3070cw-native.ppd ppd/hl3070cw-postscript.ppd \
	  ppd/linux/hl3070cw-native.ppd
	python3 -I tools/genppd.py --check
	python3 -I -m compileall -q tools

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
PKG      := build/pkg/HL3070CW-Driver-$(VERSION).pkg

pkg: $(PKG)

$(PKG): $(BIN) LICENSE Makefile ppd/hl3070cw-native.ppd ppd/hl3070cw-postscript.ppd uninstall.sh packaging/postinstall packaging/distribution.xml
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
	# one line per paragraph, so Installer's narrow licence pane wraps it cleanly
	awk 'BEGIN { RS = ""; ORS = "\n\n" } { gsub(/\n/, " "); print }' LICENSE > packaging/resources/LICENSE.txt
	productbuild --distribution packaging/distribution.xml --resources packaging/resources \
	  --package-path build/pkg --version $(VERSION) $(PKG)
	rm build/pkg/driver.pkg

clean:
	chmod -R u+w build/pkgroot 2>/dev/null || true
	rm -rf build

.PHONY: all test check lint oracle-test fixtures pkg clean
