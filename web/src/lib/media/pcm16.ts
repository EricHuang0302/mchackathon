const PCM16_MIN = -32_768;
const PCM16_MAX = 32_767;

export class Pcm16Encoder {
  readonly #step: number;
  #buffer: Float32Array<ArrayBufferLike> = new Float32Array();
  #position = 0;

  constructor(inputSampleRate: number, outputSampleRate = 16_000) {
    if (inputSampleRate <= 0 || outputSampleRate <= 0) {
      throw new RangeError("Sample rates must be positive");
    }
    this.#step = inputSampleRate / outputSampleRate;
  }

  encode(samples: Float32Array): Uint8Array {
    if (samples.length === 0) return new Uint8Array();
    this.#buffer = append(this.#buffer, samples);
    const output: number[] = [];

    while (this.#position + 1 < this.#buffer.length) {
      const left = Math.floor(this.#position);
      const fraction = this.#position - left;
      const sample =
        this.#buffer[left]! * (1 - fraction) +
        this.#buffer[left + 1]! * fraction;
      output.push(toPcm16(sample));
      this.#position += this.#step;
    }

    const consumed = Math.floor(this.#position);
    if (consumed > 0) {
      this.#buffer = this.#buffer.slice(consumed);
      this.#position -= consumed;
    }

    const bytes = new Uint8Array(output.length * 2);
    const view = new DataView(bytes.buffer);
    output.forEach((sample, index) => view.setInt16(index * 2, sample, true));
    return bytes;
  }

  reset(): void {
    this.#buffer = new Float32Array();
    this.#position = 0;
  }
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function append(
  left: Float32Array<ArrayBufferLike>,
  right: Float32Array<ArrayBufferLike>,
): Float32Array<ArrayBufferLike> {
  if (left.length === 0) return right.slice();
  const combined = new Float32Array(left.length + right.length);
  combined.set(left);
  combined.set(right, left.length);
  return combined;
}

function toPcm16(sample: number): number {
  const clamped = Math.max(-1, Math.min(1, sample));
  return Math.round(clamped < 0 ? clamped * -PCM16_MIN : clamped * PCM16_MAX);
}
