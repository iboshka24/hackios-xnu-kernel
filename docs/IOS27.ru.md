# iOS 27: подготовка настоящего userland и проверка первого ABI-барьера

**Статус: подготовка компонентов и exec probe реализованы. Загрузка полного iOS 27
не реализована: нынешнее ядро отклоняет launchd с errno 86.**

## Что сделано

```text
IPSW Apple 27.0.1 / 24A446 / iPhone19,2
 -> HTTP Range: ZIP64 directory + BuildManifest + Restore.plist
 -> RecoveryOS AEA + KernelCache (без скачивания всего IPSW)
 -> AEA decryption через ipsw и публичный Apple FCS endpoint
 -> настоящие /sbin/launchd, /usr/lib/dyld, SystemVersion.plist
 -> собственный APFS probe с этими неизменёнными Mach-O
 -> существующий XNU в QEMU -cpu max
 -> mount прошёл, exec /sbin/launchd отклонён: errno 86
```

Это не имитация терминала и не переименование образа iOS 16.5 в iOS 27.
Изменение CPU subtype в Apple файлах не производится. RecoveryOS не выдаётся
за полный системный rootfs со SpringBoard.

## Зафиксированная прошивка

Источник каталога: `https://api.ipsw.me/v4/device/iPhone19,2?type=ipsw`.
Сам архив и компоненты скачиваются с Apple CDN; URL, размер и каталоговый SHA256
зафиксированы в userland-файле `ios27/target.json`.

| Поле | Значение |
|---|---|
| Product | `iPhone19,2`, board `v63ap` |
| ProductVersion / build | `27.0.1` / `24A446` |
| Размер всего IPSW | 12 761 486 095 bytes |
| BuildManifest SHA256 | `6a47f58c7bff3e1378d1caf8b03b3b2940cc0ab7f0a6a4116c4fcaa718f608c0` |
| Customer Erase rootfs | `043-69473-662.dmg.aea`, 9 261 023 232 bytes |
| System cryptex | `043-70107-711.dmg.aea`, 2 348 810 240 bytes |
| RecoveryOS, identity 4 | `043-69851-764.dmg.aea`, 251 658 240 bytes |
| KernelCache | `kernelcache.release.v6x-pandia`, 23 847 493 bytes |

Metadata inventory потребовал **96 356 bytes** HTTP Range данных. Первое получение
RecoveryOS и kernelcache вместе с метаданными — **275 581 654 bytes**.
Повторный запуск проверяет локальные компоненты по ZIP size/CRC и вычисляет SHA256,
не скачивая их заново. Каталоговый SHA256 **всего IPSW не проверен**, потому что
весь архив не скачивался; отчёт прямо сохраняет `full_ipsw_sha256_verified=false`.

Полученные SHA256:

```text
2b3acdffc18e939682831347413e1c232ec4869a9878a03ec302a0222a238729  RecoveryOS AEA
ce84f1d4f833d8a92a08f82f24f1d89d990d6f380870f08b60627ef45f7f6b33  KernelCache IM4P
5b64712e4cdd030aeac81a69fd34f69f16715174aa62a25d2c0ab6a10a2143bc  APFS exec probe
```

Декомпрессированный kernelcache сообщает:

```text
Darwin Kernel Version 27.0.0: Thu Aug 13 21:41:52 PDT 2026; root:xnu-13432.2.10~2/RELEASE_ARM64_T8160
```

Это версия исследованного Apple kernelcache. QEMU в проверке по-прежнему запускает
отдельное портированное XNU 8796; наличие kernelcache не делает его совместимым с virt.

## Наблюдаемый ABI

`SystemVersion.plist`: `27.0.1`, `24A446`, `ReleaseType=Darwin Recovery`.

| Файл | Размер | Mach-O CPU subtype | LC_BUILD_VERSION |
|---|---:|---|---|
| `/sbin/launchd` | 639 360 | `0x8000000c`, ARM64e_X1 | platform iOS, minimum/SDK 27.0.0 |
| `/usr/lib/dyld` | 1 430 544 | `0x8000000c`, ARM64e_X1 | platform iOS, minimum/SDK 27.0.0 |

launchd требует `/usr/lib/dyld` и содержит 705 chained imports. Оба файла содержат
chained-fixup layouts с page size 16 384 и pointer format 12. CPU subtype 12
и fixup pointer format 12 — **разные поля разных форматов**, не взаимозаменяемые числа.
`ios27/abi.py` разбирает заголовки/layouts, но не утверждает, что реализует bindings,
PAC или runtime Apple.

Текущий kernel собран для обычного ARM64. Поддержка дополнительных CPU инструкций
через `-cpu max` проверена отдельным успешным запуском прежнего ARM64 hello
(`out/qemu-smoke-c0t3q4up`). Тот же выбор CPU не устраняет process ABI checks ядра.

