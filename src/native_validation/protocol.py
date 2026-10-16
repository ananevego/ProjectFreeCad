"""Manual native scenarios; a generated kit never marks these as executed."""

CHECKS = [
    dict(id='FPL_ROUNDTRIP', application='freepcb', title='Импорт и сохранение FPL',
         action='В FreePCB2 2.428 импортировать standalone FPL и 24 component FPL. Сохранить в results, закрыть и открыть сохранённые библиотеки.',
         pass_criteria='Имена, число/номера pin records, hole/shape sizes, origin и углы совпадают с expected-catalog.json; любые изменения записать.',
         evidence_expected=['saved FPL', 'version/import screenshots']),
    dict(id='FPL_LAYERS_TEXT', application='freepcb', title='Слои, тексты и рисунок',
         action='Проверить top/bottom silk, notes, reference/value/user text, fills и четыре dash/dot patterns; сравнить с source и conversion reports.',
         pass_criteria='Нет дополнительных потерь сверх объявленных; различия font/baseline/caps/joins измерены и записаны, а не признаны точными автоматически.',
         evidence_expected=['layer/text screenshots', 'measurements']),
    dict(id='APERTURES_NPTH', application='freepcb', title='Mask/paste, PTH и NPTH',
         action='На тестовой плате в MM разместить controls. Проверить mask/paste, NPTH 3.2mm без copper/paste и PTH padstacks; сопоставить native records с catalog.',
         pass_criteria='Размеры/слои/holes сохранены; отсутствие plating flag не считается доказательством NPTH manufacturing semantics.',
         evidence_expected=['saved board', 'aperture/drill measurements']),
    dict(id='TECH_CARRIER_CONTACT', application='freepcb', title='Технический carrier и contact',
         action='Импортировать TechnicalContact_Control. Проверить отсутствие copper/hole у __TECH_1, наличие только его F.Paste; у contact1 только B.Cu/B.Mask без paste.',
         pass_criteria='Geometry/layers совпадают с catalog; дополнительный electrical exposure carrier или неожиданные net connections записать как finding/failure.',
         evidence_expected=['pad properties screenshot', 'netlist/connection observation']),
    dict(id='GERBER_DRILL', application='freepcb', title='Gerber и drill',
         action='Экспортировать Gerber и drill тестовой платы в results; независимо открыть эти файлы и измерить copper/mask/paste/holes.',
         pass_criteria='Файлы соответствуют измерениям catalog; NPTH/plating/tool separation проверены по фактическому drill output, не по 3D.',
         evidence_expected=['Gerber/drill files', 'independent viewer measurements']),
    dict(id='CDS_ROUNDTRIP', application='schemator', title='Импорт и сохранение CDS',
         action='В Схематоре 1.429 импортировать 24 symbol.cds, сохранить и повторно открыть. Проверить тело, тексты, pin markers и номера.',
         pass_criteria='Количество физических pin numbers и connection endpoints совпадает с catalog; font/render differences и native failures записаны.',
         evidence_expected=['saved CDS/schematic', 'version/pin screenshots']),
    dict(id='PIN_MAPPING_NETLIST', application='schemator', required_versions={'schemator':'1.429','freepcb':'2.428'}, title='Связи УГО → footprint',
         action='Создать R/C/header и multi-unit/common компоненты, соединить выводы, выгрузить netlist и загрузить её в тестовую плату FreePCB2.',
         pass_criteria='Physical numbers/net connections соответствуют source mapping; source ERC/power/NC semantics не объявляются перенесёнными только по совпадению номера.',
         evidence_expected=['schematic', 'netlist', 'board connection report']),
    dict(id='UNIT_PIN_POLICIES', application='schemator', title='Секции и pin policies',
         action='Проверить bundles units/common/power/pins: disjoint/common views, revealed hidden pins, connectable NC и numbered power pins.',
         pass_criteria='Фактическое поведение соответствует explicit loss policies; independent placement, hierarchy и implicit nets отдельно описаны, не считаются перенесёнными.',
         evidence_expected=['unit/pin screenshots', 'behavior notes']),
    dict(id='OPENSCAD_BOARD_FRAME', application='openscad', required_versions={'freepcb':'2.428','openscad':None}, title='Native board export и 3D frame',
         action='В FreePCB2 выбрать общую openscad_models/Bundle.3dshapes, единицы MM. Разместить R0805/C0805/Header6 с разными поворотами и flip, экспортировать board SCAD и открыть в OpenSCAD.',
         pass_criteria='Масштаб, origin, pin1, высота и ориентация STL совпадают с платой. scenes/*.scad и CSG compilation сами по себе этого не доказывают.',
         evidence_expected=['native board SCAD', '3D screenshots with measured references']),
    dict(id='RELOCATE_NATIVE', application='freepcb', title='Перенос комплекта',
         action='Перенести весь kit на другую машину/в новый каталог. Проверить verify_kit.py, выбрать новый полный путь 3D folder и повторить импорт и board export без доступа к старым путям.',
         pass_criteria='Нужны только файлы kit и целевые приложения; существующие исходники/модели не удалять ради этой проверки.',
         evidence_expected=['relocated setup screenshot', 'saved native export']),
]


