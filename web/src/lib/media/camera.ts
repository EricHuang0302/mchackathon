export interface CameraFrame {
  blob: Blob;
  capturedAt: string;
  modeRevision: number;
}

export interface CaptureFrameOptions {
  modeRevision: number;
  currentModeRevision: () => number;
  maxDimension?: number;
  mimeType?: "image/jpeg" | "image/webp";
  quality?: number;
}

export class CameraCapture {
  readonly #mediaDevices: Pick<MediaDevices, "getUserMedia">;
  readonly #document: Pick<Document, "createElement">;
  #stream?: MediaStream;
  #requestId = 0;

  constructor(
    mediaDevices: Pick<MediaDevices, "getUserMedia"> = navigator.mediaDevices,
    documentRef: Pick<Document, "createElement"> = document,
  ) {
    this.#mediaDevices = mediaDevices;
    this.#document = documentRef;
  }

  async start(videoConstraints: MediaTrackConstraints = {}): Promise<MediaStream> {
    this.stop();
    const requestId = ++this.#requestId;
    const stream = await this.#mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        ...videoConstraints,
      },
    });

    if (requestId !== this.#requestId) {
      stopTracks(stream);
      throw new DOMException("Camera request was cancelled", "AbortError");
    }

    this.#stream = stream;
    return stream;
  }

  async attach(video: HTMLVideoElement): Promise<void> {
    if (!this.#stream) throw new Error("Camera is not started");
    video.playsInline = true;
    video.muted = true;
    video.srcObject = this.#stream;
    await video.play();
  }

  async capture(
    video: HTMLVideoElement,
    options: CaptureFrameOptions,
  ): Promise<CameraFrame> {
    if (!this.#stream) throw new Error("Camera is not started");
    const requestId = this.#requestId;
    assertCurrentRevision(options);
    const maxDimension = options.maxDimension ?? 1_280;
    if (!Number.isFinite(maxDimension) || maxDimension <= 0) {
      throw new RangeError("maxDimension must be greater than zero");
    }
    if (video.videoWidth <= 0 || video.videoHeight <= 0) {
      throw new Error("Camera frame is not ready");
    }

    const scale = Math.min(
      1,
      maxDimension / Math.max(video.videoWidth, video.videoHeight),
    );
    const canvas = this.#document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas is unavailable");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (value) =>
          value ? resolve(value) : reject(new Error("Frame encoding failed")),
        options.mimeType ?? "image/jpeg",
        options.quality ?? 0.8,
      );
    });
    if (requestId !== this.#requestId) {
      throw new DOMException("Camera frame was cancelled", "AbortError");
    }
    assertCurrentRevision(options);
    return {
      blob,
      capturedAt: new Date().toISOString(),
      modeRevision: options.modeRevision,
    };
  }

  stop(): void {
    this.#requestId++;
    if (this.#stream) stopTracks(this.#stream);
    this.#stream = undefined;
  }

  get active(): boolean {
    return this.#stream?.getTracks().some((track) => track.readyState === "live") ?? false;
  }
}

function assertCurrentRevision(options: CaptureFrameOptions): void {
  if (options.modeRevision !== options.currentModeRevision()) {
    throw new DOMException("Camera frame revision is stale", "AbortError");
  }
}

function stopTracks(stream: MediaStream): void {
  for (const track of stream.getTracks()) track.stop();
}
