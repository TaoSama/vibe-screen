import { media } from '@kit.AVCodecKit';
import { Codec } from '../core/protocol/ProtocolModels';
import { EncodedFrame, LatestFrameQueue } from '../core/media/LatestFrameQueue';

const VIDEO_MIME_H264: string = 'video/avc';
const VIDEO_MIME_HEVC: string = 'video/hevc';

export interface VideoDecoderListener { onDecoderError(message: string): void; onFrameRendered(): void; }
interface InputSlot { index: number; buffer: media.AVBuffer; }
interface DetachedDecoder { decoder: media.VideoDecoder; started: boolean; }

export class HarmonyVideoDecoder {
  private decoder: media.VideoDecoder | undefined;
  private frames: LatestFrameQueue = new LatestFrameQueue();
  private inputSlots: InputSlot[] = [];
  private epoch: bigint = 0n;
  private listener: VideoDecoderListener | undefined;
  private started: boolean = false;
  private generation: number = 0;

  async configure(codec: Codec, width: number, height: number, surfaceId: string, epoch: bigint,
    listener: VideoDecoderListener): Promise<void> {
    const owner: number = ++this.generation;
    const previous: DetachedDecoder | undefined = this.detachDecoder();
    if (previous !== undefined) await this.releaseDetached(previous);
    if (owner !== this.generation) throw new Error('Decoder configuration superseded');
    if (codec !== Codec.H264 && codec !== Codec.HEVC) throw new Error('Unsupported hardware codec');
    if (surfaceId.length === 0) throw new Error('Video surface is not ready');

    const mime: string = codec === Codec.HEVC ? VIDEO_MIME_HEVC : VIDEO_MIME_H264;
    const candidate: media.VideoDecoder = await media.createVideoDecoderByMime(mime);
    if (owner !== this.generation) { await candidate.release(); throw new Error('Decoder configuration superseded'); }
    this.decoder = candidate; this.listener = listener; this.epoch = epoch;
    candidate.on('error', (error: Error) => {
      if (!this.isCurrent(owner, candidate)) return;
      this.frames.clear(); listener.onDecoderError(error.message);
    });
    candidate.on('needInputData', (index: number, buffer: media.AVBuffer) => {
      if (!this.isCurrent(owner, candidate)) return;
      this.inputSlots.push({ index, buffer }); this.drain(candidate, owner);
    });
    candidate.on('newOutputData', (index: number, _buffer: media.AVBuffer) => {
      if (!this.isCurrent(owner, candidate)) return;
      candidate.freeOutputBuffer(index, true); listener.onFrameRendered();
    });
    await candidate.configure({ mime, width, height }); this.ensureCurrent(owner, candidate);
    await candidate.setOutputSurface(surfaceId); this.ensureCurrent(owner, candidate);
    await candidate.prepare(); this.ensureCurrent(owner, candidate);
    await candidate.start(); this.ensureCurrent(owner, candidate);
    this.started = true;
  }

  submit(frame: EncodedFrame): void {
    this.frames.offer(frame);
    const active: media.VideoDecoder | undefined = this.decoder;
    if (active !== undefined) this.drain(active, this.generation);
  }

  droppedFrames(): number { return this.frames.droppedCount(); }

  async release(): Promise<void> {
    this.generation += 1;
    const detached: DetachedDecoder | undefined = this.detachDecoder();
    if (detached !== undefined) await this.releaseDetached(detached);
  }

  private detachDecoder(): DetachedDecoder | undefined {
    const active: media.VideoDecoder | undefined = this.decoder;
    const detached: DetachedDecoder | undefined = active === undefined ? undefined : { decoder: active, started: this.started };
    this.decoder = undefined; this.started = false; this.inputSlots = []; this.frames.clear(); this.listener = undefined;
    return detached;
  }

  private async releaseDetached(detached: DetachedDecoder): Promise<void> {
    if (detached.started) { try { await detached.decoder.stop(); } finally { await detached.decoder.release(); } }
    else await detached.decoder.release();
  }

  private drain(candidate: media.VideoDecoder, owner: number): void {
    if (!this.isCurrent(owner, candidate)) return;
    const frame: EncodedFrame | undefined = this.frames.poll(this.epoch);
    const slot: InputSlot | undefined = this.inputSlots.shift();
    if (frame === undefined || slot === undefined) {
      if (slot !== undefined) this.inputSlots.unshift(slot);
      if (frame !== undefined) this.frames.offer(frame);
      return;
    }
    slot.buffer.memory = frame.payload.buffer;
    slot.buffer.pts = Number(frame.timestampNs / 1000n);
    slot.buffer.flag = media.BufferFlag.NONE;
    candidate.pushInputData(slot.index).catch((error: Error) => {
      if (this.isCurrent(owner, candidate)) this.listener?.onDecoderError(error.message);
    });
  }

  private ensureCurrent(owner: number, candidate: media.VideoDecoder): void {
    if (!this.isCurrent(owner, candidate)) throw new Error('Decoder configuration superseded');
  }

  private isCurrent(owner: number, candidate: media.VideoDecoder): boolean {
    return owner === this.generation && this.decoder === candidate;
  }
}
