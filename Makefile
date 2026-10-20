PREFIX    ?= /usr
BINDIR    ?= $(PREFIX)/bin
LIBDIR    ?= $(PREFIX)/lib/xcontrol
DATADIR   ?= $(PREFIX)/share/xcontrol
LOCALEDIR ?= $(PREFIX)/share/locale
LAYERDIR  ?= $(PREFIX)/share/vulkan/implicit_layer.d
BUILDDIR  ?= build
PYTHON    ?= python3

CFLAGS ?= -O2 -g
SHIM_CFLAGS = $(CFLAGS) -fPIC -fvisibility=hidden -Wall -Wextra
# the dlsym hook must compile to a tail jump (see gl_shim.c)
GL_CFLAGS = $(SHIM_CFLAGS) -foptimize-sibling-calls

PYFILES = $(wildcard xcontrol/*.py)
VERSION = $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' xcontrol/__init__.py)
LINGUAS = $(shell cat po/LINGUAS)
MOFILES = $(foreach l,$(LINGUAS),$(BUILDDIR)/locale/$(l)/LC_MESSAGES/xcontrol.mo)

all: $(BUILDDIR)/libxcontrol_gl.so $(BUILDDIR)/libVkLayer_xcontrol.so $(MOFILES) $(BUILDDIR)/xcontrol.desktop

$(BUILDDIR)/libxcontrol_gl.so: shim/gl_shim.c
	@mkdir -p $(BUILDDIR)
	$(CC) $(CPPFLAGS) $(GL_CFLAGS) $(LDFLAGS) -shared -o $@ $< -ldl -lpthread

$(BUILDDIR)/libVkLayer_xcontrol.so: shim/vk_layer.c
	@mkdir -p $(BUILDDIR)
	$(CC) $(CPPFLAGS) $(SHIM_CFLAGS) $(LDFLAGS) -shared -o $@ $< -lpthread

# ---- translations -----------------------------------------------------------
$(BUILDDIR)/locale/%/LC_MESSAGES/xcontrol.mo: po/%.po
	@mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

$(BUILDDIR)/xcontrol.desktop: data/xcontrol.desktop.in po/LINGUAS $(wildcard po/*.po)
	@mkdir -p $(BUILDDIR)
	msgfmt --desktop -d po --template $< -o $@

# Regenerate the template after changing user-visible strings.
pot:
	xgettext --from-code=UTF-8 -L Python -k_ -kN_ -kC_:1c,2 -kngettext:1,2 --add-comments=TRANSLATORS \
		--package-name=xcontrol --msgid-bugs-address=https://github.com/yourname/xcontrol/issues \
		-o po/xcontrol.pot $(sort $(PYFILES))
	xgettext -L Desktop -j -o po/xcontrol.pot data/xcontrol.desktop.in
	sed -i 's/^"Project-Id-Version: .*\\n"$$/"Project-Id-Version: xcontrol $(VERSION)\\n"/' po/xcontrol.pot

# Merge new strings into every translation (translators then fill them in).
update-po: pot
	for l in $(LINGUAS); do msgmerge -U --backup=none po/$$l.po po/xcontrol.pot; done

# Start a new language: make new-po LANG_CODE=es
new-po: pot
	msginit -i po/xcontrol.pot -o po/$(LANG_CODE).po -l $(LANG_CODE).UTF-8 --no-translator
	grep -qx '$(LANG_CODE)' po/LINGUAS || echo '$(LANG_CODE)' >> po/LINGUAS

# ---- install ----------------------------------------------------------------
install: all
	install -Dm755 $(BUILDDIR)/libxcontrol_gl.so $(DESTDIR)$(LIBDIR)/libxcontrol_gl.so
	install -Dm755 $(BUILDDIR)/libVkLayer_xcontrol.so $(DESTDIR)$(LIBDIR)/libVkLayer_xcontrol.so
	install -Dm755 data/xcontrol-edid-helper $(DESTDIR)$(LIBDIR)/xcontrol-edid-helper
	install -Dm755 data/xcontrol-module-helper $(DESTDIR)$(LIBDIR)/xcontrol-module-helper
	install -Dm755 data/xcontrol-user-helper $(DESTDIR)$(LIBDIR)/xcontrol-user-helper
	install -Dm755 data/xcontrol-locale-helper $(DESTDIR)$(LIBDIR)/xcontrol-locale-helper
	install -Dm755 data/xcontrol-power-helper $(DESTDIR)$(LIBDIR)/xcontrol-power-helper
	install -Dm755 data/xcontrol-controller-helper $(DESTDIR)$(LIBDIR)/xcontrol-controller-helper
	install -Dm644 data/70-xcontrol-controllers.rules $(DESTDIR)$(PREFIX)/lib/udev/rules.d/70-xcontrol-controllers.rules
	install -dm755 $(DESTDIR)$(PREFIX)/share/polkit-1/actions
	sed 's|@LIBDIR@|$(LIBDIR)|g' data/io.github.xcontrol.policy.in > $(DESTDIR)$(PREFIX)/share/polkit-1/actions/io.github.xcontrol.policy
	chmod 644 $(DESTDIR)$(PREFIX)/share/polkit-1/actions/io.github.xcontrol.policy
	install -dm755 $(DESTDIR)$(LAYERDIR)
	sed 's|@LIBDIR@|$(LIBDIR)|g' shim/VkLayer_xcontrol.json.in > $(DESTDIR)$(LAYERDIR)/VkLayer_xcontrol.json
	chmod 644 $(DESTDIR)$(LAYERDIR)/VkLayer_xcontrol.json
	install -dm755 $(DESTDIR)$(DATADIR)/xcontrol
	install -m644 $(PYFILES) $(DESTDIR)$(DATADIR)/xcontrol/
	sed -i -e 's|@LIBDIR@|$(LIBDIR)|g' -e 's|@LOCALEDIR@|$(LOCALEDIR)|g' $(DESTDIR)$(DATADIR)/xcontrol/paths.py
	$(PYTHON) -m compileall -q -d $(DATADIR)/xcontrol $(DESTDIR)$(DATADIR)/xcontrol
	install -dm755 $(DESTDIR)$(BINDIR)
	sed 's|@DATADIR@|$(DATADIR)|g' bin/xcontrol.in > $(DESTDIR)$(BINDIR)/xcontrol
	sed 's|@DATADIR@|$(DATADIR)|g' bin/xcontrol-run.in > $(DESTDIR)$(BINDIR)/xcontrol-run
	chmod 755 $(DESTDIR)$(BINDIR)/xcontrol $(DESTDIR)$(BINDIR)/xcontrol-run
	# old names (before the rename), so Steam launch options and login entries keep working
	ln -sf xcontrol $(DESTDIR)$(BINDIR)/mesa-panel
	ln -sf xcontrol-run $(DESTDIR)$(BINDIR)/mesa-panel-run
	install -Dm644 $(BUILDDIR)/xcontrol.desktop $(DESTDIR)$(PREFIX)/share/applications/xcontrol.desktop
	for l in $(LINGUAS); do \
		install -Dm644 $(BUILDDIR)/locale/$$l/LC_MESSAGES/xcontrol.mo \
			$(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES/xcontrol.mo; \
	done

check:
	$(PYTHON) tests/check_gettext.py
	$(PYTHON) tests/check_modelines.py
	$(PYTHON) tests/check_edid_override.py
	$(PYTHON) tests/check_override_status.py
	$(PYTHON) tests/check_output_names.py
	$(PYTHON) tests/check_launcher.py
	$(PYTHON) tests/check_output_props.py
	$(PYTHON) tests/check_input.py
	$(PYTHON) tests/check_ratbag.py
	$(PYTHON) tests/check_theming.py
	$(PYTHON) tests/check_sysinfo.py
	$(PYTHON) tests/check_kmods.py
	$(PYTHON) tests/check_module_helper.py
	$(PYTHON) tests/check_desktop.py
	$(PYTHON) tests/check_user_helper.py
	$(PYTHON) tests/check_preview.py
	$(PYTHON) tests/check_panel.py
	$(PYTHON) tests/check_i3.py
	$(PYTHON) tests/check_awake.py
	$(PYTHON) tests/check_notify.py
	$(PYTHON) tests/check_night.py
	$(PYTHON) tests/check_defaults.py
	$(PYTHON) tests/check_region.py
	$(PYTHON) tests/check_audio.py
	$(PYTHON) tests/check_power.py
	$(PYTHON) tests/check_pads.py
	$(PYTHON) tests/check_health.py
	$(PYTHON) tests/check_backup.py
	sh -n data/xcontrol-edid-helper
	sh -n data/xcontrol-module-helper
	sh -n data/xcontrol-user-helper
	sh -n data/xcontrol-locale-helper
	sh -n data/xcontrol-power-helper
	sh -n data/xcontrol-controller-helper
	for l in $(LINGUAS); do msgfmt --check -o /dev/null po/$$l.po; done

clean:
	rm -rf $(BUILDDIR)

.PHONY: all install clean pot update-po new-po check
