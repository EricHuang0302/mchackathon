import type { RestClient } from "./restClient";
import { z } from "zod";

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
}

export type EventAcknowledgement = EventConflict & {
  status: "accepted" | "duplicate" | "conflict";
};

export interface EventBatchResponse {
  acknowledgements: EventAcknowledgement[];
  stateRevision: number;
  modeRevision: number;
  snapshotRevision: number;
  authorityEpoch: number;
  lastAcknowledgedClientSequence: number | null;
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
    if (this.#state === "paused" || this.#state === "resyncing") {
      return Promise.resolve();
    }
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

        const response = parseEventBatchResponse(await this.#client.request<unknown>(
          "POST",
          `/v1/incidents/${encodeURIComponent(incidentId)}/event-batches`,
          { body: { events } },
        ));
        const acknowledged = response.acknowledgements
          .filter(({ status }) => status === "accepted" || status === "duplicate")
          .map(({ eventId }) => eventId);
        const conflicts = response.acknowledgements
          .filter(({ status }) => status === "conflict")
          .map(({ eventId, code }) => ({ eventId, code }));

        if (acknowledged.length > 0) {
          await this.#store.acknowledgeEvents(acknowledged);
        }
        await this.#store.saveReconciledState(incidentId, response, {
          preserveLocalMode: true,
        });
        if (conflicts.length > 0) {
          await this.#store.markConflicts(conflicts);
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

const eventBatchResponseSchema: z.ZodType<EventBatchResponse> = z.strictObject({
  acknowledgements: z.array(
    z.strictObject({
      eventId: z.uuid(),
      status: z.enum(["accepted", "duplicate", "conflict"]),
      code: z.string().nullable().optional().transform((value) => value ?? undefined),
    }),
  ),
  stateRevision: z.int().nonnegative(),
  modeRevision: z.int().nonnegative(),
  snapshotRevision: z.int().nonnegative(),
  authorityEpoch: z.int().positive(),
  lastAcknowledgedClientSequence: z.int().nonnegative().nullable(),
});

function parseEventBatchResponse(value: unknown): EventBatchResponse {
  const result = eventBatchResponseSchema.safeParse(value);
  if (!result.success) {
    throw new Error("Invalid event batch response", { cause: result.error });
  }
  return result.data;
}
