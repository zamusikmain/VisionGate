import {Key} from './i18n';
export function uploadError(file:File):Key|null {
 if(file.size>12*1024*1024)return 'invalid';
 if(['image/heic','image/heif','image/heic-sequence','image/heif-sequence'].includes(file.type)||(!file.type&&/\.(heic|heif)$/i.test(file.name)))return 'unsupportedHEIF';
 const supported=['image/jpeg','image/png','image/webp'].includes(file.type)||(!file.type&&/\.(jpe?g|png|webp)$/i.test(file.name));
 return supported?null:'invalid';
}
export function apiErrorKey(code:string):Key {
 const keys:Record<string,Key>={UNSUPPORTED_HEIF:'unsupportedHEIF',UNSUPPORTED_ANIMATION:'unsupportedAnimation',BUSY:'busyError',FILE_TOO_LARGE:'invalid',INVALID_IMAGE_TYPE:'invalid',CORRUPTED_IMAGE:'corruptImage',INVALID_IMAGE_DIMENSIONS:'invalidDimensions'};
 return keys[code]??'systemError';
}
