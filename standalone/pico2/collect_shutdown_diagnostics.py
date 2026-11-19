#!/usr/bin/env python3
"""Collect second-Data panic/watchdog diagnostics privately over existing USB SSH.

Read-only on the iPhone. No changes to APFS/Preboot/NVRAM or jailbreak.
Works only while the already-installed second Data environment is SSH reachable.
Keeps full diagnostic records in a private local directory: DO NOT publish it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys

CRASH_ROOTS = (
    "/private/var/mobile/Library/Logs/CrashReporter",
    "/private/var/root/Library/Logs/CrashReporter",
)
MAX_FILES = 12
MAX_FILE_BYTES = 2 * 1024 * 1024

class DiagnoseError(RuntimeError):
    pass


def valid_log_path(path: str) -> bool:
    if not path or not path.startswith("/") or not re.fullmatch(r"[A-Za-z0-9_./+@-]+", path):
        return False
    parts = PurePosixPath(path).parts
    if ".." in parts or not any(path.startswith(root + "/") for root in CRASH_ROOTS):
        return False
    name = PurePosixPath(path).name.lower()
    return (
        name.startswith("panic-full")
        or name.startswith("panicbase")
        or name.startswith("jetsamevent")
        or "watchdog" in name
    )


def execute_ssh(checkout: Path, remote_cmd: str, timeout: int = 120) -> bytes:
    try:
        r = subprocess.run(
            ["./dualboot.py", "ssh", remote_cmd],
            cwd=checkout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise DiagnoseError("SSH timed out; inspect the device's current boot state") from e
    except OSError as e:
        raise DiagnoseError(f"failed to start desktop SSH helper: {e}") from e
    if r.returncode != 0:
        raise DiagnoseError(
            f"device SSH command exited {r.returncode}: "
            + r.stderr.decode("utf-8", errors="replace")[-400:]
        )
    return r.stdout


def run(checkout: Path, destination: Path):
    checkout = checkout.expanduser().resolve(strict=True)
    if not (checkout / "dualboot.py").is_file():
        raise DiagnoseError("desktop checkout missing dualboot.py")
    if destination.exists():
        raise DiagnoseError("refusing to overwrite existing diagnostic folder")
    destination.mkdir(parents=True, mode=0o700)
    destination.chmod(0o700)
    snapshot = (
        "date -u; uname -a; uptime; "
        "sysctl kern.boottime 2>/dev/null || true; "
        "sysctl kern.osrelease 2>/dev/null || true; "
        "sysctl kern.bootargs 2>/dev/null || true; "
        "df -h /private/var 2>/dev/null || true"
    )
    (destination / "system-snapshot.txt").write_bytes(execute_ssh(checkout, snapshot))
    roots = " ".join(shlex.quote(s) for s in CRASH_ROOTS)
    cmd = (
        f"find {roots} -type f "
        "\\( -name 'panic-full*' -o -name 'PanicFull*' "
        "-o -name 'PanicBase*' -o -name 'JetsamEvent*' "
        "-o -name '*watchdog*' \\) -print 2>/dev/null | tail -n 60"
    )
    listing = execute_ssh(checkout, cmd).decode("utf-8", errors="replace")
    paths = [p for p in listing.splitlines() if valid_log_path(p)]
    # Most recent file names usually sort by embedded date. Never trust the
    # resulting paths as shell commands without shlex.quote and root validation.
    paths = sorted(set(paths), reverse=True)[:MAX_FILES]
    (destination / "inventory.txt").write_text("\n".join(paths) + ("\n" if paths else ""))
    downloaded = []
    for index, remote in enumerate(paths, 1):
        base = PurePosixPath(remote).name
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
        try:
            content = execute_ssh(
                checkout,
                f"head -c {MAX_FILE_BYTES} -- {shlex.quote(remote)}",
                timeout=180,
            )
        except DiagnoseError as e:
            downloaded.append(f"FAILED: {remote}: {e}")
            continue
        local = destination / f"{index:02d}-{safe}"
        local.write_bytes(content)
        local.chmod(0o600)
        downloaded.append(f"LOCAL {local.name}: {remote} ({len(content)} bytes, capped at 2 MiB)")
    summary = [
        "Private second-Data runtime diagnostics, not a firmware/boot validation.",
        "Phone state: SSH reachable at capture time. A later reboot/power-off is NOT inferred.",
        f"Remote files inventoried: {len(paths)}",
        *downloaded,
        "",
        "Compare panicString, watchdog and uptime against the time of the observed power-off.",
        "If no panic log exists, check Mac USB/serial logs and battery/power loss separately.",
        "DO NOT commit, upload or publicly share unredacted diagnostic files.",
    ]
    (destination / "README.txt").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    print(f"PRIVATE OUTPUT: {destination}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkout", type=Path,
                   default=Path.home() / "doublera1n-usb-537622e",
                   help="existing, successful desktop checkout with USB SSH")
    p.add_argument("--output", type=Path,
                   default=Path.home() / "Desktop" / (
                       "doublera1n-shutdown-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                   ))
    a = p.parse_args(argv)
    try:
        run(a.checkout, a.output.expanduser())
    except (DiagnoseError, OSError) as e:
        print("STOP: " + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
