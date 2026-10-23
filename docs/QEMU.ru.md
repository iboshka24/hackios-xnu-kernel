# Portable QEMU: XNU smoke без IPSW

## Реализовано

`qemu/runner.py` запускает QEMU прямо из Python под Windows, без WSL, Bash,
GNU timeout, sparse-файла на 12 GB и `copy_file_range`. Используются настоящий
UEFI loader, настоящее XNU и статическая Mach-O программа проекта.

Четыре режима:

- **smoke**: `prebuilt/userland/hello` становится `/sbin/launchd` через mockfs,
  выполняет системные вызовы и печатает PID/UID. Apple userland не нужен.
- **apfs-smoke**: тот же собственный executable помещается в настоящий APFS
  container посредством имеющегося `tools/apfs/mkapfs.py`. Manifest задаёт
  Unix permissions независимо от Windows filesystem. Для pass дополнительно
  требуется строка kernel log о монтировании тома `Smoke`.
- **exec-probe**: принимает явно заданный APFS image и сохраняет реальную
  ошибку exec PID 1, включая `exec_rejected_bad_arch` для errno 86. Не объявляет
  image загруженной iOS при нулевом коде самого QEMU; подробнее в [IOS27.ru.md](IOS27.ru.md).
- **ios**: подключаются настоящие локальные `root.apfs` и `system.apfs`.
  Сам runner их не генерирует и не подменяет имитацией SpringBoard.
  Этот режим в данной итерации не запускался.

Каждый запуск создаёт отдельный `out/qemu-*/` с `serial.log`, `report.json`,
payload и EFI system partition. В отчёт входят команды, SHA256 всех входов,
версия QEMU, elapsed time, код выхода и отдельный признак host timeout.
NIC отключён; TCP monitor не открывается; физические диски не подключаются.

`smoke_userspace_pass` требует **обеих** строк из serial log:

```text
Hello from user space on Darwin!
I am process 1, uid 0, console fd 0.
```

Для iOS режима результат `session_completed` означает только код QEMU 0.
Поля `ios_ui_validated` и `gpu_acceleration_validated` остаются false:
наличие имени SpringBoard в логе не считается проверкой UI.

## Настоящий запуск 23.10.2026

Host — Windows x86-64; QEMU 11.1.0, `virt,gic-version=3`, Cortex-A76, TCG,
один vCPU. Guest address space — 3 GiB; `maxmem=256` ограничивает управляемую
XNU память. Адрес payload `0xF0000000` не позволяет просто уменьшить QEMU RAM
до 256 MiB. В этой конфигурации запущен smoke, не SpringBoard.

| Loader | Запуск | Время процесса, секунд | Результат |
|---|---|---:|---|
| Исходный prebuilt | `qemu-smoke-fyuqu88i` | 13.614 | PID 1/uid 0; панель осталась 800x600 |
| Пересобранный | `qemu-smoke-mveqs3am` | 14.197 | PID 1/uid 0; панель 1125x2048 |
| Тот же пересобранный, cold boot | `qemu-smoke-phjf8xoy` | 11.776 | PID 1/uid 0 |
| Тот же пересобранный, cold boot | `qemu-smoke-v5okwj4r` | 11.571 | PID 1/uid 0 |

Это времена завершения smoke-процесса QEMU, **не FPS, не benchmark iOS и не
время загрузки SpringBoard**. Все четыре запуска завершились с кодом 0 без host timeout.

Отдельно выполнен реальный **APFS smoke**: `qemu-apfs-smoke-vblglle1`,
14.612 секунды, exit 0, без host timeout. Python builder создал container
размером 4 MiB, kernel смонтировал его и выполнил `/sbin/launchd` из этого тома:

```text
apfs: volume 0 "Smoke" of container 0 (at 0 MB): 1 files, 6 directories, 10 blocks of 4096 used
Hello from user space on Darwin!
I am process 1, uid 0, console fd 0.
```

SHA256 этого APFS fixture:
`ab82050d66f196f67df3d66ccc48f4bdbc9df6845f737aa83cb2d0a61c944691`.
Синтетический вход здесь — собственная программа проекта; mount, чтение
исполняемого файла и системные вызовы выполнены настоящим XNU внутри QEMU.

Наблюдение до исправления:

```text
ramfb: control 250018 after the request
display 800 x 600 at fc7a0000
MiniIOMobileFramebuffer: display 1125x2436 on a panel of 800x600 (3200 bytes per row)
```

После пересборки:

```text
display 1125 x 2048 at fbba6000
MiniIOMobileFramebuffer: display 1125x2436 on a panel of 1125x2048 (4500 bytes per row)
Hello from user space on Darwin!
I am process 1, uid 0, console fd 0.
```

Физический адрес framebuffer меняется между boot и не является константой API.
Программа `hello` намеренно вызывает exit для PID 1. Последующий
`panic: initproc failed to start` ожидается её исходным кодом; это не успешный
запуск Apple launchd и не ошибка, скрытая под утверждением о загрузке iOS.

## Исправление ramfb

`xnuloader/ramfb.h` задаёт панель 1125x2048 в пределах QEMU bochs-vbe limits.
Логическое разрешение iOS остаётся 1125x2436; существующий kernel display driver
масштабирует его в панель.

DMA control читается как volatile после барьера записи. Вместо однократного
чтения loader ожидает завершения до 100 интервалов по 100 микросекунд.
Ошибка и timeout диагностируются раздельно; SCREEN обновляется только после
нулевого completion status. Это устраняет наблюдавшееся преждевременное чтение.
При timeout незавершённой DMA выделенный buffer не освобождается под устройством;
позднее завершение и восстановление после такого timeout отдельно не проверены.

