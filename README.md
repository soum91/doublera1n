# doublera1n: jailbreak your iPhone 11/SE2 by using a new data volume

> [!CAUTION]
> CURRENTLY SUPPORTS iOS: 27.0-27.2 ON MAIN OS

doublera1n runs the phone's own stock System volume (sealed, untouched) with a separated data volume, as `/private/var`. It is booted from pwned DFU (usbliter8) with a patched kernel/iBoot and comes with a rootless jailbreak.

Stock iOS still here. A normal reboot on jailbreak data volume send you to stock iOS, to boot into the jailbreak state again, put the phone into pwned DFU and run `boot.sh`.

This resolve 2 problems I faced while using CFW: storage (which dualboot eats a lot) and cfw (which reboot turns your device into recovery mode).

But this is not a great solution, since SEP is disable for 2nd data partition, you can't login into iCloud on this, but luckily, FairPlay still works, which means application works well.

<p align="center">
  <img src="demo.jpg" width="360" alt="iPhone 11 Pro on iOS 27.2 booted into 2nd Data: App Store signed in, Sileo and Filza on the home screen, windowed apps">
</p>

## Quick start
```
git clone https://github.com/34306/doublera1n.git
cd doublera1n
./boot.sh
```
That's it. Plug the iPhone in booted into iOS (its version is read automatically), then put it into pwned DFU when it asks. The first time `boot.sh` installs 2nd Data (it asks for pwned DFU once more for the first boot), every time after it just boots 2nd Data.

On first use it runs `./setup.sh` by itself, which installs the Homebrew tools (libimobiledevice, libirecovery, ldid, libusb, ipsw) and creates `.venv` from `requirements.txt`. `.venv/` is machine-local, run `./setup.sh` again any time to repair it (if needed).

Prefer a menu? `./dualboot.sh` (↑/↓ select, Enter run):

