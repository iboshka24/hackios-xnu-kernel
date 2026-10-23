#!/bin/bash
# Host-only regression checks: no IPSW, compiler, emulator or phone is used.
set -euo pipefail
ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/work/"{common/devices,userland,ios165/rootfs,qemu,bin}
cp "$ROOT/common/"{lib,build,run}.sh "$tmp/work/common/"
cp "$ROOT/common/devices/qemu-virt.conf" "$tmp/work/common/devices/"
touch "$tmp/work/userland/"{root,system}.apfs
cat > "$tmp/work/userland/build.sh" <<'SH'
#!/usr/bin/env bash
echo "image builder ran"
exit "${TEST_IMAGE_STATUS:-0}"
SH
cat > "$tmp/work/qemu/run-ios.sh" <<'SH'
#!/usr/bin/env bash
echo "emulator ran"
exit "${TEST_QEMU_STATUS:-0}"
SH
chmod +x "$tmp/work/userland/build.sh" "$tmp/work/qemu/run-ios.sh"
passed=0 failed=0
expect() {
	local name=$1 want=$2 got=0
	shift 2
	"$@" > "$tmp/output" 2>&1 || got=$?
	if [ "$got" = "$want" ]; then
		printf 'PASS %s\n' "$name"
		passed=$((passed + 1))
	else
		printf 'FAIL %s: exit %s, expected %s\n' "$name" "$got" "$want"
		cat "$tmp/output"
		failed=$((failed + 1))
	fi
}
cd "$tmp/work"
expect 'image builder failure reaches caller' 1 env SKIP='kernel loader boot' TEST_IMAGE_STATUS=23 \
	bash common/build.sh qemu-virt
expect 'successful image builder stays successful' 0 env SKIP='kernel loader boot' TEST_IMAGE_STATUS=0 \
	bash common/build.sh qemu-virt
expect 'emulator failure reaches caller through tee' 42 env TEST_QEMU_STATUS=42 bash common/run.sh qemu-virt 1
expect 'successful emulator stays successful' 0 env TEST_QEMU_STATUS=0 bash common/run.sh qemu-virt 1
cat > bin/tee <<'SH'
#!/usr/bin/env bash
cat > /dev/null
exit 73
SH
chmod +x bin/tee
expect 'log writer failure reaches caller' 73 env PATH="$PWD/bin:$PATH" TEST_QEMU_STATUS=0 \
	bash common/run.sh qemu-virt 1
expect 'unknown device fails before building' 1 bash common/build.sh absent
mv userland/root.apfs userland/root.saved
expect 'missing image prevents emulator launch' 1 bash common/run.sh qemu-virt 1

if [ -f "$ROOT/userland/build.sh" ]; then
	# Execute the actual staging statements and shell options, not duplicate implementations.
	settings=$(sed -n '/^set -e/p' "$ROOT/userland/build.sh")
	copy_block=$(sed -n '/^[[:space:]]*cp obj\/hello_dyn /p; /^[[:space:]]*\[ -f obj\/drawable_test \]/p' \
		"$ROOT/userland/build.sh")
	zone_block=$(sed -n '/^[[:space:]]*zone=$(timedatectl /p' "$ROOT/userland/build.sh")
	[ -n "$settings" ] && [ -n "$copy_block" ] && [ -n "$zone_block" ]
	mkdir -p obj root/bin
	touch obj/{hello_dyn,svc_test,surf_test,rwtouch,mg_test}
	expect 'prebuilt staging tolerates absent optional diagnostic' 0 bash -c "$settings
$copy_block
true"
	printf 'diagnostic\n' > obj/drawable_test
	expect 'compiled staging includes optional diagnostic' 0 bash -c "$settings
$copy_block
cmp obj/drawable_test root/bin/drawable_test"
	mv obj/hello_dyn obj/hello_dyn.saved
	expect 'staging still rejects absent required program' 1 bash -c "$settings
$copy_block
true"
	expect 'APFS producer failure is not hidden by tail' 23 bash -c "$settings
(exit 23) | tail -1
exit 0"
	cat > bin/timedatectl <<'SH'
#!/usr/bin/env bash
printf '%s' "${TEST_ZONE:-}"
exit "${TEST_ZONE_STATUS:-0}"
SH
	chmod +x bin/timedatectl
	expect 'unavailable timedatectl preserves UTC fallback' 0 env PATH="$PWD/bin:$PATH" TEST_ZONE_STATUS=1 \
		bash -c "$settings
$zone_block
test \"\$zone\" = UTC"
	expect 'available timedatectl preserves host timezone' 0 env PATH="$PWD/bin:$PATH" TEST_ZONE_STATUS=0 \
		TEST_ZONE=Europe/Paris bash -c "$settings
$zone_block
test \"\$zone\" = Europe/Paris"
else
	printf 'SKIP userland staging checks: run common/setup.sh to include them\n'
fi
printf '%s passed, %s failed\n' "$passed" "$failed"
[ "$failed" = 0 ]
