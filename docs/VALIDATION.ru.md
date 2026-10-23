# Проверка portability baseline

## Выполнено локально

Host: Windows, Git for Windows Bash. Доступны Git и GitHub CLI. `common/setup.sh`
собрал объединённое рабочее дерево двух репозиториев. Доступная WSL-команда
не предоставила работающий Linux-дистрибутив. QEMU, gcc, clang/lld-link, adb,
fastboot и iPhoneOS16.5 SDK в проверенном PATH/стандартном месте отсутствуют.

До правок `bash tools/common-test.sh`: **8 passed, 5 failed**.
После правок той же проверкой: **13 passed, 0 failed**.

| Проверка | Ожидание после исправления |
|---|---|
| Image builder возвращает 23 | `common/build.sh` завершает работу с ошибкой 1 и диагностикой |
| Image builder успешен | Wrapper возвращает 0 |
| Emulator возвращает 42 | `common/run.sh` возвращает 42 через pipeline с tee |
| Emulator успешен | Wrapper возвращает 0 |
| Writer лога возвращает 73 | Wrapper возвращает 73 |
| Неизвестный device | Ошибка до запуска сборки |
| Нет root.apfs | Ошибка до запуска emulator |
| Нет необязательного drawable_test | Staging prebuilt проходит |
| drawable_test присутствует | Диагностика копируется с неизменным содержимым |
| Нет обязательного hello_dyn | Staging по-прежнему завершается ошибкой |
| Producer APFS pipeline возвращает 23 | tail не маскирует ошибку |
| timedatectl недоступен/возвращает ошибку | Сохраняется UTC fallback |
| timedatectl возвращает Europe/Paris | Значение сохраняется |

Тесты wrapper выполняют настоящие `common/build.sh` и `common/run.sh` в отдельном
временном дереве с mock image builder и emulator. Userland проверки исполняют
извлечённые из настоящего `userland/build.sh` staging/timezone строки и его
настройки shell. **Это не полная сборка APFS и не загрузка гостя.**
Без userland checkout тест печатает SKIP для этих шести проверок, а не pass.

Синтаксис изменённых shell files проверяется отдельно для каждого файла:

```bash
for file in common/build.sh common/run.sh userland/build.sh tools/common-test.sh; do
    bash -n "$file" || exit 1
done
bash tools/common-test.sh
git diff --check
common/ugit diff --check
```

На Windows та же проверка запускается из PowerShell:

```powershell
$env:TMPDIR = 'C:/Users/ibrohim/AppData/Local/Temp/opencode'
& 'C:\Program Files\Git\bin\bash.exe' tools/common-test.sh
```

## Состав изменений

- `common/build.sh`: ошибка image builder прекращает wrapper до упаковки boot image.
- `common/run.sh`: `pipefail` сохраняет ошибки emulator и writer лога.
- `userland/build.sh`: необязательный drawable_test, `pipefail` для APFS pipelines,
  сохранение UTC fallback при ошибке timedatectl.
- `tools/common-test.sh`: host-only regressions без Apple файлов и устройств.

Важная семантика: штатный GNU timeout тоже возвращает ненулевой код, обычно 124.
После включения pipefail этот код больше не теряется. Завершение лимита сессии
не равно доказанному kernel crash; результат нужно сопоставлять с serial log.
Обработка ошибок phone path и необычная проверка результата XNU linker в
`common/build.sh` в эту итерацию не переписаны.

## Воспроизведение объединённого форка

Следующие команды соответствуют интерфейсам исходников. Clone/setup и host tests
выполнены в этой итерации; **fetch, build images и guest boot ниже здесь не выполнялись**.
Для них требуется Linux host и зависимости из upstream README, включая 7-Zip >=23.

```bash
git clone --branch research/portability-baseline https://github.com/iboshka24/hackios-xnu-kernel.git hackios
cd hackios
USERLAND_URL=https://github.com/iboshka24/hackios-xnu-userland.git \
USERLAND_REF=research/portability-baseline bash common/setup.sh
bash tools/common-test.sh
```

Не запускайте setup повторно на рабочем дереве с незакоммиченными изменениями ради
«чистой проверки»: при существующем `.userland.git` он вызывает pull второго repo.
Для точной исходной базы используйте SHA из RESEARCH.ru.md; ветки форка изменяемые.

```bash
ios165/fetch.sh
CHECK=1 common/build.sh qemu-virt
QEMU_EFI=/usr/share/AAVMF/AAVMF_CODE.fd \
QEMU_VARS=/usr/share/AAVMF/AAVMF_VARS.fd \
common/run.sh qemu-virt 1200
```

Firmware paths выше взяты из upstream для Debian/Ubuntu; на другой системе
нужны существующие пути, а не пустые файлы. CHECK=1 дополнительно использует
инструменты APFS проверки и их зависимости. PREBUILT путь не требует SDK,
но пересборка собственных Metal libraries требует toolchain.

## Стенд и матрица последующей аппаратной валидации

| Тест | Данные для приёмки | Текущий результат |
|---|---|---|
| launchd/backboardd/SpringBoard | PID, boot timestamp, screenshot и отзывчивость ввода | NOT RUN |
| Settings, Safari, Photos, widgets | Действие, screenshot до/после, exception/crash logs | NOT RUN |
| Touch, audio, Wi-Fi | Завершённый ввод, слышимый/записанный sample, HTTP transfer | NOT RUN |
| GPU render/compute | Input hashes, ожидаемый readback, fence completed, pixels | NOT RUN |
| CoreAnimation FPS | Frame/present timestamps, median/p95 frame time, dropped frames | NOT MEASURED |
| GPU power/thermal | Условия нагрузки, источник телеметрии, idle/load duration | NOT MEASURED |
| Procursus/Sileo/dpkg/SSH/tweaks | Версии пакетов, prefix, установка пакета и запуск процесса | NOT RUN |
| Второй Android board | DTB hash, firmware versions, boot log и отдельные device tests | NOT RUN |
| iOS 27 | Exact build, ABI inventory, отдельные результаты каждого boot stage | NOT RUN |

Для каждого реального запуска сохраняются commits обоих repo, image hashes,
QEMU version/command line либо board/firmware, boot args, serial log и screenshot.
Сначала три одинаковых baseline boot; затем меняется один компонент.
Не считать строки QEMU-лога простым grep -c: `qemu/run-ios.sh` предупреждает о
повторном выводе console buffer. Для событий нужны PID/timestamp identifiers.

GPU submit, завершение fence и правильный результат — три разные проверки.
После timeout старый driver может оставаться wedged: следующие кейсы нельзя
считать измеренными без canary и восстановления либо нового boot.
Показатели FPS и ватт не выведены из субъективной плавности или процента ir3.

## Публикация и лицензии

Оба форка сохраняют upstream history и LICENSE: kernel — APSL 2.0, собственный
userland — MIT; third-party components сохраняют свои notices. В этот diff
не добавлены IPSW, SDK, извлечённые Apple binaries, vendor firmware или ключи.
Происхождение всех унаследованных upstream prebuilts отдельно не переаудировано.

Полные исходные diff доступны сравнением веток форков с исходными SHA из
RESEARCH.ru.md. Патчи не меняют XNU/GPU исходники и не заменяют проверку драйверов.
