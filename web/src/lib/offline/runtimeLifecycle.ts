export type SuspendReason = "hidden" | "pagehide" | "telephone";
export type ResumeReason = "visible" | "pageshow";

export interface RuntimeLifecycleOptions {
  stopMedia: () => void;
  pauseTimers: () => void;
  onSuspend: (reason: SuspendReason) => void;
  onResumeAvailable: (reason: ResumeReason) => void;
  onOnline?: () => void;
  onOffline?: () => void;
  document?: Pick<
    Document,
    "visibilityState" | "addEventListener" | "removeEventListener"
  >;
  window?: Pick<Window, "addEventListener" | "removeEventListener">;
}

export class RuntimeLifecycle {
  readonly #options: RuntimeLifecycleOptions;
  readonly #document: NonNullable<RuntimeLifecycleOptions["document"]>;
  readonly #window: NonNullable<RuntimeLifecycleOptions["window"]>;
  #started = false;
  #suspended = false;

  constructor(options: RuntimeLifecycleOptions) {
    this.#options = options;
    this.#document = options.document ?? document;
    this.#window = options.window ?? window;
  }

  start(): void {
    if (this.#started) return;
    this.#started = true;
    this.#document.addEventListener("visibilitychange", this.#visibilityChange);
    this.#window.addEventListener("pagehide", this.#pageHide);
    this.#window.addEventListener("pageshow", this.#pageShow);
    this.#window.addEventListener("online", this.#online);
    this.#window.addEventListener("offline", this.#offline);
    if (this.#document.visibilityState === "hidden") this.#suspend("hidden");
  }

  stop(): void {
    if (!this.#started) return;
    this.#started = false;
    this.#document.removeEventListener(
      "visibilitychange",
      this.#visibilityChange,
    );
    this.#window.removeEventListener("pagehide", this.#pageHide);
    this.#window.removeEventListener("pageshow", this.#pageShow);
    this.#window.removeEventListener("online", this.#online);
    this.#window.removeEventListener("offline", this.#offline);
  }

  beforeTelephoneHandoff(): void {
    this.#suspend("telephone");
  }

  get suspended(): boolean {
    return this.#suspended;
  }

  readonly #visibilityChange = (): void => {
    if (this.#document.visibilityState === "hidden") this.#suspend("hidden");
    else this.#resumeAvailable("visible");
  };

  readonly #pageHide = (): void => this.#suspend("pagehide");
  readonly #pageShow = (): void => this.#resumeAvailable("pageshow");
  readonly #online = (): void => this.#options.onOnline?.();
  readonly #offline = (): void => this.#options.onOffline?.();

  #suspend(reason: SuspendReason): void {
    if (this.#suspended) return;
    this.#options.stopMedia();
    this.#options.pauseTimers();
    this.#suspended = true;
    this.#options.onSuspend(reason);
  }

  #resumeAvailable(reason: ResumeReason): void {
    if (!this.#suspended) return;
    this.#suspended = false;
    this.#options.onResumeAvailable(reason);
  }
}
