const REPLACEMENT_CODE_POINT: number = 0xfffd;

export function encodeUtf8(value: string): Uint8Array {
  const bytes: number[] = [];
  for (let index: number = 0; index < value.length; index += 1) {
    let codePoint: number = value.charCodeAt(index);
    if (codePoint >= 0xd800 && codePoint <= 0xdbff && index + 1 < value.length) {
      const low: number = value.charCodeAt(index + 1);
      if (low >= 0xdc00 && low <= 0xdfff) {
        codePoint = 0x10000 + ((codePoint - 0xd800) << 10) + low - 0xdc00;
        index += 1;
      } else codePoint = REPLACEMENT_CODE_POINT;
    } else if (codePoint >= 0xdc00 && codePoint <= 0xdfff) codePoint = REPLACEMENT_CODE_POINT;
    if (codePoint <= 0x7f) bytes.push(codePoint);
    else if (codePoint <= 0x7ff) bytes.push(0xc0 | (codePoint >> 6), 0x80 | (codePoint & 0x3f));
    else if (codePoint <= 0xffff) bytes.push(0xe0 | (codePoint >> 12), 0x80 | ((codePoint >> 6) & 0x3f), 0x80 | (codePoint & 0x3f));
    else bytes.push(0xf0 | (codePoint >> 18), 0x80 | ((codePoint >> 12) & 0x3f),
      0x80 | ((codePoint >> 6) & 0x3f), 0x80 | (codePoint & 0x3f));
  }
  return new Uint8Array(bytes);
}

export function decodeUtf8(bytes: Uint8Array): string {
  let result: string = '';
  for (let index: number = 0; index < bytes.length;) {
    const first: number = bytes[index++];
    let codePoint: number = REPLACEMENT_CODE_POINT;
    let continuationCount: number = 0;
    let minimum: number = 0;
    if (first <= 0x7f) codePoint = first;
    else if ((first & 0xe0) === 0xc0) { codePoint = first & 0x1f; continuationCount = 1; minimum = 0x80; }
    else if ((first & 0xf0) === 0xe0) { codePoint = first & 0x0f; continuationCount = 2; minimum = 0x800; }
    else if ((first & 0xf8) === 0xf0) { codePoint = first & 0x07; continuationCount = 3; minimum = 0x10000; }
    if (continuationCount > 0) {
      const start: number = index;
      let valid: boolean = index + continuationCount <= bytes.length;
      for (let count: number = 0; valid && count < continuationCount; count += 1) {
        const next: number = bytes[index++];
        if ((next & 0xc0) !== 0x80) { valid = false; index = start; }
        else codePoint = (codePoint << 6) | (next & 0x3f);
      }
      if (!valid || codePoint < minimum || codePoint > 0x10ffff || (codePoint >= 0xd800 && codePoint <= 0xdfff)) {
        codePoint = REPLACEMENT_CODE_POINT;
      }
    }
    if (codePoint <= 0xffff) result += String.fromCharCode(codePoint);
    else {
      const adjusted: number = codePoint - 0x10000;
      result += String.fromCharCode(0xd800 + (adjusted >> 10), 0xdc00 + (adjusted & 0x3ff));
    }
  }
  return result;
}
