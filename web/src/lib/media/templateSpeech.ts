import type { PlaybackSink } from "./mediaGate";
import type { PcmPlaybackChunk } from "./pcmPlayback";

/**
 * A line of approved template text. Never model-authored prose: the rule
 * interpreter selects the template and this only reads it aloud.
 */
export interface SpeechRequest {
  text: string;
  lang?: string;
}

export interface TemplateSpeechOptions {
  synthesis?: SpeechSynthesis;
  createUtterance?: (text: string) => SpeechSynthesisUtterance;
}

const DEFAULT_LANG = "zh-TW";

export class BrowserTemplateSpeech implements PlaybackSink<SpeechRequest> {
  readonly #synthesis?: SpeechSynthesis;
  readonly #createUtterance: (text: string) => SpeechSynthesisUtterance;

  constructor(options: TemplateSpeechOptions = {}) {
    this.#synthesis =
      options.synthesis ??
      (typeof globalThis.speechSynthesis === "undefined" ? undefined : globalThis.speechSynthesis);
    this.#createUtterance =
      options.createUtterance ?? ((text) => new SpeechSynthesisUtterance(text));
  }

  /** False where the browser has no speech synthesis; callers degrade to screen only. */
  get available(): boolean {
    return this.#synthesis !== undefined;
  }

  enqueue(request: SpeechRequest): void {
    const synthesis = this.#synthesis;
    if (!synthesis || !request.text) return;
    const utterance = this.#createUtterance(request.text);
    utterance.lang = request.lang ?? DEFAULT_LANG;
    // Replace rather than append. A superseded instruction must never be read
    // out after the rules have already chosen a newer one.
    synthesis.cancel();
    synthesis.speak(utterance);
  }

  stopAll(): void {
    this.#synthesis?.cancel();
  }
}

const isSpeechRequest = (value: SpeechRequest | PcmPlaybackChunk): value is SpeechRequest =>
  typeof (value as SpeechRequest).text === "string";

/**
 * One playback sink for the media gate covering both guidance outputs, so a
 * single stopAll from the gate silences model audio and spoken templates
 * together.
 */
export class GuidanceOutput implements PlaybackSink<SpeechRequest | PcmPlaybackChunk> {
  constructor(
    readonly pcm: PlaybackSink<PcmPlaybackChunk>,
    readonly speech: PlaybackSink<SpeechRequest>,
  ) {}

  enqueue(value: SpeechRequest | PcmPlaybackChunk): void {
    if (isSpeechRequest(value)) this.speech.enqueue(value);
    else this.pcm.enqueue(value);
  }

  stopAll(): void {
    this.pcm.stopAll();
    this.speech.stopAll();
  }
}
