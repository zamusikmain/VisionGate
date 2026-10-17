"""Private development report; evaluation annotations are never inference inputs."""
import json
from pathlib import Path

from backend.gate.samsung_auto import summarize_fields
from backend.gate.samsung_pretrained import extract_records

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/samsung-pretrained'


def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def field_counts(photos):
    return {key:sum(any((f['key'].startswith('imei') if key=='imei' else f['key']==key) and f['format_valid']
                       for f in p['fields']) for p in photos)
            for key in ('imei','imei1','imei2','model','sku','serial','storage_gb')}


def describe(fields):
    return '; '.join(f"{f['key']}={f['value']}"+(' [invalid format/checksum]' if not f['format_valid'] else '') for f in fields) or '—'


def run():
    before=load(ROOT/'reports/samsung-v03/final/results.json')
    after=load(OUT/'integrated/results.json')
    old={p['sha256']:p for c in before['cases'] for p in c['photos']}
    selected={p['sha256']:p for c in after['cases'] for p in c['photos']}
    experiments={}
    for name in ('mobile','server','server-det'):
        report=load(OUT/name/'results.json')
        for p in report['photos']:p['fields']=summarize_fields(extract_records(p))
        experiments[name]=report
    audit=load(OUT/'manual-read-audit.json')
    lines=['# Samsung: эксперимент с предобученными локальными моделями', '',
           '16 октября 2026. Измеримое улучшение чтения и сопоставления получено. Надёжная автоматическая приёмка фото пока не достигнута.', '',
           'Все 28 уникальных фотографий обработаны. Ни изображения, ни OCR-текст не отправлялись во внешние сервисы. Публичные веса скачаны отдельно после проверки источника, лицензии, размера и SHA-256. NASCA не обходилась; BioGate не изменялся; push/deployment не выполнялись.', '',
           '## Фактический результат', '',
           '- APPROVED правильно: 0/5 → 0/5. REJECTED по подтверждённым дефектам исходных кейсов: 0/9 → 0/9.',
           '- UNKNOWN / REVIEW: 14/14 → 14/14. Все 14 итоговых отказов — REJECTED_UNVERIFIED. Подтверждённое покрытие решений: 0%.',
           '- Confusion matrix не изменилась: [[0,5],[0,9]], строки — ожидаемые APPROVED/REJECTED, столбцы — фактические APPROVED/REJECTED.',
           f"- Реальные перестановки scan: подтверждённые несовпадения {before['permutations']['confirmed_mismatches']}/182 → {after['permutations']['confirmed_mismatches']}/182; неразрешённые {after['permutations']['unresolved_identity']}/182; ложных одобрений перестановок 0.",
           '- Новые подтверждённые несовпадения основаны на независимом чтении точных цифр штрихкодом и OCR-контексте того же слота. Имена файлов и case ID не используются как значения идентификаторов.', '',
           'Это разработочные примеры, уже просмотренные при разработке. Метрики не являются независимой оценкой точности.', '',
           '## Поля: количество фотографий с форматно допустимым кандидатом', '',
           'Кандидат не равен подтверждённому правильному полю. Luhn/формат и высокая модельная оценка не гарантируют точность OCR. Модель и SKU не объединяются.', '',
           '| Поле | Старый pipeline | Только PP-OCRv5 mobile | Интегрированный профиль |', '|---|---:|---:|---:|']
    counts=[field_counts(list(old.values())),field_counts(experiments['mobile']['photos']),field_counts(list(selected.values()))]
    for key in counts[0]:lines.append(f"| {key} | {counts[0][key]}/28 | {counts[1][key]}/28 | {counts[2][key]}/28 |")
    strong=lambda photos:sum(any(f['key'] in {'imei1','imei2'} and f.get('mismatch_eligible') for f in p['fields']) for p in photos)
    lines+=['',f"Фото со слотом IMEI, подтверждённым точными цифрами из штрихкода: {strong(old.values())}/28 → {strong(selected.values())}/28.",
            'Существующее покрытие первичных IMEI сохранено: 17/28. Новая модель дополняет декодер вторыми IMEI и контекстом слотов; она не заменяет ZXing. Полная точность транскрипции и recall всех полей не измерены: сплошной эталонной разметки нет.', '',
            '## Визуально проверенные новые чтения', '',
            'Девять выбранных полей на шести исходных фотографиях проверены по исходным пикселям этикеток. Это частичный аудит конкретных улучшений, а не случайная/отложенная выборка. Неоднозначные поля не включены в эталон.', '',
            '| Фото SHA-256, начало | Роль | Поле | Прочитано на источнике | Было извлечено | Стало извлечено |', '|---|---|---|---|---|---|']
    recovered=[]
    for a in audit['annotations']:
        has=lambda p:any(f['key']==a['field'] and f['value']==a['value'] for f in p['fields'])
        b=has(old[a['sha256']]);n=has(selected[a['sha256']]);recovered.append(dict(**a,before=b,after=n))
        lines.append(f"| {a['sha256'][:12]} | {a['role']} | {a['field']} | {a['value']} | {'да' if b else 'нет'} | {'да' if n else 'нет'} |")
    lines+=['', 'Оценки уверенности сохранены как некалиброванные. В неправильных чтениях, например вариантах IMEI с неверной контрольной суммой, цифры не исправляются. Нормализация I/1 касается только маркера поля IMEI, исходная строка сохраняется.', '',
            '## Реально использованные модели и время', '',
            '| Эксперимент | Модели | Нейронная обработка 28 фото |', '|---|---|---:|']
    for name,title in [('mobile','PP-OCRv5 mobile det + latin mobile rec'),('server','PP-OCRv5 mobile det, затем server rec по строкам-кандидатам'),('server-det','PP-OCRv5 server det + latin mobile rec')]:
        lines.append(f"| {name} | {title} | {experiments[name]['inference_seconds']:.2f} с |")
    for name in ('nanodet','yolox'):
        r=load(OUT/(name+'-results.json'))
        lines.append(f"| {name} | OpenCV Zoo COCO ONNX | {r['inference_seconds']:.2f} с |")
    grounding=load(OUT/'grounding/results.json')
    lines.append(f"| grounding | Grounding DINO tiny, ONNX Community uint8 | {grounding['inference_seconds']:.2f} с |")
    api=load(OUT/'api-smoke.json')
    lines+=['',f"Полный интегрированный batch: {after['elapsed_seconds']:.2f} с, с частичным локальным кэшем и параллельной нагрузкой. API на одной реальной паре: {api['seconds']:.2f} с. Это не контролируемое сравнение скоростей. Мобильный нейронный OCR отдельно обработал 28 фото примерно за 70 с, около 2,5 с/фото.",
            'Тяжёлые server-эксперименты включали конкуренцию за CPU; каскад server rec повторно использовал области mobile detector. Первый неограниченный server-прогон остановлен до первого результата через 194 с. Отдельная проверка показала загрузку с обычной оптимизацией за 0,39 с: гипотеза о зависании оптимизатора не подтверждена.', '',
            'Источники: [PaddlePaddle mobile detector](https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx), [Latin recognizer](https://huggingface.co/PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx), [server detector](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_det_onnx), [server recognizer](https://huggingface.co/PaddlePaddle/PP-OCRv5_server_rec_onnx), [NanoDet](https://huggingface.co/opencv/object_detection_nanodet), [YOLOX](https://huggingface.co/opencv/object_detection_yolox), [Grounding DINO export](https://huggingface.co/onnx-community/grounding-dino-tiny-ONNX). Все веса объявлены Apache-2.0; ONNX Runtime — MIT. Точные ревизии, размеры и SHA-256 сохранены в provenance.json рядом с весами.', '',
            '## Возможности проверок', '',
            '| Проверка | Что установлено экспериментом |', '|---|---|',
            '| Области текста и идентификаторы | PP-OCRv5 даёт новые реальные чтения и рамки строк; улучшение подтверждено частичным визуальным аудитом |',
            '| Физическая коробка | Grounding DINO выдал box-кандидатов на 28/28 фото, включая переснятые экраны и крупные планы наклейки. Это не 28 правильных физических коробок |',
            '| Нужная заводская наклейка | Grounding DINO не выдал label-кандидатов с фиксированным запросом/порогом. COCO-модели такого класса не имеют. Детектор заводской наклейки не подтверждён |',
            '| Пересъёмка экрана | NanoDet и YOLOX не дали phone-кандидатов. Единственная phone-рамка Grounding DINO попала на этикетку, а не на весь телефон; визуально непригодна. Подтверждённых автоматических отказов по этому признаку нет |',
            '| Обрезка, перекрытые поля, критические блики | OCR не доказывает полноту/отсутствие дефектов. Нет проверенного детектора границы наклейки и разметки обязательных полей: UNKNOWN |',
            '| Несовпадение IMEI | Улучшено: 16 подтверждённых несовпадений из 182 перестановок вместо 0; остальные не считаются успешным обнаружением |', '',
            'Объектные эксперименты не интегрированы в политику решений. Порог NanoDet 0,35, YOLOX 0,35 и Grounding DINO 0,3 сохранены по исходным примерам; запрос Grounding DINO зафиксирован до прогона. Первая попытка NanoDet с неверной подготовкой входа исключена из оценки; финальный прогон использует RGB/letterbox и исправленный порядок выходных тензоров OpenCV 5.', '',
            '## Все 14 исходных случаев', '', '| Case ID | Ожидалось | Получено | Статус доказательств |', '|---|---|---|---|']
    expected={r['case_id']:r['expected'] for r in before['evaluation']['rows']}
    for case in after['cases']:lines.append(f"| {case['case_id']} | {expected[case['case_id']]} | {case['final_decision']} | {case['rejection_status']} / {case['diagnostic_state']} |")
    lines+=['','## Сравнение всех 28 фотографий','', '| Case ID / роль | До | После интеграции |', '|---|---|---|']
    for case in after['cases']:
        for photo in case['photos']:lines.append(f"| {case['case_id']} / {photo['role']} | {describe(old[photo['sha256']]['fields'])} | {describe(photo['fields'])} |")
    lines+=['', '## Проверки и ограничения', '',
            'Backend: 260 passed, 2 skipped. Frontend: 37 passed. TypeScript и production build успешны. Реальный API smoke: HTTP 200, no-store, оба фото имеют pretrained_ocr.status=OK, ложного конфликта исходной пары нет. Batch и XLSX export выполнены; XLSX повторно прочитан с проверкой буквальных идентификаторов.', '',
            'Нехватка мощности не является главным препятствием для выбранного mobile OCR. Не хватает доступной схемы обязательных полей Samsung, доменной разметки и проверенного детектора наклейки/физического объекта/дефектов. Читаемость части строк не закрывает эти требования. Текущая реализация не выполняет требование надёжного бинарного автоматического одобрения.', '',
            '## До 19 октября', '',
            '- 16 октября: зафиксировать мобильный профиль и сверенные чтения; получить доступную спецификацию штатным корпоративным доступом, без обхода DRM. Разметить на текущих фото полигоны коробки/наклейки, текст и реальные дефекты.',
            '- 17 октября: собрать разрешённую отдельную выборку (ориентир 100–300 разнообразных пар как план сбора, не гарантия достаточности); обучить/адаптировать небольшой доменный детектор либо получить существующие корпоративные веса. Для обучения предпочтительна разрешённая локальная/внутренняя GPU-машина; изображения не выгружать в публичный сервис.',
            '- 18 октября: заморозить правила и проверить новые устройства, магазины/сессии и источники съёмки. Измерить ошибки полей, IoU/recall наклейки, false APPROVED/REJECTED, дефекты и UNKNOWN. Не настраивать модель по отложенной выборке.',
            '- 19 октября: регрессия, batch/API/XLSX, фиксированная локальная сборка и демонстрация с честными ограничениями. Если спецификация/разметка/новые данные не получены, сдавать OCR-assisted прототип, не обещать полноценную автоматическую приёмку.', '',
            '## Запуск выбранного профиля', '', '```powershell',
            '# Run from the VisionGate project root',
            '.\\start-samsung.ps1 -Mode web -OcrEngine ppocrv5',
            '.\\start-samsung.ps1 -Mode batch -OcrEngine ppocrv5 -ReportDirectory reports/samsung-pretrained/integrated',
            '.\\start-samsung.ps1 -Mode export -OcrEngine ppocrv5 -ReportDirectory reports/samsung-pretrained/integrated',
            '```', '', 'Для прежнего профиля: `-OcrEngine legacy`. Оригиналы остаются в `data/Samsung/original`; настройки моделей и инструкция — в `docs/samsung-pretrained.md`. Внешние AI API не используются.']
    (OUT/'RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (OUT/'comparison.json').write_text(json.dumps(dict(candidate_photo_counts=dict(before=counts[0],mobile=counts[1],integrated=counts[2]),visual_audit=recovered,
        before_evaluation=before['evaluation'],after_evaluation=after['evaluation'],after_permutations=after['permutations']),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Private report saved',OUT/'RESULT.md')


if __name__=='__main__':run()
