export class AudioGate {
  private allowed = false;
  private resumeRequested = false;
  private revision = 0;
  private cancellers = new Set<() => void>();

  silence() {
    this.allowed = false;
    this.resumeRequested = false;
    this.revision += 1;
    this.cancellers.forEach((cancel) => cancel());
    this.cancellers.clear();
  }
  requestResume() { this.resumeRequested = true; this.allowed = false; }
  acceptResume(modeRevision: number) { if (this.resumeRequested) { this.allowed = true; this.revision = modeRevision; } }
  registerActiveOutput(cancel: () => void) { this.cancellers.add(cancel); return () => this.cancellers.delete(cancel); }
  permits(modeRevision: number) { return this.allowed && this.revision === modeRevision; }
  isResumeRequested() { return this.resumeRequested; }
  isAllowed() { return this.allowed; }
}

export const audioGate = new AudioGate();