def protocol():
    return dict(schema_version=1, kind='native_validation_protocol', checks=CHECKS,
        scope='Manual observations with evidence; file/record checks do not attest GUI actions.')


def results_template():
    return dict(schema_version=1, kind='native_validation_results', kit_manifest_sha256=None,
        operator=None, versions=dict(freepcb=None, schemator=None, openscad=None),
        checks=[dict(id=c['id'], status='not_run', notes='', evidence=[]) for c in CHECKS])


README = '''# Комплект native validation

Цель: FreePCB2 2.428, Схематор 1.429, единицы MM. Скопируйте ВЕСЬ каталог.
Файлы FPL/CDS — CP1251, JSON/Markdown/SCAD — UTF-8. Установленный Python 3.10+
нужен только checker; он использует стандартную библиотеку и работает без repo.

1. Выполните `py -3 -B verify_kit.py` (macOS/Linux: `python3 -B verify_kit.py`).
   Это проверка целостности, а не подтверждение GUI, netlist, Gerber или 3D.
2. В FreePCB2 выберите MM и Папка для OpenSCAD = полный локальный путь
   `<kit>/openscad_models/Bundle.3dshapes`. Эта общая папка содержит aliases
   всех bundles. Внутренние README bundles описывают также их отдельные папки.
3. Используйте bundles/<stage>/components/<id>/{symbol.cds,footprint.fpl} и
   footprints/<id>/footprint.fpl. Полный список и expected pin/shape records
   находятся в expected-catalog.json. Planned 2D controls не получают STL по догадке.
   Catalog использует NM: 1mm=1000000NM. pin.x/y — native coordinates, angle —
   native clockwise degrees. Pad record = [shape,height,left,right,radius],
   полная ширина=left+right. Shape 0=none, 1=round, 3=rect, 4=roundrect,
   5=oval, 99=project default; inner_pad имеет дополнительный connect_flag.
4. Создайте протокол: `py -3 -B verify_kit.py --init-results results/run.json`.
   Заполните operator/versions и checks из protocol.json. Все проверки изначально
   not_run. passed требует notes и evidence: [{"path":"results/...","sha256":"..."}].
   SHA256 файла: `(Get-FileHash results/file -Algorithm SHA256).Hash.ToLower()`.
   Сохранённые native файлы, screenshots и Gerber кладите только в results/;
   используйте ASCII-имена файлов без пробелов для переносимости на Windows.
5. Проверьте протокол: `py -3 -B verify_kit.py --results results/run.json`.
   Checker подтверждает структуру/хеши evidence и kit identity; действия оператора
   и содержание screenshot криптографически не удостоверяет. Immutable manifest
   сохраняет native validation flags=false; не редактируйте его для записи успеха.
6. Файлы scenes/*.scad — library-local model previews из явных transforms.
   Опционально `py -3 -B verify_kit.py --compile-openscad C:/path/openscad.exe`.
   Это CSG syntax compilation, без remesh STL, GUI или physical frame claims.
   После relocation компилируйте заново с новым --run-id; результаты CSG могут
   содержать абсолютные пути времени запуска. Не подменяйте ими native board SCAD.

Refusals содержит source/report для ожидаемых slots/offset/nonrectangular pads;
FPL для них отсутствует. Они не заменены кругами/прямоугольниками. Source snapshots
в source/ сохраняют структуру проекта и выбранные исходники с LICENSE/provenance.
Provenance/README библиотек могут описывать больше файлов, чем выбранный snapshot.
STL скопированы побайтно только из существующего store; их source frame/license
provenance не восстанавливается из имени. hashes доказывают identity, не alignment.
ready_for_3d_checks=false означает неполный набор моделей; 3D checks тогда blocked.

Не изменяйте bundles/source/footprints/openscad_models/scenes. Для native save/export
используйте results/. Полный перечень сценариев, pass criteria и evidence — protocol.json.
'''
