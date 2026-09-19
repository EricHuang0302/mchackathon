import { assert, test } from "vitest";

import { bytesToBase64, Pcm16Encoder } from "./pcm16";

test("resamples streaming float audio to little-endian 16 kHz PCM16", () => {
  const encoder = new Pcm16Encoder(48_000);
  const first = encoder.encode(new Float32Array(480).fill(1));
  const second = encoder.encode(new Float32Array(480).fill(-1));

  assert.equal(first.byteLength, 320);
  assert.equal(second.byteLength, 320);
  assert.equal(new DataView(first.buffer).getInt16(0, true), 32_767);
  assert.equal(new DataView(second.buffer).getInt16(0, true), -32_768);
  assert.equal(atob(bytesToBase64(first)).length, first.byteLength);
});
