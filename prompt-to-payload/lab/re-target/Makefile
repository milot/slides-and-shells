# vulnbox - workshop RE target
#
# Deliberately compiled without hardening so the bugs are reachable and the
# disassembly stays legible. Never reuse these flags for anything real.

UNAME_S := $(shell uname -s)

CC      ?= cc
CFLAGS  := -O0 -g -fno-stack-protector -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 \
           -Wall -Wno-deprecated-declarations
BUILD   := build
DIST    := dist
SRC     := src/vulnbox.c

ifeq ($(UNAME_S),Darwin)
  STRIP_CMD := strip -x -S
else
  STRIP_CMD := strip --strip-all
  CFLAGS    += -no-pie -z execstack
endif

.PHONY: all stripped clean verify

all: $(BUILD)/vulnbox $(DIST)/vulnbox

# Symboled build. Kept for comparison during the talk, never given to the model.
$(BUILD)/vulnbox: $(SRC) | $(BUILD)
	$(CC) $(CFLAGS) -o $@ $<

# The artifact the model actually analyses.
#
# Deliberately emitted into its own directory. A .dSYM bundle or a symboled
# sibling in the same folder is enough for r2, lldb and Ghidra to recover the
# names we just stripped, which would silently hand the model the answers.
$(DIST)/vulnbox: $(BUILD)/vulnbox | $(DIST)
	cp $< $@
	$(STRIP_CMD) $@

$(BUILD) $(DIST):
	mkdir -p $@

# Proves the three bugs are reachable in this build before it goes on stage.
verify: all
	@./verify.sh

clean:
	rm -rf $(BUILD) $(DIST)
