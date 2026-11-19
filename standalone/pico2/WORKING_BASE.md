# Successful installation base

This branch starts at `537622e5e041445b0d2ff9de7a1df5e6248c8670`, the commit identified by the user's successful installation checkout. Pico tools are additive. The desktop installer, boot scripts, payload, libraries and profiles retain the successful commit's bytes.

The d431ap/24A446 profile generated on the installation Mac must be retained. Public profiles from another development branch can contain different patch records. Validate existing boot assets against the original profile with `--profile-dir` when it is located outside this checkout.

From the successful installation repository, after switching to this branch, export with its existing virtual environment:

```bash
.venv/bin/python3 standalone/pico2/nand_boot.py export \
  --work-root "${DUALBOOT_HOME:-$PWD/dualboot-work}" \
  --profile-dir "$PWD/profiles/d431ap-24A446" \
  --output "$HOME/Desktop/PicoNAND"
```

If `DUALBOOT_HOME` points elsewhere, use that directory for `--work-root`. A generated profile that exists only on the Mac stays there. Preserve any local source modifications when updating the checkout. Source commit identity alone cannot establish whether the successful Mac checkout also contains uncommitted edits.

The export prepares private local files. Physical validation of Preboot paths, staging and Pico handoff is still required.
