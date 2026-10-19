"""3D preview: math, geometry, textures and how settings map to what's drawn (no GL needed)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.pop("DISPLAY", None)
from xcontrol import preview3d as P  # noqa: E402

bad = 0


def expect(what, got, want):
    global bad
    if got != want:
        bad += 1
        print(f"FAIL {what}: got {got!r}, want {want!r}")


ident = P.translate(0, 0, 0)
m = P.mat_mul(P.translate(1, 2, 3), P.rotate(90, 0, 0, 1))
expect("identity", P.mat_mul(ident, m) == m, True)
expect("rotate then translate", tuple(round(c, 6) for c in P.apply(m, (1, 0, 0))), (1.0, 3.0, 3.0))
cam = P.mat_mul(P.translate(0, -1.0, -25.0), P.mat_mul(P.rotate(8, 1, 0, 0), P.rotate(-18, 0, 1, 0)))
eye = P.apply(P.mat_mul(P.rotate(18, 0, 1, 0), P.rotate(-8, 1, 0, 0)), (0.0, 1.0, 25.0))
expect("eye maps to the camera origin", tuple(round(abs(c), 5) for c in P.apply(cam, eye)), (0.0, 0.0, 0.0))
pr = P.perspective(90, 1, 1, 100)
expect("perspective", (round(pr[0], 6), pr[11]), (1.0, -1))

g = P.gear(1.0, 4.0, 1.0, 20, 0.7)
expect("gear is triangles", len(g) % 3, 0)
expect("gear triangle count", len(g) // 3, 20 * (2 * 4 + 4 * 2 + 4 * 2))
expect("unit normals", all(abs(sum(c * c for c in v[3:6]) - 1) < 1e-6 for v in g), True)
expect("plane", len(P.plane([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], (2, 2), (0, 0, 1))), 6)
expect("checker texture size", len(P.checker_texture(64, 4)), 64 * 64 * 4)
fence = P.fence_texture(32, 2)
alphas = {fence[i] for i in range(3, len(fence), 4)}
expect("fence has holes and wires", alphas, {0, 255})


class Fake:  # just the settings logic, without a window
    settings = {"msaa": 0, "af": 0, "traa": "off", "fps_limit": 0}
    _effective = P.Preview3D._effective


f = Fake()
f.settings = {"msaa": 0, "af": 0, "traa": "supersample", "fps_limit": 0}
expect("app decides: nothing forced, no TRAA without MSAA", f._effective(), (1, 1, "off"))
f.settings = {"msaa": 8, "af": 16, "traa": "multisample", "fps_limit": 30}
expect("forced", f._effective(), (8, 16, "multisample"))
f.settings = {"msaa": 1, "af": 1, "traa": "supersample", "fps_limit": 0}
expect("forced off", f._effective(), (1, 1, "off"))

print("check_preview:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