Реальная попытка запуска Apple launchd из probe image
(`out/qemu-smoke-m7n8scax/serial.log`):

```text
apfs: volume 0 "iOS27Probe" of container 0 (at 0 MB): 2 files, 7 directories, 512 blocks of 4096 used
load_init_program: attempting to load /sbin/launchd
load_init_program: failed loading /sbin/launchd: errno 86
panic(...): Process 1 exec of /sbin/launchd failed, errno 86
```

Это `EBADARCH`, не отсутствие файла и не timeout. Новый режим runner `exec-probe`
выделяет такой результат как `exec_rejected_bad_arch`, сохраняет `exec_errno=86`
и возвращает ненулевой status. Он не превращает ожидаемый отказ в «iOS boot passed».

## Воспроизведение на текущем Windows host

Из корня объединённого checkout, с обоими репозиториями на ветке
`research/portability-baseline`:

```powershell
$python = 'C:\Users\ibrohim\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\python.exe'
$tools = 'C:\Users\ibrohim\AppData\Local\Temp\opencode\hackios-tools'
& $python ios27/fetch.py
& $python ios27/fetch.py --identity 4 --component OS --component KernelCache --output ios27/artifacts/recovery
& $python ios27/prepare.py --ipsw-tool "$tools\ipsw\ipsw.exe" --sevenzip "$tools\7zip\7z.exe"
```

Последняя команда печатает новый `out/ios27-core-*/core.json`. Проверка уже
созданного в этой итерации образа:

```powershell
& $python qemu/runner.py --mode exec-probe --cpu max --ramdisk out/ios27-core-ea496fgf/probe.apfs --qemu "$tools\qemu\qemu-system-aarch64.exe" --firmware "$tools\qemu\share\edk2-aarch64-code.fd" --seconds 60
```

После нового prepare используйте путь из его собственного core.json, а не имя
старого временного каталога. Probe содержит только launchd и dyld, **не shared
cache и не frameworks**: он проверяет первый барьер exec, а не полноту системы.

