export enum Rotation { DEG_0 = 0, DEG_90 = 90, DEG_180 = 180, DEG_270 = 270 }
export interface Point { x: number; y: number; }
export interface Viewport { left: number; top: number; width: number; height: number; rotation: Rotation; }

export class CoordinateMapper {
  map(localX: number, localY: number, viewport: Viewport): Point {
    if (viewport.width <= 0 || viewport.height <= 0) throw new Error('Viewport must be positive');
    const rawX: number = Math.min(Math.max((localX - viewport.left) / viewport.width, 0), 1);
    const rawY: number = Math.min(Math.max((localY - viewport.top) / viewport.height, 0), 1);
    switch (viewport.rotation) {
      case Rotation.DEG_90: return { x: rawY, y: 1 - rawX };
      case Rotation.DEG_180: return { x: 1 - rawX, y: 1 - rawY };
      case Rotation.DEG_270: return { x: 1 - rawY, y: rawX };
      default: return { x: rawX, y: rawY };
    }
  }
}

