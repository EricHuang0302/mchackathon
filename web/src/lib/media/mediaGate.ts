export type InteractionMode =
  | "call_119"
  | "on_call"
  | "voice_guidance"
  | "handover";

export interface MediaPolicy {
  interactionMode: InteractionMode;
  guidancePaused: boolean;
  modeRevision: number;
}

export interface PlaybackSink<T> {
  enqueue(value: T): void;
  stopAll(): void;
}

export interface CaptureSource<T> {
  start(onSample: (sample: T) => void): Promise<void>;
  stop(): void;
}

export interface AudibleTimer {
  stop(): void;
}

export interface MediaGateStatus {
  policy: Readonly<MediaPolicy>;
  audioAllowed: boolean;
  captureActive: boolean;
}

type StatusListener = (status: MediaGateStatus) => void;

const DEFAULT_POLICY: MediaPolicy = {
  interactionMode: "call_119",
  guidancePaused: true,
  modeRevision: 0,
};

export class MediaGate<TPlayback = unknown, TSample = Float32Array> {
  readonly #playback: PlaybackSink<TPlayback>;
  readonly #capture: CaptureSource<TSample>;
  readonly #audibleTimer: AudibleTimer;
  readonly #listeners = new Set<StatusListener>();
  #policy: MediaPolicy = { ...DEFAULT_POLICY };
  #captureActive = false;
  #captureGeneration = 0;

  constructor(
    playback: PlaybackSink<TPlayback>,
    capture: CaptureSource<TSample>,
    audibleTimer: AudibleTimer,
  ) {
    this.#playback = playback;
    this.#capture = capture;
    this.#audibleTimer = audibleTimer;
  }

  applyPolicy(next: MediaPolicy): boolean {
    if (next.modeRevision < this.#policy.modeRevision) return false;

    if (
      next.modeRevision === this.#policy.modeRevision &&
      next.interactionMode !== this.#policy.interactionMode
    ) {
      return false;
    }

    this.#policy = { ...next };
    if (!this.#isAudioAllowed()) this.#stopOutputs();
    this.#notify();
    return true;
  }

  enqueuePlayback(value: TPlayback, modeRevision: number): boolean {
    if (!this.#accepts(modeRevision)) return false;
    this.#playback.enqueue(value);
    return true;
  }

  async startCapture(
    modeRevision: number,
    onSample: (sample: TSample) => void,
  ): Promise<boolean> {
    if (!this.#accepts(modeRevision)) return false;
    const generation = ++this.#captureGeneration;

    await this.#capture.start((sample) => {
      if (
        generation === this.#captureGeneration &&
        this.#accepts(modeRevision)
      ) {
        onSample(sample);
      }
    });

    if (
      generation !== this.#captureGeneration ||
      !this.#accepts(modeRevision)
    ) {
      this.#capture.stop();
      return false;
    }

    this.#captureActive = true;
    this.#notify();
    return true;
  }

  stopAll(): void {
    this.#stopOutputs();
    this.#notify();
  }

  subscribeStatus(listener: StatusListener): () => void {
    this.#listeners.add(listener);
    listener(this.status);
    return () => this.#listeners.delete(listener);
  }

  get status(): MediaGateStatus {
    return {
      policy: { ...this.#policy },
      audioAllowed: this.#isAudioAllowed(),
      captureActive: this.#captureActive,
    };
  }

  #accepts(modeRevision: number): boolean {
    return modeRevision === this.#policy.modeRevision && this.#isAudioAllowed();
  }

  #isAudioAllowed(): boolean {
    return (
      this.#policy.interactionMode === "voice_guidance" &&
      !this.#policy.guidancePaused
    );
  }

  #stopOutputs(): void {
    this.#captureGeneration++;
    this.#playback.stopAll();
    this.#capture.stop();
    this.#audibleTimer.stop();
    this.#captureActive = false;
  }

  #notify(): void {
    const status = this.status;
    for (const listener of this.#listeners) listener(status);
  }
}