| Menu | What it does |
|---|---|
| Start | same as `./boot.sh`: installs 2nd Data the first time, boots it after |
| SSH into 2nd Data | `ssh root@` through iproxy (pinned to the phone's UDID) |
| Re-apply fixes | pushes every userland fix again over SSH (2nd Data running) |
| Remove 2nd Data | deletes DataB and our files in Preboot, back to a single stock OS |
| More | pick the iOS version by hand, status / check the Mac, run `setup.sh` again |

> [!WARNING]
> When setting up 2nd Data, if the iPhone asks **iPhone Partially Set Up**, choose **Continue with Partial Setup**. Do NOT choose **Erase and Start Over**.

I also fixed a lot of problems such as Wifi did not auto connect when reboot, deep sleep panic the device, SEP-less panic stuff, etc. You can check patches i did in the repo as well.

## Requirements
- A Mac (support both Apple silicon and Intel) with Homebrew. `setup.sh` installs libimobiledevice, libirecovery, ldid, libusb, [ipsw](https://github.com/blacktop/ipsw) and creates `.venv`.
- A usbliter8 board (RP2350) for pwned DFU. I'd recommend using the board i put the image below.
- A13: iPhone 11 (iPhone12,1, n104ap), 11 Pro (iPhone12,3, d421ap), 11 Pro Max (iPhone12,5, d431ap), iPhone SE 2 (iPhone12,8, d79ap), iPad 9 Wi-Fi / Cellular (iPad12,1 j181ap / iPad12,2 j182ap). Boot compatibility has not been established for every model/build.
- Any iOS 27.x build of that iPhone. 2nd Data always runs the build installed on the phone (i might be extend to iOS 26 soon?).

## Untested iOS version

Every patch site is found again in the IPSW of the build you pick. If Apple changes a patched function too much, wait for me until I update and support it. Only iPhone 11 Pro on 27.2 (24B119) has booted so far, Issues, PR are welcome if it broken for you.

### iPhone 11 Pro Max on iOS 27.0.1

The Pro Max uses board `d431ap` (`iPhone12,5`), not the 11 Pro's `d421ap`. A dedicated `profiles/d431ap-24A446` profile is included for iOS 27.0.1, resolved against the original Pro Max firmware. The offline firmware precheck passed all 10 checks; **physical boot remains untested**. Never substitute the 11 Pro profile.

On a Mac, `python3 scripts/check_11pm.py --build 24A446` checks the local Pro Max profile. To re-resolve and verify the exact patch sites, run `python3 lib/precheck.py --board d431ap --build 24A446` after installing the analysis tools. Alternatively, run the GitHub Actions workflow **iPhone 11 Pro Max firmware precheck** and choose `24A446`. It uploads a diagnostic and the generated profile without connecting to the phone.

A passed precheck **does not mean the Pro Max has booted successfully**. It doesn't validate the second data volume, SEP limitations, ticket handling, or hardware recovery. Do not install a second data volume without a verified recovery path and a backup.

### USB-only diagnostic experiment (no UART board required)

The original installer **still requires UART** to recover the setup result and installed APTicket. Do **not** bypass that check and run `Start`: it is unsafe to attempt DataB setup without a return path. Some RP2354A service boards can pwn DFU without exposing a `/dev/cu.usbmodem*` serial port.

An independent, **read-only restore-ramdisk USB transport probe** is now available. It tests whether the Mac can reach a TCP listener in the ramdisk through `usbmuxd`/`iproxy`. The probe **never invokes `rdsetup`**, never creates a volume, and never reads an APTicket. Passing it would only establish a possible return transport, **not** validate a jailbreak installation. It is not a no-UART installer yet.

1. Pull the current fork's `main` branch. The separately built, signed `payload/setup/rdprobe` binary is already included next to `rdsetup`, so no manual ZIP download or file copying is needed. It is also reproducible with `bash src/build_rdprobe.sh` on a Mac with the iPhoneOS SDK and `ldid`. Do not substitute the original `rdsetup` binary.
2. With a current encrypted backup, the iPhone in pwned DFU, and a checked/selected **exact** build, prepare the probe on the Mac: `./.venv/bin/python3 dualboot.py probe-usb --build 24A446`. Preparation downloads the full IPSW and creates boot artifacts on the Mac; it does not send anything to the phone.
3. **Only after reviewing the physical boot risk**, add `--boot` to that command. It sends a modified boot chain and the read-only probe ramdisk, then waits up to 120 seconds for the USB handshake. The phone may need a force-reboot to return to stock. No iPhone 11 Pro Max boot is established yet.

#### Alternate diagnostics after a black-screen / no-USB boot

The first physical `d431ap` / `24A446` probe got through iBEC and accepted `bootx`, but the Apple Recovery USB device disappeared and **neither usbmuxd nor raw USB enumeration returned**. The kernel and restore ramdisk have **not** been shown to start. Re-running the same probe provides no new evidence.

The following variants use the **same exact Pro Max build and personalized boot chain**, but isolate different variables. They are opt-in experiments, **not a jailbreak**:

1. **Stock baseline, recommended first:** `./.venv/bin/python3 dualboot.py probe-usb --variant stock --build 24A446` prepares an original Apple RestoreRamDisk and RestoreTrustCache with no executable injection or APFS modification. It does not require the custom `rdprobe` binary. Only with an encrypted backup and a recovery plan, append `--boot` to send the chain. The Mac passively observes USB product IDs for up to 120 seconds. If Finder offers **Restore** or **Update**, do **not** click either. Seeing USB again is not proof that any jailbreak can run.
2. **Minimal peripheral firmware:** `./.venv/bin/python3 dualboot.py probe-usb --variant minimal --build 24A446` prepares the existing standalone read-only TCP probe, but the boot phase sends only SPTM, TXM, StaticTrustCache and RestoreTrustCache before the ramdisk, DeviceTree, SEP and kernel. Optional ANE/AOP/AVE/GFX/ISP/PMP/SIO/WCH images are omitted. Append `--boot` only for a separately authorized physical trial. This may fail earlier if omitted firmware is required.
3. **Explicit volatile ramdisk boot arguments:** `./.venv/bin/python3 dualboot.py probe-usb --variant bootargs --build 24A446` keeps all firmware and the read-only TCP probe from the original experiment, but immediately before `bootx` sends `setenv boot-args rd=md0 -v debug=0x2014e` to the temporary iBEC session. This is the material difference from the unsuccessful full and minimal probes. It does **not** call `setenvnp`, change persistent NVRAM, install anything, or modify DataB. The test fails closed before `bootx` if iBEC rejects the volatile setting. Append `--boot` only with a backup and a recovery plan.
4. **Native iBEC diagnostic (Mac preparation only recommended initially):** `./.venv/bin/python3 dualboot.py probe-usb --variant native-ibec --build 24A446` builds a separate patched **actual iBEC**, rather than packaging the patched iBSS executable as iBEC. It uses the same full firmware, ramdisk probe and explicit volatile boot-args as variant 3. It checks byte-for-byte whether the two patched executables differ and **refuses to boot if they are identical**. This corrects an unverified assumption carried over from a different iOS build, but does not establish an on-device boot. Preparation without `--boot` sends nothing to the phone, though pwned DFU is still needed to obtain the ticket. Prepare and compare on the Mac before considering any physical boot attempt.

**Physical observations (iPhone 11 Pro Max, 24A446):** The stock baseline returned an `idevice_id` identifier and the phone subsequently reached the normal Home Screen. This establishes that stock iOS came back, **not** that the restore ramdisk stayed booted. The minimal probe again received no USB listener response. The explicit-bootargs probe was physically attempted twice: iBEC accepted the volatile `setenv`, but there was still no USB listener response and the phone remained black. Avoid re-running those same variants without a distinct reason. The native-iBEC preparation compared the actual patched iBEC to patched iBSS and found them identical; it stopped on the Mac before attempting a boot. **Do not repeat that branch.**

Each variant validates that the patched iBoot artifact contains the expected `rd=md0` argument before sending anything, but only UART/kernel logs can confirm the actual runtime argument or pinpoint an early panic. A successful stock baseline would narrow the problem to the custom ramdisk or its trust cache; a failed stock baseline instead points to the shared boot-chain components. **Never run `install`, `Start`, or `remove` as a diagnostic.**

This experiment does **not** write DataB, but a previously untested boot chain is still risky. If the USB handshake fails, stop. A production no-UART installer requires its own authenticated and validated ticket/status transfer implementation and independent review.

#### Next diagnostic: existing panic reports (no more DFU boots)

After force-rebooting the Pro Max back to normal iOS, unlock it, trust the Mac, and connect it directly by USB. With the phone in **stock iOS**, run:

```sh
./.venv/bin/python3 scripts/boot_failure_triage.py collect
```

This calls `idevicecrashreport --keep` to **copy existing crash reports without removing them from the phone** and then prints a local summary of panic/reset report dates and clue families. If `idevicecrashreport` is missing, install the Mac's libimobiledevice tools; the existing repo setup already uses `idevice_id`. If several iPhones are connected, unplug the others or supply `--udid`. The script reports the folder where the original files were copied; they are never uploaded automatically.

To inspect a manually exported report instead, place the `.ips` file in a local folder and run `./.venv/bin/python3 scripts/boot_failure_triage.py analyze /path/to/folder`. If a new `panic-full` or `panic-base` report is present at the time of the failed boot, its `panicString` may narrow down a kernel/SEP/TXM/display failure. A missing report is **inconclusive**, because a failed iBoot or early kernel boot may never write persistent logs. Do not run the real installer until kernel startup and a return transport are verified independently.

**Pre-check** (`lib/precheck.py`) runs before anything touches the phone: it pulls only BuildManifest, kernelcache, TXM, iBSS, iBEC and DeviceTree (~70 MB) with `ipsw extract --remote`, builds the profile, applies every patch and checks TSS. Release builds come from ipsw.me, betas and RCs from AppleDB. If your build is on neither, give the IPSW yourself (file or URL).

```
./dualboot.py versions                                   # local profiles + Apple's builds
./dualboot.py select --auto                              # read the build from the iPhone (USB)
./dualboot.py select --build 24B5110a                    # any build, betas included
./dualboot.py precheck --build <build> --ipsw <file|URL> # an IPSW you fetched yourself
```

TSS: if Apple doesn't sign the build anymore (old builds, betas), the newest signed build's ticket is used for the setup chain, the patched iBoot doesn't check AP images. Once installed, 2nd Data uses the ticket installed on the phone (read over UART), this UART require you to have this kind of board:

![B4 PICO DFU board (RP2350, Lightning plug + USB-C): pwned DFU and UART over the Lightning port](pico_uart.jpg)

## Credits
- [usbliter8-fun by wh1te4ever](https://github.com/wh1te4ever/usbliter8-fun)
- [usbliter8]() (got deleted)
- [Liter8 by Xplo8E](https://github.com/Xplo8E/Liter8)
- [lycorine by hrtowii](https://github.com/hrtowii/lycorine-public)

## License
doublera1n is MIT, see [LICENSE](LICENSE). Some parts keep their own license.
