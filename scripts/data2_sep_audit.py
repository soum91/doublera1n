#!/usr/bin/env python3
"""Audit intentionally disabled DataB SEP paths; optionally collect PRIVATE read-only logs.

Default mode reads checked-in exact-build JSON only. It does NOT apply patches,
modify the phone, touch keybags, enable passcodes, or prove SEP runtime health.

Optional --probe uses the project's existing USB SSH helper only while DataB is
already running and writes private diagnostic output on the Mac. No boot actions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

TARGET = "d431ap-24A446"
REQUIRED_BOOT = (
    "kernel.credential-manager.sendsepcommand.result",
    "kernel.credential-manager.processscrdresponsepayload.result",
    "kernel.aks.start.sep-call",
    "kernel.aks.external-method.selector7.13",
)
REQUIRED_OSB = (
    "kernel.aks.sep-booted.false.0",
    "kernel.aks.sep-booted.false.1",
    "kernel.sep.sleep.sep-not-alive.0",
    "kernel.sep.sleep.sep-not-alive.1",
)
# All commands are hardcoded read-only queries. Do not accept arbitrary remote
# commands, because this tool is used to diagnose security-sensitive boot state.
READ_ONLY_PROBES = {
    "system.txt": (
        "date -u; uname -a; uptime; "
        "sysctl kern.osrelease 2>&1; "
        "sysctl kern.bootargs 2>&1"
    ),
    "sep-ioreg.txt": (
        "ioreg -l -w 0 2>&1 | "
        "grep -i -E 'AppleSEPManager|AppleSEPKeyStore|AppleSEPCredentialManager|"
        "AppleCredentialManager|sep-booted|sks|scrd|xART' | head -n 160"
    ),
    "sep-log.txt": (
        "log show --style syslog --last 10m 2>&1 | "
        "grep -i -E 'AppleSEP|SEP is|SEP_OS|sep-booted|credentialmanager|"
        "no sks endpoint|sks endpoint|scrd|AKS|xART|sep_endpoint' | head -n 250"
    ),
    "service-status.txt": (
        "launchctl print-disabled system 2>&1 | "
        "grep -i -E 'corerepaird|seserviced|mobileactivationd|securityd' | head -n 80"
    ),
}
MAX_OUTPUT_BYTES = 128 * 1024


class AuditError(RuntimeError):
    pass


def _records(path: Path) -> list[dict]:
    try:
        items = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read exact-profile patch list {path}: {exc}") from exc
    if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
        raise AuditError(f"patch list {path} is not a JSON array of records")
    ids = [x.get("id") for x in items]
    if any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise AuditError(f"missing/duplicate patch IDs in {path}")
    return items


def audit(root: Path, profile: str = TARGET) -> dict:
    if profile != TARGET:
        raise AuditError(f"this evidence audit is calibrated only for {TARGET}")
    base = root / "profiles" / profile
    boot = _records(base / "kernel-boot-jit.json")
    osb = _records(base / "kernel-osb.json")
    bmap = {r["id"]: r for r in boot}
    omap = {r["id"]: r for r in osb}
    for name in REQUIRED_BOOT:
        if name not in bmap:
            raise AuditError(f"required bootstrap SEP stub not found: {name}")
    for name in REQUIRED_OSB:
        if name not in omap:
            raise AuditError(f"required DataB SEP-less patch not found: {name}")

    # The current exact build stubs 26 AppleCredentialManager methods with
    # paired success-result/return replacements. Do not mistake these stubs
    # for a functioning SCRD/SEP transport.
    prefix = "kernel.credential-manager."
    pairs = {}
    for r in boot:
        rid = r["id"]
        if not rid.startswith(prefix):
            continue
        tail = rid[len(prefix):]
        if "." not in tail:
            raise AuditError(f"invalid credential manager patch name: {rid}")
        fn, kind = tail.rsplit(".", 1)
        if kind not in ("result", "return"):
            raise AuditError(f"unexpected credential-manager patch: {rid}")
        pairs.setdefault(fn, {})[kind] = r
    if len(pairs) != 26 or any(set(v) != {"result", "return"} for v in pairs.values()):
        raise AuditError("ACM patch topology differs from reviewed 26 method pairs; re-audit")
    # On d431ap/24A446 these instructions are immediate success / return.
    for name, pp in pairs.items():
        if pp["result"].get("replacementBytes") != "00008052" or pp["return"].get("replacementBytes") != "c0035fd6":
            raise AuditError(f"ACM method {name} no longer has the expected forced-success stub")
    if bmap["kernel.aks.start.sep-call"].get("replacementBytes") != "1f2003d5":
        raise AuditError("AKS start SEP-call patch changed unexpectedly")
    if bmap["kernel.aks.external-method.selector7.13"].get("replacementBytes") != "c80080d2":
        raise AuditError("AKS synthesized noPin/beenUnlocked selector patch changed unexpectedly")
    if [omap[x].get("replacementBytes") for x in ("kernel.aks.sep-booted.false.0",
                                                   "kernel.aks.sep-booted.false.1")] != ["00008052", "c0035fd6"]:
        raise AuditError("AKS SEP-booted false stub has changed unexpectedly")

    return {
        "target": profile,
        "source": "checked-in patch profiles only; not a runtime SEP probe",
        "boot_jit_records": len(boot),
        "osb_records": len(osb),
        "acm_forced_success_methods": len(pairs),
        "acm_patch_words": sum(len(v) for v in pairs.values()),
        "acm_stubbed_examples": ["sendSEPCommand", "processSCRDResponsePayload"],
        "aks_start_sep_call_skipped": True,
        "aks_selector7_fakes_unlock_state": True,
        "aks_sep_booted_forced_false": True,
        "sep_runtime_state": "NOT MEASURED",
        "all_sep_features_restored": False,
        "requires": "real SEP endpoint evidence before any experimental restoration of normal ACM/AKS paths",
    }


def _read_only_ssh(checkout: Path, command: str, timeout: int = 80) -> tuple[int, bytes]:
    if command not in READ_ONLY_PROBES.values():
        raise AuditError("refusing unapproved remote command")
    try:
        cp = subprocess.run(
            ["./dualboot.py", "ssh", command], cwd=checkout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (1, f"UNAVAILABLE: {exc}\n".encode())
    result = cp.stdout + (b"\nSSH STDERR:\n" + cp.stderr if cp.stderr else b"")
    return cp.returncode, result[:MAX_OUTPUT_BYTES]


def probe(checkout: Path, output: Path) -> None:
    checkout = checkout.expanduser().resolve(strict=True)
    if not (checkout / "dualboot.py").is_file():
        raise AuditError("checkout missing dualboot.py (existing successful Mac workspace required)")
    if output.exists():
        raise AuditError("private output folder already exists; refusing overwrite")
    output.mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    statuses = []
    for filename, command in READ_ONLY_PROBES.items():
        code, data = _read_only_ssh(checkout, command)
        dest = output / filename
        dest.write_bytes(data)
        dest.chmod(0o600)
        statuses.append(f"{filename}: remote exit {code}, captured {len(data)} bytes")
    readme = (
        "PRIVATE DataB SEP diagnostics. Never publish these files unchanged.\n"
        "No device mutation, keybag access, passcode operation or activation request was performed.\n"
        "A missing endpoint or failed command here is only a diagnostic clue; no SEP fix is proved.\n\n"
        + "\n".join(statuses) + "\n"
    )
    (output / "README.txt").write_text(readme)
    (output / "README.txt").chmod(0o600)
    print(readme + f"Private output: {output}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                    help="doublera1n repository checkout for offline JSON audit")
    ap.add_argument("--probe", action="store_true",
                    help="opt-in: read-only SSH snapshots from already-running DataB")
    ap.add_argument("--checkout", type=Path, default=Path.home() / "doublera1n-usb-537622e")
    ap.add_argument("--output", type=Path, default=Path.home() / "Desktop" /
                    ("doublera1n-sep-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    args = ap.parse_args(argv)
    try:
        report = audit(args.root.expanduser())
        print(json.dumps(report, indent=2))
        if args.probe:
            probe(args.checkout, args.output.expanduser())
        return 0
    except (AuditError, OSError) as exc:
        print("STOP: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
