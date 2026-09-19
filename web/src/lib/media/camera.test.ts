import { assert, expect, test } from "vitest";

import { CameraCapture } from "./camera";

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

test("rejects a camera frame from an old mode revision", async () => {
  const stream = {
    getTracks: () => [{ readyState: "live", stop: () => undefined }],
  } as unknown as MediaStream;
  const camera = new CameraCapture(
    {
      getUserMedia: async () => stream,
    } as Pick<MediaDevices, "getUserMedia">,
    {
      createElement: () => {
        throw new Error("stale capture must not create a canvas");
      },
    } as unknown as Pick<Document, "createElement">,
  );
  await camera.start();
  const video = { videoWidth: 640, videoHeight: 480 } as HTMLVideoElement;

  await expect(
    camera.capture(video, {
      modeRevision: 1,
      currentModeRevision: () => 2,
    }),
  ).rejects.toMatchObject({ name: "AbortError" });
});

test("stopping the camera cancels an in-flight frame encoding", async () => {
  const stream = {
    getTracks: () => [{ readyState: "live", stop: () => undefined }],
  } as unknown as MediaStream;
  let encoded!: (blob: Blob | null) => void;
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ({ drawImage: () => undefined }),
    toBlob: (callback: (blob: Blob | null) => void) => {
      encoded = callback;
    },
  } as unknown as HTMLCanvasElement;
  const camera = new CameraCapture(
    { getUserMedia: async () => stream } as Pick<MediaDevices, "getUserMedia">,
    { createElement: () => canvas } as unknown as Pick<Document, "createElement">,
  );
  await camera.start();
  const capture = camera.capture(
    { videoWidth: 640, videoHeight: 480 } as HTMLVideoElement,
    { modeRevision: 2, currentModeRevision: () => 2 },
  );

  camera.stop();
  encoded(new Blob());

  await expect(capture).rejects.toMatchObject({ name: "AbortError" });
});

test("a denied camera permission leaves capture inactive", async () => {
  const denied = new DOMException("denied", "NotAllowedError");
  const camera = new CameraCapture(
    {
      getUserMedia: async () => {
        throw denied;
      },
    } as Pick<MediaDevices, "getUserMedia">,
    { createElement: () => document.createElement("canvas") },
  );

  await expect(camera.start()).rejects.toBe(denied);
  assert.equal(camera.active, false);
});
