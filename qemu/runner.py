#!/usr/bin/env python3
"""Portable QEMU runner. Smoke boots our static Mach-O, NOT the iOS userland.

python qemu/runner.py --qemu PATH --firmware PATH [--mode smoke|apfs-smoke|exec-probe|ios]
All writable artifacts go into a new out/qemu-* directory; no physical disks are used.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RAM_BASE = 0x40000000
PAYLOAD_BASE = 0xF0000000
SYSTEM_BASE = 0xFC000000
PAYLOAD_LIMIT = 64 << 20
BOOT_GRACE_SECONDS = 40
SMOKE_MARKERS = ("Hello from user space on Darwin!", "I am process 1, uid 0")
APFS_SMOKE_MARKER = 'apfs: volume 0 "Smoke" of container 0'
EXEC_FAILURE = re.compile(r"load_init_program: failed loading /sbin/launchd: errno (\d+)")


def default_loader():
    for relative in ("xnuloader/loader.efi", "prebuilt/loader-qemu.efi"):
        path = ROOT / relative
        if path.is_file():
            return path
    return ROOT / "prebuilt/loader.efi"


def input_file(value):
    path = Path(value).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing or empty input: {path}")
    return path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_apfs_smoke(program, session):
    root = session / "smoke-root"
    directories = ("dev", "sbin", "tmp", "etc", "private", "private/var")
    for directory in directories:
        (root / directory).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(program, root / "sbin/launchd")
    manifest = "".join(f"40755\t0\t0\t{directory}\n" for directory in directories)
    manifest += "100755\t0\t0\tsbin/launchd\n"
    (session / "smoke.manifest").write_text(manifest, encoding="utf-8", newline="\n")
    image = session / "smoke.apfs"
    subprocess.run([sys.executable, str(ROOT / "tools/apfs/mkapfs.py"), "-o", "smoke.apfs",
                    "Smoke=smoke-root,manifest=smoke.manifest"], cwd=session, check=True, timeout=30)
    return input_file(image)


def check_memory(memory_gib, system_size=0):
    if not 3 <= memory_gib <= 16:
        raise ValueError("guest memory must be 3..16 GiB (the payload is at 0xF0000000)")
    if system_size and memory_gib < 7:
        raise ValueError("iOS mode needs at least 7 GiB to preserve the loader's resident-image window")
    if system_size and SYSTEM_BASE + system_size > RAM_BASE + (memory_gib << 30):
        raise ValueError("system image does not fit guest RAM; increase --memory-gib")


def build_command(qemu, firmware, mode, memory_gib, cpus, display, system=None, cpu="cortex-a76"):
    command = [str(qemu), "-M", "virt,gic-version=3", "-cpu", cpu,
               "-accel", "tcg,tb-size=128", "-smp", str(cpus), "-m", f"{memory_gib}G",
               "-bios", str(firmware), "-drive", "file=fat:rw:esp,format=raw,if=virtio",
               "-device", f"loader,file=payload.bin,addr={PAYLOAD_BASE:#x},force-raw=on",
               "-device", "ramfb", "-display", display, "-serial", "stdio",
               "-monitor", "none", "-nic", "none", "-no-reboot"]
    if mode == "ios":
        if system is None:
            raise ValueError("iOS mode requires a system image")
        # QEMU key/value options escape a literal comma by doubling it.
        path = system.as_posix().replace(",", ",,")
        command += ["-device", f"loader,file={path},addr={SYSTEM_BASE:#x},force-raw=on",
                    "-global", "virtio-mmio.force-legacy=false",
                    "-device", "virtio-tablet-device", "-device", "virtio-keyboard-device"]
    return command


def verdict(mode, text, returncode, timed_out):
    if mode == "exec-probe":
        failure = EXEC_FAILURE.search(text)
        if failure:
            return "exec_rejected_bad_arch" if int(failure[1]) == 86 else f"exec_rejected_errno_{failure[1]}"
        return "exec_probe_inconclusive"
    if mode != "ios":
        markers = SMOKE_MARKERS + ((APFS_SMOKE_MARKER,) if mode == "apfs-smoke" else ())
        if all(marker in text for marker in markers):
            return "smoke_userspace_pass"
        return "smoke_userspace_fail"
    if timed_out:
        return "session_timeout"
    return "session_completed" if returncode == 0 else "emulator_error"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "apfs-smoke", "exec-probe", "ios"), default="smoke")
    parser.add_argument("--qemu", default=os.environ.get("QEMU_BIN", "qemu-system-aarch64"))
    parser.add_argument("--firmware", required=True, type=Path)
    parser.add_argument("--kernel", type=Path, default=ROOT / "prebuilt/mach.development.bcm2837")
    parser.add_argument("--loader", type=Path, default=default_loader())
    parser.add_argument("--ramdisk", type=Path, help="smoke/apfs-smoke: test Mach-O; ios: small root.apfs")
    parser.add_argument("--system-image", type=Path, help="iOS mode only: system.apfs from local IPSW")
    parser.add_argument("--memory-gib", type=int, help="guest virtual RAM: smoke=3, ios=7")
    parser.add_argument("--cpus", type=int, default=1)
    parser.add_argument("--cpu", choices=("cortex-a76", "max"), default="cortex-a76",
                        help="max exposes emulated CPU extensions; it does not implement an Apple ABI")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--display", choices=("none", "gtk", "sdl"), default="none")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.seconds <= 3600 or not 1 <= args.cpus <= 8:
            raise ValueError("--seconds must be 1..3600; --cpus must be 1..8")
        if args.mode != "ios" and args.system_image:
            raise ValueError("--system-image is only valid in iOS mode")
        if args.mode == "exec-probe" and args.ramdisk is None:
            raise ValueError("exec-probe requires an explicit prepared --ramdisk APFS image")
        qemu = shutil.which(str(args.qemu))
        if qemu is None:
            raise ValueError(f"QEMU executable not found: {args.qemu}")
        qemu = str(Path(qemu).resolve())
        firmware, kernel, loader = map(input_file, (args.firmware, args.kernel, args.loader))
        ramdisk = input_file(args.ramdisk or ROOT / (
            "prebuilt/userland/hello" if args.mode != "ios" else "userland/root.apfs"))
        system = input_file(args.system_image or ROOT / "userland/system.apfs") if args.mode == "ios" else None
        memory_gib = args.memory_gib if args.memory_gib is not None else (7 if args.mode == "ios" else 3)
        check_memory(memory_gib, system.stat().st_size if system else 0)
        if kernel.stat().st_size + ramdisk.stat().st_size + 4096 > PAYLOAD_LIMIT:
            raise ValueError("kernel + ramdisk exceeds the loader's 64 MiB payload area")
    except (OSError, ValueError) as error:
        parser.error(str(error))

    version = subprocess.run([qemu, "--version"], capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()[0]
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix=f"qemu-{args.mode}-", dir=out))
    test_program = ramdisk if args.mode == "apfs-smoke" else None
    if test_program:
        ramdisk = build_apfs_smoke(test_program, session)
    esp = session / "esp/EFI/BOOT"
    esp.mkdir(parents=True)
    shutil.copyfile(loader, esp / "BOOTAA64.EFI")
    # maxmem limits XNU's managed pages; QEMU's high-address payload still needs 3 GiB of address space.
    bootargs = f"loader_return_after={args.seconds} epoch={int(time.time())} cpus={args.cpus}"
    bootargs += " virtio_input=1" if args.mode == "ios" else " maxmem=256"
    payload = [sys.executable, str(ROOT / "xnuloader/mkpayload.py"), "-o", str(session / "payload.bin"),
               f"kernel={kernel}", f"ramdisk={ramdisk}", "--cmdline", bootargs]
    if system:
        payload += ["--rdres", f"{system.stat().st_size:x}"]
    subprocess.run(payload, check=True, timeout=30)
    if (session / "payload.bin").stat().st_size > PAYLOAD_LIMIT:
        raise ValueError("packed payload exceeds the loader's 64 MiB area")
    command = build_command(qemu, firmware, args.mode, memory_gib, args.cpus, args.display, system, args.cpu)
    report = {"mode": args.mode, "backend": "qemu-tcg", "qemu_version": version,
              "command": command, "bootargs": bootargs, "inputs": {},
              "ios_ui_validated": False, "gpu_acceleration_validated": False}
    for name, path in (("kernel", kernel), ("loader", loader), ("ramdisk", ramdisk), ("firmware", firmware), ("system", system), ("test_program", test_program)):
        if path:
            report["inputs"][name] = {"path": str(path), "sha256": sha256(path), "size": path.stat().st_size}
    started = time.monotonic()
    timed_out = False
    with (session / "serial.log").open("wb") as log:
        try:
            result = subprocess.run(command, cwd=session, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=args.seconds + BOOT_GRACE_SECONDS)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            timed_out, returncode = True, None
    # Bound log inspection; the complete serial capture remains on disk.
    with (session / "serial.log").open("rb") as log:
        text = log.read(8 << 20).decode("utf-8", errors="replace")
    report.update(elapsed_seconds=round(time.monotonic() - started, 3),
                  returncode=returncode, timed_out=timed_out,
                  verdict=verdict(args.mode, text, returncode, timed_out))
    failure = EXEC_FAILURE.search(text)
    if args.mode == "exec-probe":
        report["exec_errno"] = int(failure[1]) if failure else None
    (session / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['verdict']}: {session}")
    return 0 if report["verdict"] in ("smoke_userspace_pass", "session_completed") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f"runner.py: {error}")
