import { BufferTarget, CanvasSource, Mp4OutputFormat, Output, QUALITY_HIGH, QUALITY_MEDIUM, WebMOutputFormat, getFirstEncodableVideoCodec, type VideoCodec } from 'mediabunny';

export type Container = 'mp4' | 'webm';

export interface EncoderChoice { container: Container; codec: VideoCodec; tried: string[] }
export interface VideoResult {
  bytes: ArrayBuffer;
  container: Container;
  codec: VideoCodec;
  codecString: string;
  frames: number;
  seconds: number;
  fps: number;
  width: number;
  height: number;
  ms: number;
}

export const MAX_EDGE = 3840;

export async function chooseEncoder(width: number, height: number, fps: number): Promise<EncoderChoice | { none: string; tried: string[] }> {
  if (typeof VideoEncoder === 'undefined' || typeof VideoFrame === 'undefined') return { none: 'This webview has no WebCodecs video encoder.', tried: [] };
  const tried: string[] = [];
  const opts = { width, height, frameRate: fps, quality: QUALITY_HIGH };
  const avc = await getFirstEncodableVideoCodec(['avc'], opts);
  tried.push(`avc ${avc ? 'supported' : 'not supported'}`);
  if (avc) return { container: 'mp4', codec: avc, tried };
  for (const c of ['vp9', 'av1', 'vp8'] as VideoCodec[]) {
    const hit = await getFirstEncodableVideoCodec([c], opts);
    tried.push(`${c} ${hit ? 'supported' : 'not supported'}`);
    if (hit) return { container: 'webm', codec: hit, tried };
  }
  return { none: `No video codec can encode ${width} by ${height} at ${fps} frames per second here (${tried.join(', ')}).`, tried };
}

export interface ExportJob {
  width: number;
  height: number;
  fps: number;
  frames: number;
  choice: EncoderChoice;
  canvas: HTMLCanvasElement;
  draw(index: number): Promise<void>;
  signal?: AbortSignal;
  progress?(done: number, total: number): void;
}

export async function encode(job: ExportJob): Promise<VideoResult> {
  const t0 = performance.now();
  const target = new BufferTarget();
  const output = new Output({ format: job.choice.container === 'mp4' ? new Mp4OutputFormat({ fastStart: 'in-memory' }) : new WebMOutputFormat(), target });
  let codecString = '';
  const source = new CanvasSource(job.canvas, { codec: job.choice.codec, quality: job.width * job.height > 1920 * 1080 ? QUALITY_MEDIUM : QUALITY_HIGH, keyFrameInterval: 2, onEncoderConfig: (c) => { codecString = c.codec; } });
  output.addVideoTrack(source, { frameRate: job.fps });
  await output.start();
  try {
    for (let i = 0; i < job.frames; i++) {
      if (job.signal?.aborted) throw new DOMException('Export cancelled', 'AbortError');
      await job.draw(i);
      await source.add(i / job.fps, 1 / job.fps);
      job.progress?.(i + 1, job.frames);
    }
    await output.finalize();
  } catch (e) {
    await output.cancel().catch(() => undefined);
    throw e;
  }
  const bytes = target.buffer;
  if (!bytes) throw new Error('The video muxer produced no data.');
  return { bytes, container: job.choice.container, codec: job.choice.codec, codecString, frames: job.frames, seconds: job.frames / job.fps, fps: job.fps, width: job.width, height: job.height, ms: performance.now() - t0 };
}
