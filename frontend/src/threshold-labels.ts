import {Lang} from './i18n';
const labels:Record<string,[string,string,string,string]>={
sharpness_min:['Минимальная резкость','Minimum sharpness','Целевая дисперсия Лапласиана в области штрихкода.','Target Laplacian variance inside barcode ROI.'],
sharpness_critical:['Критическая резкость','Critical sharpness','Ниже этого значения фото отклоняется.','Reject below this value.'],
brightness_min:['Минимальная яркость','Minimum brightness','Средняя яркость области, шкала 0–255.','Mean ROI luminance on a 0–255 scale.'],
brightness_max:['Максимальная яркость','Maximum brightness','Верхний предел средней яркости.','Upper mean luminance limit.'],
dark_pixel_max:['Доля тёмных пикселей','Dark pixel ratio','Максимальная доля пикселей с яркостью ниже 25.','Maximum proportion of pixels below luminance 25.'],
overexposure_max:['Доля пересвета','Overexposed pixel ratio','Максимальная доля пикселей с яркостью от 250.','Maximum proportion of pixels at luminance 250 or above.'],
contrast_min:['Минимальный контраст','Minimum contrast','Целевое стандартное отклонение яркости в области.','Target standard deviation of ROI luminance.'],
barcode_area_min:['Минимальная площадь штрихкода','Minimum barcode area','Доля площади фотографии.','Fraction of total photo area.'],
barcode_width_min:['Минимальная ширина штрихкода','Minimum barcode width','Доля ширины фотографии.','Fraction of total photo width.'],
edge_margin_min:['Отступ от края','Edge safety margin','Относительный отступ; предупреждение при успешном чтении.','Relative margin; advisory when decoding succeeds.'],
glare_max:['Максимальный блик','Maximum glare','Порог структурного индикатора блика; эвристика.','Structural glare indicator threshold; heuristic.'],
perspective_max:['Максимальная перспектива','Maximum perspective','Порог асимметрии противоположных сторон; эвристика.','Opposing side asymmetry threshold; heuristic.'],
quality_score_min:['Минимальная оценка качества','Minimum quality score','Требуется вместе с прохождением критических проверок.','Required together with passing hard requirements.'],
decode_weight:['Вес декодирования','Decode weight','Доля итоговой оценки от успешного чтения.','Fraction of final score contributed by successful decoding.']};
export function thresholdLabel(key:string,lang:Lang){const x=labels[key];return x?{name:x[lang==='ru'?0:1],description:x[lang==='ru'?2:3]}:{name:key,description:''}}
