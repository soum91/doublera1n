#!/usr/bin/env python3
"""Read-only verification of an iPhone 11 Pro Max (d431ap) profile.

This never connects to a phone or patches firmware. Passing does not imply that
the boot chain has been successfully tested on physical hardware.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "kernel-boot-jit.json", "kernel-restore-nodebugger.json",
    "kernel-vm-fault-cs-bypass.json", "kernel-ramdisk.json",
    "kernel-osb.json", "txm-boot-permissive.json", "txm-cs-only.json",
)


def inspect_profile(build, root=ROOT):
    path = Path(root) / "profiles" / f"d431ap-{build}" / "profile.json"
    if not path.is_file():
        return [f"No d431ap/{build} profile. Never substitute the d421ap (11 Pro) profile."], [
            f"Generate with: python3 lib/precheck.py --board d431ap --build {build}"
        ]
    try:
        profile = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return [f"Cannot read profile: {exc}"], []

    errors = []
    for field, expected in {
        "board": "d431ap", "build": build, "cpid": "0x8030", "bdid": "0x02",
    }.items():
        if str(profile.get(field, "")).lower() != expected.lower():
            errors.append(f"{field}: expected {expected}, got {profile.get(field)!r}")
    if profile.get("product_types") != ["iPhone12,5"]:
        errors.append("product_types must be ['iPhone12,5']")

    for name in REQUIRED:
        target = path.parent / name
        if not target.is_file():
            errors.append(f"Missing {name}")
            continue
        try:
            records = json.loads(target.read_text())
        except (OSError, ValueError) as exc:
            errors.append(f"Unreadable records in {name}: {exc}")
            continue
        if not isinstance(records, list) or not records:
            errors.append(f"{name}: no patch records")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if profile.get("files", {}).get(name) != digest:
            errors.append(f"{name}: checksum does not match profile")
    if profile.get("precheck", {}).get("ok") is not True:
        errors.append("No successful firmware-specific precheck recorded")

    notices = ["Offline record consistency does not demonstrate a successful boot."]
    if profile.get("pending_userland"):
        notices.append("Matching userland patches still need to be resolved from the root filesystem.")
    if profile.get("tested") is not True:
        notices.append("Not device-tested on iPhone 11 Pro Max.")
    return errors, notices


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", default="24A446", help="27.0.1: 24A446; 27.2: 24B119")
    args = ap.parse_args()
    errors, notices = inspect_profile(args.build)
    for item in errors:
        print("FAIL:", item)
    for item in notices:
        print("NOTE:", item)
    if errors:
        raise SystemExit(2)
    print(f"PASS: d431ap/{args.build} record checks passed (not device-tested)")


if __name__ == "__main__":
    main()
