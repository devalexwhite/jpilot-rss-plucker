# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Alex White

CC ?= cc
PKG_CONFIG ?= pkg-config
CFLAGS ?= -O2 -g
PROFILE ?= $(if $(JPILOT_HOME),$(JPILOT_HOME),$(HOME))/.jpilot
PLUGIN = libjpilot-rss-plucker.so

all: $(PLUGIN)

$(PLUGIN): plugin.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -Wall -Wextra -fPIC -shared $(LDFLAGS) -o $@ $< \
		$$($(PKG_CONFIG) --cflags --libs gtk+-3.0 libxml-2.0) -lpisock

install: $(PLUGIN)
	install -d "$(PROFILE)/plugins"
	install -m 644 $(PLUGIN) rss_plucker.py "$(PROFILE)/plugins"

clean:
	$(RM) $(PLUGIN)

.PHONY: all install clean
