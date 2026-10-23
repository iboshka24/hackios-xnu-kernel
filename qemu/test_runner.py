from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import runner


class RunnerTests(unittest.TestCase):
    def test_loader_priority_preserves_phone_prebuilt(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(runner, "ROOT", Path(folder)):
            original = Path(folder) / "prebuilt/loader.efi"
            self.assertEqual(runner.default_loader(), original)
            qemu = Path(folder) / "prebuilt/loader-qemu.efi"
            qemu.parent.mkdir()
            qemu.touch()
            self.assertEqual(runner.default_loader(), qemu)
            built = Path(folder) / "xnuloader/loader.efi"
            built.parent.mkdir()
            built.touch()
            self.assertEqual(runner.default_loader(), built)

    def test_memory_payload_and_resident_boundaries(self):
        runner.check_memory(3)
        runner.check_memory(7, 2500 << 20)
        for size in (0, 1, 2, 17):
            with self.assertRaises(ValueError):
                runner.check_memory(size)
        with self.assertRaises(ValueError):
            runner.check_memory(3, 256 << 20)
        with self.assertRaises(ValueError):
            runner.check_memory(6, 64 << 20)
        runner.check_memory(7, runner.RAM_BASE + (7 << 30) - runner.SYSTEM_BASE)
        with self.assertRaises(ValueError):
            runner.check_memory(7, runner.RAM_BASE + (7 << 30) - runner.SYSTEM_BASE + 1)

    def test_smoke_needs_both_markers(self):
        for text in ("", "SpringBoard", runner.SMOKE_MARKERS[0], runner.SMOKE_MARKERS[1]):
            self.assertEqual(runner.verdict("smoke", text, 0, False), "smoke_userspace_fail")
        self.assertEqual(runner.verdict("smoke", "\n".join(runner.SMOKE_MARKERS), 0, False), "smoke_userspace_pass")

    def test_apfs_smoke_requires_actual_apfs_mount(self):
        text = "\n".join(runner.SMOKE_MARKERS)
        self.assertEqual(runner.verdict("apfs-smoke", text, 0, False), "smoke_userspace_fail")
        self.assertEqual(runner.verdict("apfs-smoke", text + runner.APFS_SMOKE_MARKER, 0, False), "smoke_userspace_pass")

    def test_real_apfs_builder_is_deterministic_on_synthetic_input(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / "program"
            program.write_bytes(b"synthetic program, not executable")
            images = []
            for name in ("one", "two"):
                session = Path(folder) / name
                session.mkdir()
                images.append(runner.build_apfs_smoke(program, session))
            self.assertEqual(runner.sha256(images[0]), runner.sha256(images[1]))
            with images[0].open("rb") as stream:
                stream.seek(32)
                self.assertEqual(stream.read(4), b"NXSB")

    def test_timeout_is_reported_separately_from_guest_evidence(self):
        self.assertEqual(runner.verdict("ios", "SpringBoard", None, True), "session_timeout")
        self.assertEqual(runner.verdict("ios", "", 1, False), "emulator_error")
        self.assertEqual(runner.verdict("ios", "", 0, False), "session_completed")
        self.assertEqual(runner.verdict("smoke", "\n".join(runner.SMOKE_MARKERS), None, True), "smoke_userspace_pass")

    def test_exec_probe_reports_the_real_kernel_error_not_success(self):
        text = "load_init_program: failed loading /sbin/launchd: errno 86"
        self.assertEqual(runner.verdict("exec-probe", text, 0, False), "exec_rejected_bad_arch")
        self.assertEqual(runner.verdict("exec-probe", text.replace("86", "2"), 0, False), "exec_rejected_errno_2")
        self.assertEqual(runner.verdict("exec-probe", "SpringBoard", 0, False), "exec_probe_inconclusive")

    def test_command_is_headless_offline_and_uses_no_host_devices(self):
        command = runner.build_command("qemu", Path("firmware with space.fd"), "smoke", 3, 1, "none")
        self.assertIn("firmware with space.fd", command)
        self.assertEqual(command[command.index("-nic") + 1], "none")
        self.assertEqual(command[command.index("-monitor") + 1], "none")
        self.assertIn("tcg,tb-size=128", command)
        self.assertFalse(any("/dev/" in arg or "PhysicalDrive" in arg for arg in command))

    def test_ios_mode_attaches_actual_images_and_input(self):
        command = runner.build_command("qemu", Path("efi"), "ios", 7, 4, "none", Path("image,1.apfs"))
        self.assertTrue(any("file=image,,1.apfs" in arg for arg in command))
        self.assertIn("virtio-tablet-device", command)
        with self.assertRaises(ValueError):
            runner.build_command("qemu", Path("efi"), "ios", 7, 4, "none")

    def test_cpu_extensions_are_an_explicit_emulator_choice(self):
        command = runner.build_command("qemu", Path("efi"), "smoke", 3, 1, "none", cpu="max")
        self.assertEqual(command[command.index("-cpu") + 1], "max")

    def test_missing_and_empty_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "image"
            with self.assertRaises(ValueError):
                runner.input_file(path)
            path.touch()
            with self.assertRaises(ValueError):
                runner.input_file(path)
            path.write_bytes(b"fixture")
            self.assertEqual(runner.input_file(path), path.resolve())
            self.assertEqual(len(runner.sha256(path)), 64)

    def test_real_payload_packer_with_synthetic_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "input", Path(folder) / "payload"
            source.write_bytes(b"synthetic kernel")
            subprocess.run([sys.executable, str(runner.ROOT / "xnuloader/mkpayload.py"),
                            "-o", str(output), f"kernel={source}", "--cmdline", "maxmem=256"],
                           check=True, capture_output=True, timeout=10)
            data = output.read_bytes()
            magic, size = struct.unpack_from("<II", data)
            self.assertEqual(magic, 0x50554E58)
            self.assertEqual(size, len(data) - 8)
            name, length, reserved = struct.unpack_from("<16sII", data, 8)
            self.assertEqual((name.rstrip(b"\0"), length, reserved), (b"kernel", 16, 0))
            self.assertEqual(data[32:48], source.read_bytes())
            self.assertEqual(data[-24:], b"\0" * 24)

    def test_oversize_packed_payload_never_launches_qemu(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(runner, "ROOT", Path(folder)):
            source = Path(folder) / "input"
            source.write_bytes(b"x")

            def fake_run(command, **kwargs):
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(command, 0, stdout="test executable\n")
                output = Path(command[command.index("-o") + 1])
                output.write_bytes(b"\0" * 8193)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(runner, "PAYLOAD_LIMIT", 8192), \
                    mock.patch.object(runner.subprocess, "run", side_effect=fake_run) as run:
                with self.assertRaisesRegex(ValueError, "packed payload exceeds"):
                    runner.main(["--qemu", sys.executable, "--firmware", str(source),
                                 "--kernel", str(source), "--loader", str(source), "--ramdisk", str(source)])
                self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
