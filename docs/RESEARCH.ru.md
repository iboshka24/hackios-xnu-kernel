# HackiOS: анализ исходников и план переносимости

Дата проверки публичных материалов: **23 октября 2026**.

**Результат этой итерации — два форка, исправления сборочных скриптов и проверенный
host-only стенд. Универсальный порт, новые GPU-драйверы и загрузка iOS 27 не реализованы.**

## 1. Исходные версии и история

| Компонент | Проверенный upstream commit | Ветка форка |
|---|---|---|
| [kernel](https://github.com/oosexgang/hackios-xnu-kernel) | `8e61187098f2c26c5daee8f9f72b6416aa64b9ab` | [iboshka24/kernel](https://github.com/iboshka24/hackios-xnu-kernel/tree/research/portability-baseline) |
| [userland](https://github.com/oosexgang/hackios-xnu-userland) | `a79ff0772a3454fd1ef127e181e5b3bce6c9ce18` | [iboshka24/userland](https://github.com/iboshka24/hackios-xnu-userland/tree/research/portability-baseline) |

Публичная история kernel на этой базе содержит два коммита: исходный релиз
`4ab189d`, затем лицензия `8e61187`. История userland содержит исходный релиз
`c5c92f6`, лицензию `b4c5513`, `fcc3214` с thermald/bootok и `a79ff07` с thermal_probe.
Это не полная история разработки до публикации: её из этих репозиториев восстановить нельзя.

Оба репозитория используют **одно рабочее дерево и два Git index**:
kernel — `.git`, userland — `.userland.git`. `common/setup.sh` не создаёт обычный
подкаталог-submodule; `common/ugit` адресует второй репозиторий. Корневые README,
LICENSE и .gitignore в рабочем дереве принадлежат kernel. Коммитить изменения
userland обычным `git add .` неправильно.

### Issues и PR на момент проверки

| Репозиторий | Материал | Значение для работы |
|---|---|---|
| kernel | [#4](https://github.com/oosexgang/hackios-xnu-kernel/pull/4) | Потеря ошибки image builder; тот же дефект независимо воспроизведён нашими тестами |
| kernel | [#5](https://github.com/oosexgang/hackios-xnu-kernel/pull/5) | `timeout --foreground`, остановка QEMU при работе с терминалом; в эту итерацию не включено |
| kernel | [#6](https://github.com/oosexgang/hackios-xnu-kernel/pull/6) | macOS/ARM: GNU/BSD utilities, copy_file_range, fw_cfg DMA; заявлена проверка автором PR, не нами |
| kernel | [#7](https://github.com/oosexgang/hackios-xnu-kernel/pull/7), [#8](https://github.com/oosexgang/hackios-xnu-kernel/pull/8) | NixOS shebang и проверка версии 7-Zip; не включены |
| kernel | [#9](https://github.com/oosexgang/hackios-xnu-kernel/pull/9) | Чёрный экран QEMU: высота ramfb и DMA completion; требуется отдельное воспроизведение |
| kernel | [issue #2](https://github.com/oosexgang/hackios-xnu-kernel/issues/2) | Зависание загрузки и entitlement-сообщения; одного лога недостаточно для диагноза |
| userland | [issue #1](https://github.com/oosexgang/hackios-xnu-userland/issues/1) | В prebuilt отсутствует drawable_test |
| userland | [#3](https://github.com/oosexgang/hackios-xnu-userland/pull/3), [#4](https://github.com/oosexgang/hackios-xnu-userland/pull/4), [#5](https://github.com/oosexgang/hackios-xnu-userland/pull/5), [#6](https://github.com/oosexgang/hackios-xnu-userland/pull/6) | Пересекающиеся исправления staging, UTC fallback, pipefail и macOS |

Статус PR не означает, что исправление присутствует в проверенном commit.
Здесь изменены только дефекты, которые удалось проверить локальным тестом.
Патчи PR #6 и #9 нельзя объединять вслепую: оба меняют обработку ramfb,
но ограничение размеров экрана и завершение DMA — разные условия.

## 2. Архитектура iOS 16.5 на HackiOS

База: XNU `8796.121.2`, Darwin `22.5.0`, конфигурация
`DEVELOPMENT_ARM64_BCM2837`. Это отдельное ядро с заменами драйверов, а не запуск
Apple kernelcache через Android kernel.

```text
телефон: fastboot boot -> Mu-Silicium UEFI -> xnuloader
QEMU:    aarch64 virt -> UEFI -> xnuloader
                           |
                     patched XNU
                           |
            /dev/md0: system.apfs, системный корень
                           |
         /sbin/launchd = собственный stage0, не Apple launchd
                           |
       /dev/md1: root.apfs -> /redwood -> /redwood/sbin/init
                           |
                 exec /sbin/launchd.ios
                           |
               backboardd -> SpringBoard -> приложения
```

Проверено по `userland/src/stage0.c`, `userland/rc.launchd`,
`userland/build.sh` и `qemu/run-ios.sh`.

| Слой | Файлы и механизм |
|---|---|
| Загрузчик | `xnuloader/loader.c`: выбор платформы, memory map, framebuffer, контейнер payload |
| CPU/IRQ | `xnu/files/osfmk/arm64/`: GICv3, timer, PSCI SMP, возврат в loader |
| Файловые системы | `xnu/files/bsd/miscfs/apfs/`, `ramfs/`; APFS-образы и writable `/private/var` |
| Системные ABI | MiniIOSurface, MiniIOMobileFramebuffer, MiniAppleKeyStore, минимальные MAC/AMFI реализации |
| Сервисы | `userland/mkjobs.py`, `jobinfo.py`, launchd plists; RC_JOBS интерпретирует собственный init |
| Инъекции | `inject.c` для backboardd, `inject_sb.c` для SpringBoard, `inject_media.c` для mediaserverd; список через `kern.exec_inject` |
| OpenGL ES | `userland/src/eagl.c`, `gl_osmesa.c`, Mesa 25.0.7, freedreno и собственный Darwin DRM shim |
| GPU kernel | `redwood_adreno.c`, `RedwoodGPU.cpp`: firmware, память, очередь, msm-подобный user client |
| Звук | RedwoodAudio в mediaserverd; ADSP на телефоне, virtio-sound в QEMU |
| Сеть | WCN6750/ath11k через LinuxKPI на redwood; virtio-net в QEMU |
| Ввод | Goodix GT9916 на redwood; virtio-input в QEMU |

IPSW зафиксирован upstream на iPhone X, iOS 16.5, build `20F66`,
`iPhone10,3`/`iPhone10,6`, с arm64 dyld cache. `ios165/fetch-from-ipsw.py`
читает ZIP64 через HTTP Range с Apple CDN; это не загрузчик произвольного IPSW.
Замена номера версии в URL не переносит manifest, cryptex, ABI и набор сервисов.

## 3. GPU: что действительно означают числа

В README осталось **293/456**. В зафиксированных
[`docs/air-report.md`](https://github.com/oosexgang/hackios-xnu-userland/blob/a79ff0772a3454fd1ef127e181e5b3bce6c9ce18/docs/air-report.md)
и [`docs/air.md`](https://github.com/oosexgang/hackios-xnu-userland/blob/a79ff0772a3454fd1ef127e181e5b3bce6c9ce18/docs/air.md)
уже другая картина:

| Измерение upstream | Число | Чего оно не доказывает |
|---|---:|---|
| Прочитано модулей корпуса | 456 | Корректность исполнения |
| Entry points переведены в NIR и скомпилированы ir3 | 321: 271 fragment + 47 compute + 3 vertex | Успешный GPU fence или правильные пиксели |
| Остальные модули | 135 `air.visible` | Это библиотечные функции, не «135 недописанных entry points» |
| Численно проверено и нарисовано, по вводной таблице air.md | 255 | Полную Metal API-совместимость приложения |
| Завершённое выполнение на телефоне, по вводной таблице air.md | 30: 7 draw + 23 compute | Актуальный итог всех более поздних экспериментов в длинном документе |

В `air.md` сохранены старые и последующие, местами противоречащие друг другу
результаты. Например, введение говорит, что Metal runtime ещё не начат, но в
`userland/src/redwoodmetal.m` уже есть device, buffer, compute/render paths,
argument buffers и ограничения offsets. В этом же файле явно перечислены пробелы:
heaps, blit encoders, events, multisample resolve и rectangle-часть viewport.
Поэтому ни вводную таблицу, ни текст README нельзя выдавать за свежий hardware census.

**Задача «дописать оставшиеся 163» некорректна как единица работы.** Нужны
раздельные результаты: parser, NIR validation, backend compile, reference compare,
GPU completion, корректный readback, Metal API и presentation.

Уже присутствуют патчи `ir3-round-default.patch`, `ir3-ssbo-subdword.patch` и
`ir3-shift-split.patch`. Их нельзя заменять обещанием «интегрировать freedreno»:
интеграция уже есть, её нужно сохранять и измерять. Неверные структурированные
входы compute kernels могут давать бесконечные циклы; случайный buffer не является
валидным тестовым изображением или списком spans.

### QEMU и другие GPU

Текущий запуск использует `ramfb` и TCG; в просмотренном kernel/platform коде
не найден реализованный путь virtio-gpu/VirGL. Добавление `-device virtio-gpu`
не создаёт гостевой драйвер или Metal runtime.

VirGL — виртуализация графического API через host renderer, **не PCI passthrough**.
Отдельно нужны virtqueue/resource/fence transport в XNU, соответствующий Mesa
winsys, IOSurface integration и presentation. Venus для Vulkan — другая ветка
реализации, не переключатель freedreno. На Apple Silicon аппаратная виртуализация
CPU сама по себе также не предоставляет гостю Apple GPU.

Для Adreno 6xx/7xx переносится часть Mesa/ir3, но не автоматически MMIO, GMU,
clocks, firmware, SMMU stream IDs и reset. Для Mali нужны другой kernel backend
и подходящий Mesa driver; Linux Panfrost/Panthor ABI в XNU отсутствует по умолчанию.

Полезная отдельная реализация:
[UniXNU NativeAdreno](https://github.com/UniXNU/NativeAdreno),
[NativeMetal](https://github.com/UniXNU/NativeMetal),
[ArmSmmu4K](https://github.com/UniXNU/ArmSmmu4K),
[описание A740](https://unixnu.com/drivers/native-adreno).
По документации UniXNU, A740 путь использует BO/VM/ring/fences, native 4 KiB SMMU,
AIR -> SPIR-V -> NIR -> ir3 и scanout. Это источник архитектурных сравнений,
а не совместимый с HackiOS drop-in driver. На этом стенде он не собирался.

## 4. Calif.io и iOS 27

Проверенные материалы:

1. [Calif, «iPhone», 16.10.2026](https://blog.calif.io/p/iphone) — первичная
   публикация четырёх демонстраций; «Everything will be released in due time».
2. [Публичный thread Calif](https://x.com/calif_io/status/2111080240978223545) —
   ссылка на видео из проверенной статьи heise; напрямую видео здесь не анализировались.
3. [heise, 19.10.2026](https://www.heise.de/en/news/Calif-io-jailbreak-How-the-untethered-tool-cracks-iOS-27-0-1-11492321.html) —
   интервью/репортаж: untethered, MIE/EMTE, возможный будущий PoC, без end-user tool.
4. [Apple: архитектура MIE](https://security.apple.com/blog/memory-integrity-enforcement/) —
   typed allocators, synchronous EMTE, tag confidentiality; это не описание бага Calif.

По доступным проверенным материалам **не установлены** CVE и точные баги цепочки,
примитив обхода MIE, механизм persistence, надёжность и полный список устройств.
Публичный воспроизводимый PoC этой цепочки и технические слайды не найдены.
Сообщение о bypass из репортажа не определяет, какой компонент EMTE был нарушен.
Не связываем с этой цепочкой другие CVE Calif без прямого подтверждения.
Модель SoC демонстрационного iPhone не выводится из общей статьи Apple о MIE.

### Почему jailbreak не равен порту userland

Jailbreak Apple-устройства и исполнение Apple userland на своём XNU — разные задачи.
При загрузке собственного ядра на Android не требуется получать root в штатном
Apple kernel посредством MIE exploit. Требуется реализовать ожидаемую семантику.

Для iOS 27 сначала необходимы точный build/product и локально извлечённые:
BuildManifest, Mach-O CPU subtypes, dyld cache/closures, cryptex layout и launchd jobs.
Затем сравниваются syscall/Mach trap ABI, commpage, page size, IOKit selectors,
ObjC/Swift runtime dependencies, кодировки chained fixups и PAC/arm64e requirements.
Чип Snapdragon 778G и QEMU `cortex-a76` не становятся совместимыми с любыми
Apple-specific инструкциями после замены offsets. Новый XNU baseline выбирается
по фактическому build, а не по совпадению маркетингового номера iOS с Darwin.

Последовательность bring-up: собственная минимальная Mach-O программа -> dyld ->
один служебный процесс -> launchd -> backboardd -> SpringBoard. Для каждого этапа
нужны код возврата, exception state и список отсутствующих ABI, а не флаг
«iOS27 supported». В этой итерации образы iOS 27 не извлекались и не запускались.

### Аудит и фаззинг при отсутствии опубликованных деталей

Это план проверки ошибок, не восстановленная цепочка Calif:

- Зафиксировать версии открытого XNU и локальных parsers; составить карту
  доступных source-to-input boundaries и инвариантов размеров/lifetimes.
- Для собственных APFS, ZIP64, metallib/AIR parsers выделить host harness,
  применять ASan/UBSan и coverage-guided mutation на минимальном корпусе.
- Проверять truncation, переполнения длины/offset, несогласованные counts,
  индексы вне таблиц, глубину вложенности; ограничивать память и время одного input.
- Сохранять hash входа, seed, build flags, stack и sanitizer report; минимизировать
  crash и добавлять regression test до исправления.
- Для свойств MIE использовать воспроизводимые instrumented tests на среде,
  реально поддерживающей требуемые теги и fault semantics. Обычный ASan crash
  на x86 не подтверждает ни bypass EMTE, ни возможность построить jailbreak.

В этой итерации новые уязвимости MIE не найдены и exploit не разработан.

## 5. Поддержка и ограничения

| Цель | Заявлено upstream | Проверено в этом форке |
|---|---|---|
| POCO X5 Pro / redwood | iOS 16.5 UI, Adreno GLES, touch, Wi-Fi, sound, camera | Только профиль/исходники; hardware run отсутствует |
| QEMU virt / Linux x86-64 | iOS 16.5 UI, ramfb, virtio input/net/sound | Host-only tests; guest boot отсутствует |
| macOS / Apple Silicon host | Публичные PR с заявленной загрузкой QEMU | Не интегрировано и не проверено нами |
| Другие Adreno 6xx/7xx устройства | Требуют board port | Нет новых поддерживаемых устройств |
| Mali | Нет готового пути в исследованной базе | Не реализовано |
| iOS 27.x | Нет порта в исследованной базе | Не реализовано |

Ограничения upstream: cellular, Bluetooth, зарядка под XNU, полный Metal для
приложений, Apple ID/App Store/FairPlay, отсутствие настоящего Secure Enclave,
video/Live Photo recording. MiniAppleKeyStore не заменяет криптографическую
идентичность SEP и не решает FairPlay. Рабочая камера не означает рабочую запись видео.

Procursus, Sileo, dpkg/apt, SSH и tweaks уже предусмотрены `tools/mk-jb.sh`,
`userland/build.sh` и `inject_tweaks.c`; создавать второй bootstrap не требуется.
Для теста нужны фактические пакеты, настройки SSH-ключа и проверка writable prefix.
checkm8/palera1n относятся к отдельной старой Apple hardware boot chain;
их совместимость не следует из ARM64 userland и здесь не проверялась.

RAM-only режим не должен включать `ufs_write=1`, `var_store=1` или flash-root
процедуры без отдельного тест-плана: они уже меняют модель сохранности данных.
При неработающей зарядке аппаратный GPU тест ограничивается зарядом и температурой.

## 6. План реализации с критериями завершения

| Этап | Работа | Условие приёмки | Статус |
|---|---|---|---|
| P0 | Два форка, воспроизводимые wrapper/staging ошибки, минимальные исправления | 13 host tests проходят; diff не содержит IPSW/SDK/firmware | Выполнено |
| P1 | Linux стенд и iOS 16.5 baseline; отдельно проверить ramfb/timeout PR | Три холодных boot, SpringBoard screenshot, управляемый ввод, crash log | Заблокировано отсутствием Linux/QEMU |
| P2 | GPU census с реальными входами, fences и reference readback | Manifest корпуса + результаты каждой стадии, ни один skip не назван pass | Не начато |
| P3 | Metal runtime: реально используемые незакрытые API, stitching, presentation | Минимальное приложение и системный compositor проходят один набор pixel tests | Не начато |
| P4 | Второй Qualcomm board с измеренным DTB, firmware и SMMU | Loader -> kernel -> input/framebuffer -> UI; затем GPU/net/audio по отдельности | Нет DTB и hardware run |
| P5 | QEMU virtio-gpu transport + Mesa backend | Реальный host renderer, завершённый fence и пиксели в scanout | Не реализовано |
| P6 | Mali board/backend | Корректные BO mappings, reset/fence и тот же набор API/pixel tests | Не реализовано |
| P7 | iOS 27 ABI inventory и поэтапный userland bring-up | Сначала dyld/launchd, затем UI; отдельная матрица от iOS 16.5 | Нет извлечённого build и ABI inventory |

Этапы P2/P3 не принимаются по проценту скомпилированных шейдеров. P4 не принимается
по одному сгенерированному `.conf`. P5 не принимается по наличию QEMU CLI-флага.
Команды и результаты фактически выполненной проверки — в [VALIDATION.ru.md](VALIDATION.ru.md).
