"""Catch handler parameters named `_`, which would hide the gettext function
(a click on such a handler would crash with "'tuple' object is not callable")."""
import ast
import glob
import os
import sys

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "xcontrol")
bad = []
for path in sorted(glob.glob(os.path.join(root, "*.py"))):
    for fn in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
        if isinstance(fn, (ast.FunctionDef, ast.Lambda)):
            a = fn.args
            names = [x.arg for x in a.args + a.kwonlyargs] + ([a.vararg.arg] if a.vararg else [])
            calls = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_"
                        for n in ast.walk(fn))
            if "_" in names and calls:
                bad.append(f"{os.path.basename(path)}:{fn.lineno} {getattr(fn, 'name', 'lambda')}")
for b in bad:
    print("gettext shadowed by a parameter named _:", b)
print("check_gettext:", "FAILED" if bad else "ok")
sys.exit(1 if bad else 0)
