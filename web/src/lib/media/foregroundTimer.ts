export interface TimerTick {
  scheduledAt: number;
  observedAt: number;
}

export interface TimerClock {
  now(): number;
  schedule(callback: () => void, delayMs: number): unknown;
  cancel(handle: unknown): void;
}

const browserClock: TimerClock = {
  now: () => performance.now(),
  schedule: (callback, delayMs) => setTimeout(callback, delayMs),
  cancel: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class ForegroundTimer {
  readonly #intervalMs: number;
  readonly #onTick: (tick: TimerTick) => void;
  readonly #clock: TimerClock;
  #handle?: unknown;
  #nextAt = 0;
  #running = false;

  constructor(
    intervalMs: number,
    onTick: (tick: TimerTick) => void,
    clock: TimerClock = browserClock,
  ) {
    if (!Number.isFinite(intervalMs) || intervalMs <= 0) {
      throw new RangeError("intervalMs must be greater than zero");
    }
    this.#intervalMs = intervalMs;
    this.#onTick = onTick;
    this.#clock = clock;
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    this.#nextAt = this.#clock.now() + this.#intervalMs;
    this.#schedule();
  }

  pause(): void {
    if (this.#handle !== undefined) this.#clock.cancel(this.#handle);
    this.#handle = undefined;
    this.#running = false;
  }

  resume(): void {
    this.start();
  }

  stop(): void {
    this.pause();
    this.#nextAt = 0;
  }

  get running(): boolean {
    return this.#running;
  }

  #schedule(): void {
    const delay = Math.max(0, this.#nextAt - this.#clock.now());
    this.#handle = this.#clock.schedule(() => this.#fire(), delay);
  }

  #fire(): void {
    this.#handle = undefined;
    if (!this.#running) return;

    const observedAt = this.#clock.now();
    this.#onTick({ scheduledAt: this.#nextAt, observedAt });
    if (!this.#running) return;
    this.#nextAt = observedAt + this.#intervalMs;
    this.#schedule();
  }
}