Использованы Python 3.13, 7-Zip 26.05, QEMU 11.1.0 и
[blacktop/ipsw 3.1.739](https://github.com/blacktop/ipsw/releases/tag/v3.1.739).
Windows archive ipsw проверен по опубликованному checksums.txt перед распаковкой.
Расшифровка AEA использовала pure-Go реализацию ipsw и публичный FCS URL Apple;
ручные ключи или jailbreak не использовались.

## Проверки и границы реализации

```powershell
& $python -m unittest discover -s ios27 -p 'test_*.py' -v
& $python -m unittest discover -s qemu -p test_runner.py -v
```

В ios27 tests проверяются строгий HTTP 206/Content-Range, обрезанные ответы,
изменение ETag, границы чтения, точный product/build, ZIP duplicates, сохранность
существующих файлов, CRC reuse, Mach-O bounds, unknown subtypes, fixup layouts,
SystemVersion и реальная сборка APFS на синтетических данных. Реальные Apple
компоненты нужны только локальной интеграционной проверке, не unit tests.
На этой итерации проходят **21 ios27 test**, **13 runner tests** и прежние
**13 shell regressions**. Реальный exec-probe возвращает отказ, как указано выше,
и не включается в число успешных загрузок.

`ios27/artifacts/` и `out/` не входят в коммиты. В Git добавлены собственные
скрипты, тесты и target metadata, не Apple executables, DMG, IPSW или FCS keys.
База iOS 16.5 и её fetch/build scripts не переписаны под несовместимые новые образы.

### Что требуется до настоящего boot iOS 27

1. Реализовать и проверить process ABI ARM64e_X1 в используемом kernel/CPU stack:
   admission, pointer authentication, thread state, commpage и shared-region semantics.
   Просто разрешить subtype в grade_binary недостаточно.
2. Обеспечить загрузку реального dyld, chained fixups и shared cache нового формата;
   подтвердить исполнение первым system process, а не изменением заголовка Mach-O.
3. Подготовить полный rootfs, cryptexes, frameworks и launchd jobs, затем последовательно
   пройти launchd -> backboardd -> SpringBoard с отдельной проверкой IOKit/Metal API.

Ни один из этих трёх пунктов не помечен реализованным этим preparation commit.

## Найденный опубликованный путь и проверка более старого устройства

Проверен исходный код [Lakr233/vphone-cli](https://github.com/Lakr233/vphone-cli)
на commit `2279ecb313d6607310755a66dce7f7c9a82e51a7` от 23.10.2026.
В [матрице совместимости](https://github.com/Lakr233/vphone-cli/blob/2279ecb313d6607310755a66dce7f7c9a82e51a7/Documents/Guides/compatibility.md)
авторы фиксируют успешную загрузку **iPhone19,2 / 27.0.1 / 24A446** на M5 Max
с cloudOS 26.4 `23E5207q`: Settings, Safari и Calculator запускаются.
Это опубликованный результат авторов, не локальный boot на нашем Windows.

Реализация состоит не из одного изменения subtype:

- `KernelCustomFirmwarePatchArm64eX1.swift`: grading, exec PAC и authenticated shared-region gates.
- `VPhoneArm64eX1Lowering.swift`: PAuth_LR -> SP-only forms, CPA -> обычная арифметика.
- `CustomFirmwareArm64eX1.swift`: обход кода bootstrap closure и учёт непосещённых кандидатов.
- Статическая обработка dyld/launchd, 38 cache images и runtime exception service.

Базовое ядро vphone600 уже поддерживает обычный ARM64e. Lowering уменьшает
PC-bound PAC/CPA гарантии и не воспроизводит аппаратную защиту X1.
Версию 27.1 подставлять нельзя: у авторов есть отдельный неудачный Duo bring-up
с неподдержанными CSSC instructions.

[Host requirements](https://github.com/Lakr233/vphone-cli/blob/2279ecb313d6607310755a66dce7f7c9a82e51a7/Documents/Guides/host-setup.md):
Apple Silicon Mac, macOS 15+, Virtualization.framework и research-guest admission.
Nested macOS VM не поддерживается. В нашем Windows QEMU 11.1 отсутствует vmapple
machine; запуск Mac-only vphone-cli здесь не подтверждён и не заявляется.
Настройки SIP, AMFI и NVRAM текущей машины не менялись.

Команда документированного Mac backend после успешного host preflight:

```bash
vphone-cli host preflight
vphone-cli vm create ios27 \
  --iphone-source 'https://updates.cdn-apple.com/2026FallFCS/8cd333d4-1025-4e89-99a2-1373d2b5bfcb/iPhone19,2_27.0.1_24A446_Restore.ipsw' \
  --cloudos-source 'https://updates.cdn-apple.com/private-cloud-compute/c0ecdb4b310cf5239ab2b248dd3098eec297dc5aa3bbe6ada27273262b0b8b64'
vphone-cli vm launch ios27
```

### Локальная проверка iPhone 12 вместо X1

Добавлен `ios27/target-iphone12.json`: `iPhone13,2`, `d53gap`, тот же build 24A446.
У него в проверенном IPSW нет RecoveryOS identity. Поэтому извлечён **RestoreRamDisk**
`043-69915-784.dmg`, 243 269 659 bytes, распакован IM4P и проверен SystemVersion:
`27.0.1`, `24A446`, `ReleaseType=Restore`.

Оба настоящих launchd/dyld имеют обычный `arm64e`, subtype `0x80000002`, без X1.
Их APFS probe **тоже отклонён нынешним XNU с errno 86**
(`out/qemu-exec-probe-iew9jm_6/report.json`). Следовательно, X1 не единственный
барьер: переход на более старый iPhone не заменяет ARM64e kernel support.
Это сужает направление работ до PAC-capable kernel baseline либо явной реализации
ARM64e ABI, а не ещё одной замены имени устройства.

```powershell
& $python ios27/fetch.py --target ios27/target-iphone12.json --identity 0 --component RestoreRamDisk --output ios27/artifacts/iphone12
& $python ios27/prepare.py --target ios27/target-iphone12.json --component RestoreRamDisk --cache ios27/artifacts/iphone12 --ipsw-tool "$tools\ipsw\ipsw.exe" --sevenzip "$tools\7zip\7z.exe"
```

Обычный ARM64 smoke с `-cpu max` проходит, тогда как оба Apple ARM64e probes
отклонены. UniXNU `1a01c2afa197d975d04da892325c56b6b14aaecb` также описывает
такой `EBADARCH` на Surface Duo 2 и не содержит готового решения X1 для нашей базы.

## Восстановленная функция из kernelcache iOS 27

В `ios27/reconstructed/` userland-форка добавлена C-реконструкция функции оценки
ARM64/ARM64e/X1. Имя `ml_grade_binary` установлено по соответствию публичному
XNU и control flow; в исследованном бинарнике символ удалён.

Восстановлено поведение **204 bytes / 51 instructions** по адресу
`0xfffffe000b2936f8` в kernelcache 27.0.1. C-код собран в DLL и сравнен
с исполнением неизменённых ARM64 bytes в Unicorn: **33 478 cases, 0 mismatches,
51/51 instructions covered**. TPIDR_EL1 и прочитанная per-CPU память заданы harness.
Это не проверка на реальном Apple CPU и не формальное доказательство на всех входах.

Код и воспроизводимая процедура:
[ios27/reconstructed](https://github.com/iboshka24/hackios-xnu-userland/tree/research/portability-baseline/ios27/reconstructed).
Реальная assembly и результаты — локально в `out/reconstructed-ios27/`.
Оригинальные исходники, остальные функции iOS и поддержка boot этим не восстановлены;
модель не встроена в существующий XNU и не меняет его grading/PAC поведение.
