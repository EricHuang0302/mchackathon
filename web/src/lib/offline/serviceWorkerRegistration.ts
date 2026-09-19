export interface OfflineWorkerOptions {
  scriptUrl: string;
  approvedAssets: string[];
  incidentActive: () => boolean;
  scope?: string;
  container?: ServiceWorkerContainer;
}

export interface OfflineWorkerHandle {
  registration: ServiceWorkerRegistration;
  updatePending(): boolean;
  activateUpdate(explicitReload?: boolean): boolean;
}

export async function registerOfflineWorker(
  options: OfflineWorkerOptions,
): Promise<OfflineWorkerHandle | undefined> {
  const container =
    options.container ??
    (typeof navigator === "undefined" ? undefined : navigator.serviceWorker);
  if (!container) return undefined;

  const registration = await container.register(options.scriptUrl, {
    scope: options.scope ?? "/",
  });
  const cacheApproved = (worker?: ServiceWorker | null) => {
    worker?.postMessage({
      type: "cache.approved",
      assets: options.approvedAssets,
    });
  };
  cacheApproved(registration.active);
  cacheApproved(registration.waiting);
  registration.addEventListener("updatefound", () => {
    const worker = registration.installing;
    worker?.addEventListener("statechange", () => {
      if (worker.state === "installed") cacheApproved(worker);
    });
  });

  return {
    registration,
    updatePending: () => registration.waiting !== null,
    activateUpdate: (explicitReload = false) => {
      if (
        (options.incidentActive() && !explicitReload) ||
        !registration.waiting
      ) {
        return false;
      }
      registration.waiting.postMessage({ type: "activate.update" });
      return true;
    },
  };
}
