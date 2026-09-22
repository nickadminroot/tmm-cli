# Разработка и live-рендеринг из WSL

Исходники могут храниться и редактироваться в Linux-файловой системе WSL. В проекте есть два разных режима выполнения.

## 1. COM-free разработка в Linux

Парсинг, валидация, раскладка и fake-API тесты не требуют KOMPAS или Windows COM:

```bash
uv sync --locked
uv run --locked python -m unittest
```

Linux-окружение не может выполнить `KOMPAS.Application.7`. Установка `pywin32` в Linux не заменяет Windows COM.

## 2. Live KOMPAS через Windows Python

WSL умеет запускать Windows `python.exe`. Скрипт остаётся в WSL, но сам Python-процесс, pywin32 и KOMPAS работают в Windows.

Предварительные требования:

- KOMPAS-3D установлен и `KOMPAS.Application.7` зарегистрирован;
- Windows Python доступен в WSL как `python.exe`;
- зависимости установлены именно в Windows Python:

```bash
python.exe -m pip install "pywin32" "markdown-it-py>=3,<5" "mdit-py-plugins>=0.4,<1"
```

Проверить интерпретатор:

```bash
python.exe -c "import sys, pythoncom, win32com.client; print(sys.executable); print('pywin32 OK')"
```

## Рекомендуемый wrapper

`tools/render_from_wsl.sh` преобразует Linux-пути через `wslpath`, явно добавляет WSL `src/` в `sys.path` Windows Python, проверяет зависимости, запускает production CLI и при необходимости экспортирует активный документ в PNG. Явная вставка пути важна: в проверенной установке Windows Python отбрасывал UNC-путь из переменной `PYTHONPATH` и подхватывал старую editable-копию проекта с диска `G:`.

```bash
chmod +x tools/render_from_wsl.sh

# Только CDW
./tools/render_from_wsl.sh tests/fixtures/v2-single-scene.json \
  --output test_output/wsl-v2-single-scene.cdw

# CDW + PNG и закрытие созданного документа после экспорта
./tools/render_from_wsl.sh tests/fixtures/table.scene.json \
  --output test_output/wsl-table.cdw \
  --png test_output/wsl-table.png \
  --dpi 180

# Снимок только рабочей области; документ оставить открытым
./tools/render_from_wsl.sh tests/fixtures/table.scene.json \
  --output test_output/wsl-table.cdw \
  --png test_output/wsl-table-work-area.png \
  --work-area --keep-open
```

Другой Windows Python можно выбрать переменной:

```bash
PYTHON_EXE=/mnt/c/Users/NickAdminRoot/.venvs/tmm-scene-kompas/Scripts/python.exe \
  ./tools/render_from_wsl.sh tests/fixtures/v2-single-scene.json
```

## Почему wrapper предпочтительнее прямого вызова

Прямой вызов тоже возможен. Для неустановленного WSL checkout путь к `src/` следует вставлять явно, а не полагаться на UNC в `PYTHONPATH`:

```bash
python.exe -c \
  'import sys; sys.path.insert(0, sys.argv.pop(1)); from tmm_scene_kompas.cli import main; raise SystemExit(main())' \
  "$(wslpath -w "$PWD/src")" \
  "$(wslpath -w "$PWD/tests/fixtures/v2-single-scene.json")" \
  --output "$(wslpath -w "$PWD/test_output/direct.cdw")"
```

После установки именно этого checkout в Windows Python также доступна обычная форма `python.exe -m tmm_scene_kompas ...`.

Но wrapper дополнительно:

- не смешивает Linux Python и Windows pywin32;
- преобразует входные и выходные пути;
- использует UTF-8 для вывода Windows Python;
- экспортирует PNG через `IKompasDocument1.SaveAsToRasterFormat`;
- проверяет существование и ненулевой размер результатов;
- закрывает только созданный документ, если не передан `--keep-open`.

