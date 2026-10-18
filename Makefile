PREFIX    ?= /usr
BINDIR    ?= $(PREFIX)/bin
LIBDIR    ?= $(PREFIX)/lib/mesa-panel
DATADIR   ?= $(PREFIX)/share/mesa-panel
LOCALEDIR ?= $(PREFIX)/share/locale
LAYERDIR  ?= $(PREFIX)/share/vulkan/implicit_layer.d
BUILDDIR  ?= build
PYTHON    ?= python3

CFLAGS ?= -O2 -g
SHIM_CFLAGS = $(CFLAGS) -fPIC -fvisibility=hidden -Wall -Wextra
# the dlsym hook must compile to a tail jump (see gl_shim.c)
GL_CFLAGS = $(SHIM_CFLAGS) -foptimize-sibling-calls

PYFILES = $(wildcard mesa_panel/*.py)
VERSION = $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' mesa_panel/__init__.py)
LINGUAS = $(shell cat po/LINGUAS)
MOFILES = $(foreach l,$(LINGUAS),$(BUILDDIR)/locale/$(l)/LC_MESSAGES/mesa-panel.mo)

all: $(BUILDDIR)/libmesapanel_gl.so $(BUILDDIR)/libVkLayer_mesa_panel.so $(MOFILES) $(BUILDDIR)/mesa-panel.desktop

$(BUILDDIR)/libmesapanel_gl.so: shim/gl_shim.c
	@mkdir -p $(BUILDDIR)
	$(CC) $(CPPFLAGS) $(GL_CFLAGS) $(LDFLAGS) -shared -o $@ $< -ldl -lpthread

$(BUILDDIR)/libVkLayer_mesa_panel.so: shim/vk_layer.c
	@mkdir -p $(BUILDDIR)
	$(CC) $(CPPFLAGS) $(SHIM_CFLAGS) $(LDFLAGS) -shared -o $@ $< -lpthread

# ---- translations -----------------------------------------------------------
$(BUILDDIR)/locale/%/LC_MESSAGES/mesa-panel.mo: po/%.po
	@mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

$(BUILDDIR)/mesa-panel.desktop: data/mesa-panel.desktop.in po/LINGUAS $(wildcard po/*.po)
	@mkdir -p $(BUILDDIR)
	msgfmt --desktop -d po --template $< -o $@

# Regenerate the template after changing user-visible strings.
pot:
	xgettext --from-code=UTF-8 -L Python -k_ -kN_ -kngettext:1,2 --add-comments=TRANSLATORS \
		--package-name=mesa-panel --msgid-bugs-address=https://github.com/yourname/mesa-panel/issues \
		-o po/mesa-panel.pot $(sort $(PYFILES))
	xgettext -L Desktop -j -o po/mesa-panel.pot data/mesa-panel.desktop.in
	sed -i 's/^"Project-Id-Version: .*\\n"$$/"Project-Id-Version: mesa-panel $(VERSION)\\n"/' po/mesa-panel.pot

# Merge new strings into every translation (translators then fill them in).
update-po: pot
	for l in $(LINGUAS); do msgmerge -U --backup=none po/$$l.po po/mesa-panel.pot; done

# Start a new language: make new-po LANG_CODE=es
new-po: pot
	msginit -i po/mesa-panel.pot -o po/$(LANG_CODE).po -l $(LANG_CODE).UTF-8 --no-translator
	grep -qx '$(LANG_CODE)' po/LINGUAS || echo '$(LANG_CODE)' >> po/LINGUAS

# ---- install ----------------------------------------------------------------
install: all
	install -Dm755 $(BUILDDIR)/libmesapanel_gl.so $(DESTDIR)$(LIBDIR)/libmesapanel_gl.so
	install -Dm755 $(BUILDDIR)/libVkLayer_mesa_panel.so $(DESTDIR)$(LIBDIR)/libVkLayer_mesa_panel.so
	install -Dm755 data/mesa-panel-edid-helper $(DESTDIR)$(LIBDIR)/mesa-panel-edid-helper
	install -dm755 $(DESTDIR)$(LAYERDIR)
	sed 's|@LIBDIR@|$(LIBDIR)|g' shim/VkLayer_mesa_panel.json.in > $(DESTDIR)$(LAYERDIR)/VkLayer_mesa_panel.json
	chmod 644 $(DESTDIR)$(LAYERDIR)/VkLayer_mesa_panel.json
	install -dm755 $(DESTDIR)$(DATADIR)/mesa_panel
	install -m644 $(PYFILES) $(DESTDIR)$(DATADIR)/mesa_panel/
	sed -i -e 's|@LIBDIR@|$(LIBDIR)|g' -e 's|@LOCALEDIR@|$(LOCALEDIR)|g' $(DESTDIR)$(DATADIR)/mesa_panel/paths.py
	$(PYTHON) -m compileall -q -d $(DATADIR)/mesa_panel $(DESTDIR)$(DATADIR)/mesa_panel
	install -dm755 $(DESTDIR)$(BINDIR)
	sed 's|@DATADIR@|$(DATADIR)|g' bin/mesa-panel.in > $(DESTDIR)$(BINDIR)/mesa-panel
	sed 's|@DATADIR@|$(DATADIR)|g' bin/mesa-panel-run.in > $(DESTDIR)$(BINDIR)/mesa-panel-run
	chmod 755 $(DESTDIR)$(BINDIR)/mesa-panel $(DESTDIR)$(BINDIR)/mesa-panel-run
	install -Dm644 $(BUILDDIR)/mesa-panel.desktop $(DESTDIR)$(PREFIX)/share/applications/mesa-panel.desktop
	for l in $(LINGUAS); do \
		install -Dm644 $(BUILDDIR)/locale/$$l/LC_MESSAGES/mesa-panel.mo \
			$(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES/mesa-panel.mo; \
	done

check:
	$(PYTHON) tests/check_gettext.py
	$(PYTHON) tests/check_modelines.py
	$(PYTHON) tests/check_edid_override.py
	$(PYTHON) tests/check_override_status.py
	$(PYTHON) tests/check_output_names.py
	sh -n data/mesa-panel-edid-helper
	for l in $(LINGUAS); do msgfmt --check -o /dev/null po/$$l.po; done

clean:
	rm -rf $(BUILDDIR)

.PHONY: all install clean pot update-po new-po check
