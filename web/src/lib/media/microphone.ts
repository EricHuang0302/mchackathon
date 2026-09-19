import type { CaptureSource } from "./mediaGate";

export interface MicrophoneOptions {
  mediaDevices?: Pick<MediaDevices, "getUserMedia">;
  createContext?: () => AudioContext;
  createWorkletNode?: (context: AudioContext) => AudioWorkletNode;
  workletUrl?: string;
}

export class BrowserMicrophone implements CaptureSource<Float32Array> {
  readonly #mediaDevices: Pick<MediaDevices, "getUserMedia">;
  readonly #createContext: () => AudioContext;
  readonly #createWorkletNode: (context: AudioContext) => AudioWorkletNode;
  readonly #workletUrl: string;
  #requestId = 0;
  #stream?: MediaStream;
  #context?: AudioContext;
  #nodes: AudioNode[] = [];
  #sampleRate?: number;

  constructor(options: MicrophoneOptions = {}) {
    this.#mediaDevices = options.mediaDevices ?? navigator.mediaDevices;
    this.#createContext =
      options.createContext ?? (() => new AudioContext({ latencyHint: "interactive" }));
    this.#createWorkletNode =
      options.createWorkletNode ??
      ((context) => new AudioWorkletNode(context, "pcm-capture"));
    this.#workletUrl =
      options.workletUrl ?? new URL("./pcmCaptureWorklet.js", import.meta.url).href;
  }

  async start(onSample: (sample: Float32Array) => void): Promise<void> {
    this.stop();
    const requestId = ++this.#requestId;
    const context = this.#createContext();
    let stream: MediaStream | undefined;

    try {
      await context.resume();
      stream = await this.#mediaDevices.getUserMedia({
        audio: { channelCount: { ideal: 1 } },
        video: false,
      });
      if (requestId !== this.#requestId) {
        await cleanup(context, stream, []);
        return;
      }

      await context.audioWorklet.addModule(this.#workletUrl);
      if (requestId !== this.#requestId) {
        await cleanup(context, stream, []);
        return;
      }

      const source = context.createMediaStreamSource(stream);
      const worklet = this.#createWorkletNode(context);
      const mute = context.createGain();
      mute.gain.value = 0;
      worklet.port.onmessage = (event) => {
        if (
          requestId === this.#requestId &&
          event.data instanceof Float32Array
        ) {
          onSample(event.data);
        }
      };
      source.connect(worklet);
      worklet.connect(mute);
      mute.connect(context.destination);

      this.#context = context;
      this.#stream = stream;
      this.#nodes = [source, worklet, mute];
      this.#sampleRate = context.sampleRate;
    } catch (error) {
      await cleanup(context, stream, []);
      throw error;
    }
  }

  stop(): void {
    this.#requestId++;
    const context = this.#context;
    const stream = this.#stream;
    const nodes = this.#nodes;
    this.#context = undefined;
    this.#stream = undefined;
    this.#nodes = [];
    this.#sampleRate = undefined;
    void cleanup(context, stream, nodes).catch(() => undefined);
  }

  get active(): boolean {
    return this.#stream?.getAudioTracks().some(
      (track) => track.readyState === "live",
    ) ?? false;
  }

  get sampleRate(): number | undefined {
    return this.#sampleRate;
  }
}

async function cleanup(
  context: AudioContext | undefined,
  stream: MediaStream | undefined,
  nodes: AudioNode[],
): Promise<void> {
  for (const node of nodes) node.disconnect();
  for (const track of stream?.getTracks() ?? []) track.stop();
  if (context && context.state !== "closed") await context.close();
}
