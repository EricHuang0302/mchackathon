import assert from "node:assert/strict";
import test from "node:test";

import { CameraCapture } from "./camera.ts";

test("requests the rear camera and stops every track", async () => {
  const constraints: MediaStreamConstraints[] = [];
  let stopped = 0;
  const tracks = [
    { readyState: "live", stop: () => stopped++ },
    { readyState: "live", stop: () => stopped++ },
  ];
  const stream = {
    getTracks: () => tracks,
  } as unknown as MediaStream;
  const mediaDevices = {
    getUserMedia: async (value: MediaStreamConstraints) => {
      constraints.push(value);
      return stream;
    },
  } as Pick<MediaDevices, "getUserMedia">;
  const camera = new CameraCapture(mediaDevices, {
    createElement: () => {
      throw new Error("not used");
    },
  } as unknown as Pick<Document, "createElement">);

  assert.equal(await camera.start(), stream);
  assert.deepEqual(constraints, [
    {
      audio: false,
      video: { facingMode: { ideal: "environment" } },
    },
  ]);
  assert.equal(camera.active, true);

  camera.stop();
  assert.equal(stopped, 2);
  assert.equal(camera.active, false);
});
