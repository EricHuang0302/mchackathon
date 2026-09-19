import type { PlaybackSink } from "./mediaGate";

export interface PcmPlaybackChunk {
  samples: Float32Array;
  sampleRate: number;
}

export interface PcmPlaybackOptions {
  createContext?: () => AudioContext;
}

export class BrowserPcmPlayback implements PlaybackSink<PcmPlaybackChunk> {
  readonly #createContext: () => AudioContext;
  readonly #sources = new Set<AudioBufferSourceNode>();
  #context?: AudioContext;
  #nextAt = 0;

  constructor(options: PcmPlaybackOptions = {}) {
    this.#createContext =
      options.createContext ?? (() => new AudioContext({ latencyHint: "interactive" }));
  }

  async enable(): Promise<void> {
    this.#context ??= this.#createContext();
    await this.#context.resume();
    this.#nextAt = Math.max(this.#nextAt, this.#context.currentTime);
  }

  enqueue(chunk: PcmPlaybackChunk): void {
    const context = this.#context;
    if (!context || context.state !== "running") {
      throw new Error("Audio playback requires a user gesture");
    }
    if (!Number.isFinite(chunk.sampleRate) || chunk.sampleRate <= 0) {
      throw new RangeError("sampleRate must be greater than zero");
    }
    if (chunk.samples.length === 0) return;

    const buffer = context.createBuffer(
      1,
      chunk.samples.length,
      chunk.sampleRate,
    );
    const samples = new Float32Array(chunk.samples.length);
    samples.set(chunk.samples);
    buffer.copyToChannel(samples, 0);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = () => {
      source.disconnect();
      this.#sources.delete(source);
    };

    const startAt = Math.max(context.currentTime, this.#nextAt);
    this.#nextAt = startAt + buffer.duration;
    this.#sources.add(source);
    source.start(startAt);
  }

  stopAll(): void {
    for (const source of this.#sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // A source that already ended is safe to ignore.
      }
      source.disconnect();
    }
    this.#sources.clear();
    this.#nextAt = this.#context?.currentTime ?? 0;
  }

  async close(): Promise<void> {
    this.stopAll();
    const context = this.#context;
    this.#context = undefined;
    if (context && context.state !== "closed") await context.close();
  }

  get enabled(): boolean {
    return this.#context?.state === "running";
  }
}
