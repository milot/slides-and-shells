UNAME_S := $(shell uname -s)
CC      ?= cc

ifeq ($(UNAME_S),Darwin)
  LIB    := libnoegress.dylib
  CFLAGS := -dynamiclib -O1 -Wall
  LDLIBS :=
else
  LIB    := libnoegress.so
  CFLAGS := -shared -fPIC -O1 -Wall
  # -ldl must come AFTER the source: GNU ld resolves libraries in order and
  # drops symbols nothing has referenced yet, so putting it first leaves
  # dlsym undefined. Harmless on glibc 2.34+, which folded dl into libc, and
  # a link error everywhere else.
  LDLIBS := -ldl
endif

.PHONY: all clean
all: $(LIB)

$(LIB): noegress.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

clean:
	rm -f libnoegress.dylib libnoegress.so
