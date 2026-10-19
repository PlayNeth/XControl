"""Find installed Steam games (native and Flatpak installs)."""
import glob
import os
import re

ROOTS = [
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.steam/root",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
]

SKIP = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|Steam Runtime|SteamVR)", re.I)


def _libraries():
    seen, libs = set(), []
    for root in ROOTS:
        root = os.path.realpath(os.path.expanduser(root))
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        candidates = [root]
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                candidates += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', f.read())]
        except OSError:
            pass
        for c in candidates:
            c = os.path.realpath(c)
            if c not in seen and os.path.isdir(os.path.join(c, "steamapps")):
                seen.add(c)
                libs.append(c)
    return libs


def installed_games():
    games = {}
    for lib in _libraries():
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                with open(acf, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if not appid or not name or SKIP.match(name.group(1)):
                continue
            games[appid.group(1)] = name.group(1)
    return sorted(({"appid": a, "name": n} for a, n in games.items()), key=lambda g: g["name"].lower())
