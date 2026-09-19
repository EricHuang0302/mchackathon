import type { RestClient } from "./restClient.ts";

export interface EventBatchEvent {
  eventId: string;
  type: string;
  detail: unknown;
  clientId: string;
  clientInstanceId: string;
  clientSequence: number;
  clientTime: string;
  authorityEpoch: number;
  stateRevision: number;
  modeRevision: number;
  ruleVersion: string;
}

export interface EventConflict {
  eventId: string;
  code?: string;
  message?: string;
}

export interface EventBatchResponse {
  acknowledgements: Array<{ eventId: string }>;
  conflicts: EventConflict[];
  reconciledState?: unknown;
}

export interface EventBatchStore {
  listPendingEvents(
    incidentId: string,
    limit: number,
  ): Promise<EventBatchEvent[]>;
  acknowledgeEvents(eventIds: string[]): Promise<void>;
  markConflicts(conflicts: EventConflict[]): Promise<void>;
  saveReconciledState(
    incidentId: string,
    state: unknown,
    options: { preserveLocalMode: true },
  ): Promise<void>;
}

export type EventBatchSyncState =
  | "idle"
  | "syncing"
  | "resyncing"
  | "paused"
  | "error";

type StateListener = (state: EventBatchSyncState) => void;

const BATCH_SIZE = 50;

export class EventBatchSync {
  readonly #client: Pick<RestClient, "request">;
  readonly #store: EventBatchStore;
  readonly #listeners = new Set<StateListener>();
  #state: EventBatchSyncState = "idle";
  #active?: Promise<void>;

  constructor(client: Pick<RestClient, "request">, store: EventBatchStore) {
    this.#client = client;
    this.#store = store;
  }

  flush(incidentId: string): Promise<void> {
    if (this.#state === "paused") return Promise.resolve();
    if (this.#active) return this.#active;

    this.#active = this.#flush(incidentId).finally(() => {
      this.#active = undefined;
    });
    return this.#active;
  }

  pause(): void {
    this.#setState("paused");
  }

  resume(): void {
    if (this.#state === "paused") this.#setState("idle");
  }

  subscribeState(listener: StateListener): () => void {
    this.#listeners.add(listener);
    listener(this.#state);
    return () => this.#listeners.delete(listener);
  }

  get state(): EventBatchSyncState {
    return this.#state;
  }

  async #flush(incidentId: string): Promise<void> {
    this.#setState("syncing");

    try {
      while (this.#state !== "paused") {
        const events = await this.#store.listPendingEvents(
          incidentId,
          BATCH_SIZE,
        );
        if (events.length === 0) {
          this.#setState("idle");
          return;
        }

        const response = await this.#client.request<EventBatchResponse>(
          "POST",
          `/v1/incidents/${encodeURIComponent(incidentId)}/event-batches`,
          { body: { events } },
        );
        const acknowledged = response.acknowledgements.map(
          ({ eventId }) => eventId,
        );

        if (acknowledged.length > 0) {
          await this.#store.acknowledgeEvents(acknowledged);
        }
        if (response.reconciledState !== undefined) {
          await this.#store.saveReconciledState(
            incidentId,
            response.reconciledState,
            { preserveLocalMode: true },
          );
        }
        if (response.conflicts.length > 0) {
          await this.#store.markConflicts(response.conflicts);
          this.#setState("resyncing");
          return;
        }
        if (acknowledged.length === 0) {
          throw new Error("Event batch made no progress");
        }
      }
    } catch (error) {
      if (this.#state !== "paused") this.#setState("error");
      throw error;
    }
  }

  #setState(state: EventBatchSyncState): void {
    this.#state = state;
    for (const listener of this.#listeners) listener(state);
  }
}
