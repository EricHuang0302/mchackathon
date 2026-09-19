export interface GuidanceLease {
  supported: boolean;
  acquired: boolean;
  release(): void;
  done: Promise<void>;
}

export async function acquireGuidanceLock(
  incidentId: string,
  lockManager: LockManager | undefined = getLockManager(),
): Promise<GuidanceLease> {
  if (!lockManager) {
    return {
      supported: false,
      acquired: false,
      release: () => undefined,
      done: Promise.resolve(),
    };
  }

  let releaseHold = (): void => undefined;
  let released = false;
  const hold = new Promise<void>((resolve) => {
    releaseHold = resolve;
  });
  let resolveReady!: (acquired: boolean) => void;
  let rejectReady!: (error: unknown) => void;
  const ready = new Promise<boolean>((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  const done = lockManager
    .request(
      `first-aid-copilot:incident:${incidentId}:guidance`,
      { mode: "exclusive", ifAvailable: true },
      async (lock) => {
        resolveReady(Boolean(lock));
        if (lock) await hold;
      },
    )
    .catch((error) => {
      rejectReady(error);
      throw error;
    });
  const acquired = await ready;

  return {
    supported: true,
    acquired,
    release: () => {
      if (released) return;
      released = true;
      releaseHold();
    },
    done,
  };
}

function getLockManager(): LockManager | undefined {
  return typeof navigator !== "undefined" && "locks" in navigator
    ? navigator.locks
    : undefined;
}
