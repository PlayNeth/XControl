"""pkexec's answer when the password prompt was cancelled, not a real failure."""


def cancelled(result):
    """True when `result` (a subprocess.CompletedProcess from pkexec) means the user cancelled
    the password prompt: pkexec exits 126 and says "Request dismissed" (or nothing). A refusal
    ("Not authorized", exit 127) isn't a cancel: the caller shows it, so the user knows why."""
    if result.returncode not in (126, 127):
        return False
    err = (result.stderr or "")
    if isinstance(err, bytes):
        err = err.decode(errors="replace")
    err = err.strip()
    return not err or "dismissed" in err
