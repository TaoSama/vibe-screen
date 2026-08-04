import { media } from '@kit.AVCodecKit';
import { Codec } from '../core/protocol/ProtocolModels';
import { EncodedFrame, LatestFrameQueue } from '../core/media/LatestFrameQueue';

const VIDEO_MIME_H264: string = 'video/avc';
const VIDEO_MIME_HEVC: string = 'video/hevc';

export class HarmonyVideoDecoder {
  private decoder: media.VideoDecoder | undefined;
  private frames: LatestFrameQueue = new LatestFrameQueue();
  private epoch: bigint = 0n;

  async configure(codec: Codec, width: number, height: number, surfaceId: string, epoch: bigint): Promise<void> {
    await this.release();
    if (codec !== Codec.H264 && codec !== Codec.HEVC) throw new Error('Unsupported hardware codec');
    const mime: string = codec === Codec.HEVC ? VIDEO_MIME_HEVC : VIDEO_MIME_H264;
    const candidate: media.VideoDecoder = await media.createVideoDecoderByMime(mime);
    candidate.on('error', (_error: Error) => { this.frames.clear(); });
    candidate.on('needInputData', (index: number, buffer: media.AVBuffer) => {
      const frame: EncodedFrame | undefined = this.frames.poll(this.epoch);
      if (frame === undefined) return;
      buffer.memory = frame.payload.buffer;
      buffer.pts = Number(frame.frameId);
      buffer.flag = frame.keyframe ? media.BufferFlag.CODEC_DATA : media.BufferFlag.NONE;
      candidate.pushInputData(index);
    });
    candidate.on('newOutputData', (index: number, _buffer: media.AVBuffer) => candidate.freeOutputBuffer(index, true));
    await candidate.configure({ mime, width, height });
    await candidate.setOutputSurface(surfaceId);
    await candidate.prepare();
    await candidate.start();
    this.decoder = candidate;
    this.epoch = epoch;
  }

  submit(frame: EncodedFrame): void { this.frames.offer(frame); }
  droppedFrames(): number { return this.frames.droppedCount(); }

  async release(): Promise<void> {
    const active: media.VideoDecoder | undefined = this.decoder;
    this.decoder = undefined;
    this.frames.clear();
    if (active !== undefined) { await active.stop(); await active.release(); }
  }
}