В проверенном окружении KOMPAS успешно сохраняет CDW и PNG напрямую по UNC-пути `\\wsl.localhost\\Ubuntu\\home\\...`. Если другая версия KOMPAS не принимает UNC, укажите выход на `/mnt/c/...`, а после завершения скопируйте файл обратно в WSL.

## Live smoke для нативной таблицы

```bash
src=$(wslpath -w "$PWD/src")
script=$(wslpath -w "$PWD/tests/smoke_native_table.py")
out=$(wslpath -w "$PWD/test_output")
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
  /mnt/c/Windows/py.exe -3.14 -u "$script" "$src" --output-dir "$out"
```

Smoke проходит production path `compile_table_plan() → add_table()` с merged
header и заведомо длинной mixed-формулой в ячейке шириной 35 мм. Успех
подтверждается одновременно:

- ровно одной `DrawingTable`, нулём overlay `DrawingTexts` и `Valid=True` до и после reopen;
- native readback `[ItemType 0,4,5,6]`, base/tail `Height=5` и `Italic=True` у всех items;
- `RowsCount == ColumnsCount == 2`;
- ненулевыми CDW/PNG через raster API;
- визуально: merged header, одна строка и горизонтальное сжатие длинного content без wrapping.

На установленном KOMPAS aggregate `ITable.Range(...).CellsFormat` после reopen
возвращает `Width=Height=0` и не сохраняет неодинаковые ширины. Production
`add_table()` поэтому включает `FixedCellsSize` и записывает
`ICellFormat.Width` через каждую native cell; exact per-cell assignments
покрываются COM-free fake contract test, а live geometry/merge/fit
подтверждаются raster.

COM-free unit-тесты не заменяют этот live smoke: они не проверяют установленную версию KOMPAS, регистрацию typelib, шрифты и реальную геометрию таблицы.

## Focused native-cell rich-text probe

Для первого подшага milestone 4 запускайте focused probe тем же явным Windows
интерпретатором, но передавайте converted `src/` первым аргументом: скрипт
вставляет этот путь в `sys.path` до импорта текущего checkout.

```bash
src=$(wslpath -w "$PWD/src")
script=$(wslpath -w "$PWD/tools/probe_native_drawing_table_rich_text.py")
out=$(wslpath -w "$PWD/test_output")
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 \
  /mnt/c/Windows/py.exe -3.14 -u "$script" "$src" --output-dir "$out"
```

Probe не использует API5 и не создаёт overlay `DrawingText`. Acceptance
case компилирует `Длина $l_1$, мм` в `Длина l$;1$, мм`, записывает его через
существующий `ITable.Cell(0, 0).Text -> IText.Str`, читает
`ITextLine`/`ITextItem`/`ITextFont` после save/reopen и принимает persistent
native structure `[ItemType 0,4,5,6]`. Для этого пути plain/tail items должны
иметь `Height=5`, внутренние formula items — установленный KOMPAS height
около `3.333`, а `Italic` должен быть `True` у всех items. `ItemType=20` не
является acceptance requirement. Probe сохраняет
`test_output/native-table-rich-text.{cdw,png}` и JSON report; exit code отличен
от нуля, если live readback не подтвердил эту структуру, counts
`DrawingTables=1`, `DrawingTexts=0`, `Valid=True` или CDW/PNG пусты.
Остальные `item-update`/`reuse-initial`/`geometry-first` cases — bounded
исторические capability probes; их `ITextLine.Add` paths не используются
production writer.

## Диагностика

- `ModuleNotFoundError: win32com` — пакет установлен не в тот Windows Python; используйте `python.exe -m pip ...`.
- `KOMPAS.Application.7` не найден — проверить установку и COM-регистрацию KOMPAS.
- `Payload not found` — использовать wrapper или передавать путь после `wslpath -w`.
- CDW создан, но PNG отсутствует — экспортировать только через `IKompasDocument1.SaveAsToRasterFormat`, не через `doc.SaveAs("file.png")`.
- Кириллица искажена только в терминале — запускать с `PYTHONUTF8=1` и `PYTHONIOENCODING=utf-8`; содержимое CDW проверять через API readback и PNG.
