# Default Apps

Which program opens links, email links, folders, text files, pictures, videos, music, PDFs,
archives and office documents, saved in `~/.config/mimeapps.list` (what xdg-open, browsers and
file managers read). Picking a program for a group sets it for every type in the group it can
open. **Every file type** lists all types with a program, searchable, to change any one. The
page also cleans up entries pointing to programs that are no longer installed, warns when
`$BROWSER` overrides the browser, and makes your own launchers in `~/.local/share/applications`
(AppImages, Wine, Steam games) count by refreshing their `mimeinfo.cache`, which nothing else does.

**Terminal**: there's no standard for it, so the choice goes to `~/.config/xdg-terminals.list`
(xdg-terminal-exec, which GLib uses for programs that run in a terminal), and XControl's i3
config uses it for the terminal key instead of i3-sensible-terminal.
