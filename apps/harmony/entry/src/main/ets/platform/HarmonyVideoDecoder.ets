import { media } from '@kit.AVCodecKit';
import { Codec } from '../core/protocol/ProtocolModels';
import { DecoderLifecycle } from '../core/media/DecoderLifecycle';
import { EncodedFrame, FrameQueueEffect, LatestFrameQueue } from '../core/media/LatestFrameQueue';

const VIDEO_MIME_H264: string = 'video/avc';
const VIDEO_MIME_HEVC: string = 'video/hevc';
const MAX_CONSECUTIVE_INPUT_FAILURES: number = 3;

export interface VideoDecoderListener {
  onDecoderError(message: string): void;
  onFrameRendered(): void;
  onKeyframeRequired?(reason: string): void;
  onDecoderWarning?(message: string): void;
}
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
  private consecutiveInputFailures: number = 0;

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
    this.decoder = candidate; this.listener = listener; this.epoch = epoch; this.consecutiveInputFailures = 0;
    this.frames.reset(epoch);
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
      try {
        Promise.resolve(candidate.freeOutputBuffer(index, true)).then(() => {
          if (this.isCurrent(owner, candidate)) listener.onFrameRendered();
        }).catch((error: Error) => {
          if (this.isCurrent(owner, candidate)) listener.onDecoderError(`output_render_failed:${error.message}`);
        });
      } catch (error) {
        listener.onDecoderError(`output_render_failed:${this.errorMessage(error as Object)}`);
      }
    });
    await DecoderLifecycle.initialize({
      configure: async (): Promise<void> => candidate.configure({ mime, width, height }),
      setOutputSurface: async (): Promise<void> => candidate.setOutputSurface(surfaceId),
      prepare: async (): Promise<void> => candidate.prepare(),
      start: async (): Promise<void> => candidate.start(),
      stop: async (): Promise<void> => candidate.stop(),
      release: async (): Promise<void> => candidate.release()
    }, {
      isCurrent: (): boolean => this.isCurrent(owner, candidate),
      claimForCleanup: (): boolean => this.detachCandidateForCleanup(candidate)
    });
    this.started = true;
  }

  submit(frame: EncodedFrame): void {
    this.emitQueueEffect(this.frames.offer(frame), 'decoder_reference_lost');
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
    this.consecutiveInputFailures = 0;
    return detached;
  }

  private detachCandidateForCleanup(candidate: media.VideoDecoder): boolean {
    if (this.decoder !== candidate) return false;
    this.decoder = undefined; this.started = false; this.inputSlots = []; this.frames.clear(); this.listener = undefined;
    this.consecutiveInputFailures = 0;
    return true;
  }

  private async releaseDetached(detached: DetachedDecoder): Promise<void> {
    const failures: string[] = [];
    if (detached.started) {
      try { await detached.decoder.stop(); }
      catch (error) { failures.push(`stop: ${this.errorMessage(error)}`); }
    }
    try { await detached.decoder.release(); }
    catch (error) { failures.push(`release: ${this.errorMessage(error)}`); }
    if (failures.length > 0) throw new Error(failures.join('; '));
  }

  private drain(candidate: media.VideoDecoder, owner: number): void {
    if (!this.isCurrent(owner, candidate) || this.frames.hasPushInFlight()) return;
    const slot: InputSlot | undefined = this.inputSlots.shift();
    if (slot === undefined) return;
    const frame: EncodedFrame | undefined = this.frames.beginPush();
    if (frame === undefined) { this.inputSlots.unshift(slot); return; }
    slot.buffer.memory = frame.payload.buffer;
    slot.buffer.pts = Number(frame.timestampNs / 1000n);
    slot.buffer.flag = media.BufferFlag.NONE;
    candidate.pushInputData(slot.index).then(() => {
      if (!this.isCurrent(owner, candidate)) return;
      if (!this.frames.hasPushInFlight()) return;
      this.consecutiveInputFailures = 0;
      this.emitQueueEffect(this.frames.completePush(true), 'decoder_reference_lost');
      this.drain(candidate, owner);
    }).catch((error: Error) => {
      if (!this.isCurrent(owner, candidate)) return;
      if (!this.frames.hasPushInFlight()) return;
      this.consecutiveInputFailures += 1;
      this.emitQueueEffect(this.frames.completePush(false), 'decoder_input_push_failed');
      this.listener?.onDecoderWarning?.(`decoder_input_push_failed:${error.message}`);
      if (this.consecutiveInputFailures >= MAX_CONSECUTIVE_INPUT_FAILURES) {
        this.listener?.onDecoderError('decoder_input_push_failed_repeatedly');
        return;
      }
      this.drain(candidate, owner);
    });
  }

  private emitQueueEffect(effect: FrameQueueEffect, reason: string): void {
    if (effect.requestKeyframe) this.listener?.onKeyframeRequired?.(reason);
  }

  private isCurrent(owner: number, candidate: media.VideoDecoder): boolean {
    return owner === this.generation && this.decoder === candidate;
  }

  private errorMessage(error: Object): string {
    return error instanceof Error ? error.message : String(error);
  }
}
