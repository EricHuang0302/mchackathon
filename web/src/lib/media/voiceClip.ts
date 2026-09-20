import { BrowserMicrophone } from "./microphone";
import { Pcm16Encoder, bytesToBase64 } from "./pcm16";

/**
 * Records one short scene report as 16 kHz mono PCM16 and wraps it as a WAV.
 *
 * A clip has an end the user chooses. Continuous streaming left that decision
 * to voice activity detection, which at a noisy scene may never decide the
 * speaker stopped, so nothing was ever transcribed. The same encoder feeds this
 * as fed the Live path, so the audio the backend receives is unchanged.
 */

export const SAMPLE_RATE = 16_000;
const BYTES_PER_SAMPLE = 2;

/** Bounded so one clip stays inside the request limit the endpoint enforces. */
export const MAX_CLIP_SECONDS = 20;
const MAX_CLIP_BYTES = MAX_CLIP_SECONDS * SAMPLE_RATE * BYTES_PER_SAMPLE;

export interface VoiceClip {
  audioBase64: string;
  mimeType: "audio/wav";
  seconds: number;
}

export interface VoiceClipRecorderOptions {
  microphone?: BrowserMicrophone;
  /** Reports elapsed seconds so the UI can show a countdown. */
  onProgress?: (seconds: number) => void;
  /** Called when the clip reaches MAX_CLIP_SECONDS and recording stops itself. */
  onLimitReached?: () => void;
}

export class VoiceClipRecorder {
  readonly #microphone: BrowserMicrophone;
  readonly #onProgress: (seconds: number) => void;
  readonly #onLimitReached: () => void;
  #encoder: Pcm16Encoder | null = null;
  #chunks: Uint8Array[] = [];
  #bytes = 0;
  #recording = false;
  #limitReached = false;

  constructor(options: VoiceClipRecorderOptions = {}) {
    this.#microphone = options.microphone ?? new BrowserMicrophone();
    this.#onProgress = options.onProgress ?? (() => undefined);
    this.#onLimitReached = options.onLimitReached ?? (() => undefined);
  }

  get recording(): boolean {
    return this.#recording;
  }

  async start(): Promise<void> {
    if (this.#recording) return;
    this.#encoder = null;
    this.#chunks = [];
    this.#bytes = 0;
    this.#limitReached = false;
    this.#recording = true;
    try {
      await this.#microphone.start((samples) => this.#accept(samples));
    } catch (error) {
      this.#recording = false;
      this.#microphone.stop();
      throw error;
    }
  }

  /** Stops the microphone and returns the clip, or null when nothing was captured. */
  stop(): VoiceClip | null {
    if (!this.#recording) return null;
    this.#recording = false;
    this.#microphone.stop();
    const pcm = concat(this.#chunks, this.#bytes);
    this.#chunks = [];
    this.#bytes = 0;
    this.#encoder = null;
    if (pcm.length === 0) return null;
    return {
      audioBase64: bytesToBase64(wavFromPcm16(pcm)),
      mimeType: "audio/wav",
      seconds: pcm.length / BYTES_PER_SAMPLE / SAMPLE_RATE,
    };
  }

  /** Drops anything captured so far without producing a clip. */
  cancel(): void {
    this.#recording = false;
    this.#microphone.stop();
    this.#chunks = [];
    this.#bytes = 0;
    this.#encoder = null;
  }

  #accept(samples: Float32Array): void {
    if (!this.#recording || this.#limitReached) return;
    const sampleRate = this.#microphone.sampleRate;
    if (!sampleRate) return;
    this.#encoder ??= new Pcm16Encoder(sampleRate, SAMPLE_RATE);
    const bytes = this.#encoder.encode(samples);
    if (bytes.length === 0) return;
    this.#chunks.push(bytes);
    this.#bytes += bytes.length;
    this.#onProgress(this.#bytes / BYTES_PER_SAMPLE / SAMPLE_RATE);
    if (this.#bytes >= MAX_CLIP_BYTES) {
      this.#limitReached = true;
      this.#onLimitReached();
    }
  }
}

function concat(chunks: Uint8Array[], total: number): Uint8Array {
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

export function wavFromPcm16(pcm: Uint8Array, sampleRate = SAMPLE_RATE): Uint8Array {
  const file = new Uint8Array(44 + pcm.length);
  const view = new DataView(file.buffer);
  const ascii = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  ascii(0, "RIFF");
  view.setUint32(4, 36 + pcm.length, true);
  ascii(8, "WAVE");
  ascii(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * BYTES_PER_SAMPLE, true);
  view.setUint16(32, BYTES_PER_SAMPLE, true);
  view.setUint16(34, 16, true);
  ascii(36, "data");
  view.setUint32(40, pcm.length, true);
  file.set(pcm, 44);
  return file;
}
