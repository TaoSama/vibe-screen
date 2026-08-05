const HID_A: number = 0x04;
const HID_1: number = 0x1e;

const NAMED_HID: Record<string, number> = {
  Enter: 0x28, Escape: 0x29, Backspace: 0x2a, Tab: 0x2b, Space: 0x2c,
  ArrowRight: 0x4f, ArrowLeft: 0x50, ArrowDown: 0x51, ArrowUp: 0x52,
  Delete: 0x4c, Home: 0x4a, End: 0x4d, PageUp: 0x4b, PageDown: 0x4e
};

export class PeripheralInputMapper {
  usbHidUsage(keyText: string): number | undefined {
    if (keyText.length === 1) {
      const lower: string = keyText.toLowerCase();
      const code: number = lower.charCodeAt(0);
      if (code >= 97 && code <= 122) return HID_A + code - 97;
      if (code >= 49 && code <= 57) return HID_1 + code - 49;
      if (code === 48) return 0x27;
      if (keyText === ' ') return NAMED_HID.Space;
    }
    return NAMED_HID[keyText];
  }

  buttonMask(button: number): number {
    if (button < 0 || button > 4) return 0;
    return 1 << button;
  }
}