В `tools/ramfb_test.c` настоящий helper проверяется **симулированным fw_cfg**:
немедленное завершение, отложенное завершение, error, timeout, завершение на
последнем интервале и ограничения размеров. Это host-тест механизма ожидания,
не симуляция всего GPU. Дополнительно исправленный loader реально загрузил XNU
в трёх отдельных QEMU процессах.

Проверенный binary включён отдельно как `prebuilt/loader-qemu.efi`:

```text
204b39dc405d7e21743b3b5d792bc1e5ae97369ef4d5dce6388f31b8a1a09803
```

Исходный `prebuilt/loader.efi`, используемый телефонным сценарием, не заменён.
Python runner и shell QEMU runner выбирают локальную сборку loader, затем
QEMU prebuilt, затем старый prebuilt как последний fallback.

## Запуск на текущем компьютере

Команды выполняются из корня объединённого checkout HackiOS.

Инструменты распакованы в пользовательский temporary каталог, без изменения
глобального PATH, установки служб или включения системной виртуализации:

```powershell
$python = 'C:\Users\ibrohim\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\python.exe'
$tools = 'C:\Users\ibrohim\AppData\Local\Temp\opencode\hackios-tools'
& $python qemu/runner.py --qemu "$tools\qemu\qemu-system-aarch64.exe" --firmware "$tools\qemu\share\edk2-aarch64-code.fd" --seconds 60
```

Для явной проверки включённого QEMU prebuilt добавьте
`--loader prebuilt/loader-qemu.efi`; для сравнения со старым —
`--loader prebuilt/loader.efi`.

Для создания и загрузки APFS fixture добавьте `--mode apfs-smoke`.
Построенный образ остаётся в каталоге запуска как `smoke.apfs`.

Дистрибутив QEMU:
[qemu-w64-setup-20260811.exe](https://qemu.weilnetz.de/w64/2026/qemu-w64-setup-20260811.exe).
Перед распаковкой проверен SHA512:

```text
5bcf9eed634e8575a37b74f445af41a2fe4106da512d0c30c368301d4c105037fdfab40a5287367a28a957624cddebbc8c07e16c88ab6634f554cdf3d16bf543
```

Для нового компьютера достаточно Python >=3.10, QEMU aarch64, его UEFI firmware,
двух checkout проекта и явных `--qemu`/`--firmware`. Папка временных инструментов
на текущем компьютере может быть очищена Windows, она не является частью Git.

## Сборка loader и тестов в использованной Windows-среде

Использован Zig 0.17.0 (Clang frontend) и существующий Rust LLD. Оба являются
host-инструментами; компилируется freestanding AArch64 UEFI приложение без SDK Apple.
Дополнительный `el3` разрешает ассемблеру SMC-инструкции телефонной ветки loader;
QEMU путь по-прежнему выбирает платформу virt.

```powershell
$tools = 'C:\Users\ibrohim\AppData\Local\Temp\opencode\hackios-tools'
$zig = "$tools\zig\zig-x86_64-windows-0.17.0\zig.exe"
$linker = 'C:\Users\ibrohim\.rustup\toolchains\stable-x86_64-pc-windows-msvc\lib\rustlib\x86_64-pc-windows-msvc\bin\rust-lld.exe'
& $zig cc --target=aarch64-windows-gnu -mcpu=generic+el3 -ffreestanding -fno-builtin -fno-stack-protector -fshort-wchar -mgeneral-regs-only -O1 -Wall -Wextra -Wno-unused-parameter -c xnuloader/loader.c -o xnuloader/loader.obj
& $linker -flavor link /subsystem:efi_application /entry:efi_main /nodefaultlib /base:0xA1000000 /out:xnuloader/loader.efi xnuloader/loader.obj
& $zig cc -std=c11 -Wall -Wextra -Werror tools/ramfb_test.c -o out/ramfb_test.exe
& .\out\ramfb_test.exe
& $python -m unittest discover -s qemu -p test_runner.py -v
```

Итог второй итерации: **11 Python tests**, **13 shell regressions**,
**6 сценариев DMA/mode validation** проходят. Loader также отдельно
скомпилирован с `-Wall -Wextra -Werror -Wno-unused-parameter`.
Проверка APFS builder использует синтетические bytes и сравнивает два независимо
построенных образа; выполнение собственного Mach-O подтверждено отдельным QEMU boot.
Новые iOS 27 проверки и exec-probe описаны отдельно в [IOS27.ru.md](IOS27.ru.md).

Zig archive: `https://ziglang.org/download/0.17.0/zig-x86_64-windows-0.17.0.zip`,
проверенный SHA256:
`b5663f69581dcf391293fbf16c06cb80d81d806545ce618b4d0bab7f0eb8c428`.
Обычная Linux сборка `xnuloader/build.sh` сохранена; в этой итерации она не выполнялась.

## Режим с настоящими iOS образами

```powershell
& $python qemu/runner.py --mode ios --qemu "$tools\qemu\qemu-system-aarch64.exe" --firmware "$tools\qemu\share\edk2-aarch64-code.fd" --ramdisk userland/root.apfs --system-image userland/system.apfs --memory-gib 7 --seconds 1200 --display gtk
```

Эта команда описывает реализованный режим, **не результат выполненного теста**.
Гостевой ABI пока остаётся iOS 16.5 baseline upstream. Нужны настоящие образы из
IPSW, достаточно host RAM и работающий display backend QEMU. Для ios запрещено
менее 7 GiB guest address space: иначе выбор loader memory window может не
совпасть с фиксированным адресом resident image. Даже корректный адрес и размер
образов не доказывают успешную загрузку их содержимого.

Новые телефонные порты, Metal acceleration, iOS 27 userland и jailbreak Calif
этими изменениями не реализованы и искусственными pass-результатами не заменены.
