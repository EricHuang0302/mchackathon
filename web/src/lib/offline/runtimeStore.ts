import type {
  EventBatchEvent,
  EventBatchStore,
  EventConflict,
} from "../connection/eventBatchSync";
import type { InteractionMode } from "../media/mediaGate";

export interface RuntimeIncident {
  incidentId: string;
  interactionMode: InteractionMode;
  modeRevision: number;
  stateRevision?: number;
  snapshotRevision?: number;
  authorityEpoch?: number;
  ruleVersion?: string;
  guidancePaused: boolean;
  updatedAt: string;
  expiresAt?: string;
  snapshot?: unknown;
  reconciledState?: unknown;
}

export interface RuleBundleRecord {
  ruleVersion: string;
  bundle: unknown;
  savedAt: string;
  expiresAt?: string;
}

export interface CommandRecord {
  commandId: string;
  incidentId: string;
  status: "received" | "started" | "completed" | "failed" | "interrupted";
  modeRevision: number;
  authorityEpoch: number;
  updatedAt: string;
  expiresAt?: string;
}

export type EventSyncStatus = "pending" | "acked" | "conflict";

interface StoredEvent extends EventBatchEvent {
  incidentId: string;
  syncStatus: EventSyncStatus;
  conflict?: EventConflict;
  expiresAt?: string;
}

export interface SaveEventOptions {
  expiresAt?: string;
}

export interface RuntimeStoreOptions {
  databaseName?: string;
  indexedDB?: IDBFactory;
}

export type RuntimeStorageStatus = "ready" | "degraded";
type StatusListener = (status: RuntimeStorageStatus, error?: unknown) => void;

const DATABASE_VERSION = 2;
const MIN_SEQUENCE = Number.MIN_SAFE_INTEGER;
const MAX_SEQUENCE = Number.MAX_SAFE_INTEGER;

export class RuntimeStore implements EventBatchStore {
  readonly #databaseName: string;
  readonly #indexedDB: IDBFactory;
  readonly #statusListeners = new Set<StatusListener>();
  #database?: Promise<IDBDatabase>;
  #status: RuntimeStorageStatus = "ready";

  constructor(options: RuntimeStoreOptions = {}) {
    this.#databaseName = options.databaseName ?? "first-aid-copilot";
    const factory = options.indexedDB ?? globalThis.indexedDB;
    if (!factory) throw new Error("IndexedDB is unavailable");
    this.#indexedDB = factory;
  }

  async saveEvent(
    incident: RuntimeIncident,
    event: EventBatchEvent,
    options: SaveEventOptions = {},
  ): Promise<void> {
    const database = await this.#open();
    const transaction = database.transaction(
      ["incidents", "events"],
      "readwrite",
    );
    transaction.objectStore("incidents").put(incident);
    transaction.objectStore("events").put({
      ...event,
      incidentId: incident.incidentId,
      syncStatus: "pending",
      expiresAt: options.expiresAt,
    } satisfies StoredEvent);
    await this.#wait(transaction);
  }

  async saveIncident(incident: RuntimeIncident): Promise<void> {
    const database = await this.#open();
    const transaction = database.transaction("incidents", "readwrite");
    transaction.objectStore("incidents").put(incident);
    await this.#wait(transaction);
  }

  async saveSequencedEvent(
    incident: RuntimeIncident,
    event: Omit<EventBatchEvent, "clientSequence">,
    options: SaveEventOptions = {},
  ): Promise<EventBatchEvent> {
    const database = await this.#open();
    const transaction = database.transaction(
      ["incidents", "events", "counters"],
      "readwrite",
    );
    const counterStore = transaction.objectStore("counters");
    const counterId = `${incident.incidentId}:${event.clientInstanceId}`;
    const counterRequest = counterStore.get(counterId) as IDBRequest<
      { counterId: string; value: number } | undefined
    >;
    let savedEvent: EventBatchEvent | undefined;

    counterRequest.onsuccess = () => {
      const clientSequence = (counterRequest.result?.value ?? 0) + 1;
      savedEvent = { ...event, clientSequence };
      counterStore.put({ counterId, value: clientSequence });
      transaction.objectStore("incidents").put(incident);
      transaction.objectStore("events").put({
        ...savedEvent,
        incidentId: incident.incidentId,
        syncStatus: "pending",
        expiresAt: options.expiresAt,
      } satisfies StoredEvent);
    };
    await this.#wait(transaction);
    if (!savedEvent) throw new Error("Failed to allocate client sequence");
    return savedEvent;
  }

  async loadIncident(incidentId: string): Promise<RuntimeIncident | undefined> {
    const database = await this.#open();
    const transaction = database.transaction("incidents", "readonly");
    const result = await requestResult<RuntimeIncident | undefined>(
      transaction.objectStore("incidents").get(incidentId),
    );
    await this.#wait(transaction);
    return result;
  }

  async listPendingEvents(
    incidentId: string,
    limit: number,
  ): Promise<EventBatchEvent[]> {
    if (!Number.isInteger(limit) || limit <= 0) return [];
    const database = await this.#open();
    const transaction = database.transaction("events", "readonly");
    const index = transaction
      .objectStore("events")
      .index("incidentStatusSequence");
    const range = IDBKeyRange.bound(
      [incidentId, "pending", MIN_SEQUENCE],
      [incidentId, "pending", MAX_SEQUENCE],
    );
    const events: EventBatchEvent[] = [];

    await walkCursor(index.openCursor(range), (cursor) => {
      events.push(toBatchEvent(cursor.value as StoredEvent));
      return events.length < limit;
    });
    await this.#wait(transaction);
    return events;
  }

  async acknowledgeEvents(eventIds: string[]): Promise<void> {
    await this.#updateEvents(eventIds, (event) => ({
      ...event,
      syncStatus: "acked",
      conflict: undefined,
    }));
  }

  async markConflicts(conflicts: EventConflict[]): Promise<void> {
    const byId = new Map(conflicts.map((conflict) => [conflict.eventId, conflict]));
    await this.#updateEvents([...byId.keys()], (event) => ({
      ...event,
      syncStatus: "conflict",
      conflict: byId.get(event.eventId),
    }));
  }

  async saveReconciledState(
    incidentId: string,
    state: unknown,
    _options: { preserveLocalMode: true },
  ): Promise<void> {
    const database = await this.#open();
    const transaction = database.transaction("incidents", "readwrite");
    const store = transaction.objectStore("incidents");
    let missing = false;
    const request = store.get(incidentId) as IDBRequest<
      RuntimeIncident | undefined
    >;
    request.onsuccess = () => {
      if (!request.result) {
        missing = true;
        transaction.abort();
        return;
      }
      const response = asRecord(state);
      store.put({
        ...request.result,
        stateRevision: maxRevision(
          request.result.stateRevision,
          response?.stateRevision,
        ),
        snapshotRevision: maxRevision(
          request.result.snapshotRevision,
          response?.snapshotRevision,
        ),
        authorityEpoch:
          typeof response?.authorityEpoch === "number"
            ? response.authorityEpoch
            : request.result.authorityEpoch,
        reconciledState: state,
      });
    };
    try {
      await transactionDone(transaction);
    } catch (error) {
      if (missing) throw new Error(`Incident ${incidentId} was not found`);
      this.#setDegraded(error);
      throw error;
    }
  }

  async saveRuleBundle(record: RuleBundleRecord): Promise<void> {
    const database = await this.#open();
    const transaction = database.transaction("ruleBundles", "readwrite");
    transaction.objectStore("ruleBundles").put(record);
    await this.#wait(transaction);
  }

  async loadRuleBundle(
    ruleVersion: string,
  ): Promise<RuleBundleRecord | undefined> {
    const database = await this.#open();
    const transaction = database.transaction("ruleBundles", "readonly");
    const result = await requestResult<RuleBundleRecord | undefined>(
      transaction.objectStore("ruleBundles").get(ruleVersion),
    );
    await this.#wait(transaction);
    return result;
  }

  async saveCommand(record: CommandRecord): Promise<void> {
    const database = await this.#open();
    const transaction = database.transaction("commands", "readwrite");
    transaction.objectStore("commands").put(record);
    await this.#wait(transaction);
  }

  async loadCommand(commandId: string): Promise<CommandRecord | undefined> {
    const database = await this.#open();
    const transaction = database.transaction("commands", "readonly");
    const result = await requestResult<CommandRecord | undefined>(
      transaction.objectStore("commands").get(commandId),
    );
    await this.#wait(transaction);
    return result;
  }

  async purgeExpired(now = Date.now()): Promise<number> {
    const database = await this.#open();
    const storeNames = ["incidents", "events", "commands", "ruleBundles"];
    const transaction = database.transaction(storeNames, "readwrite");
    let deleted = 0;

    await Promise.all(
      storeNames.map((name) =>
        walkCursor(transaction.objectStore(name).openCursor(), (cursor) => {
          const expiresAt = (cursor.value as { expiresAt?: unknown }).expiresAt;
          if (
            typeof expiresAt === "string" &&
            Number.isFinite(Date.parse(expiresAt)) &&
            Date.parse(expiresAt) <= now
          ) {
            cursor.delete();
            deleted++;
          }
          return true;
        }),
      ),
    );
    await this.#wait(transaction);
    return deleted;
  }

  async close(): Promise<void> {
    const database = await this.#database;
    database?.close();
    this.#database = undefined;
  }

  subscribeStatus(listener: StatusListener): () => void {
    this.#statusListeners.add(listener);
    listener(this.#status);
    return () => this.#statusListeners.delete(listener);
  }

  get status(): RuntimeStorageStatus {
    return this.#status;
  }

  async #updateEvents(
    eventIds: string[],
    update: (event: StoredEvent) => StoredEvent,
  ): Promise<void> {
    if (eventIds.length === 0) return;
    const database = await this.#open();
    const transaction = database.transaction("events", "readwrite");
    const store = transaction.objectStore("events");
    for (const eventId of eventIds) {
      const request = store.get(eventId) as IDBRequest<StoredEvent | undefined>;
      request.onsuccess = () => {
        if (request.result) store.put(update(request.result));
      };
    }
    await this.#wait(transaction);
  }

  async #wait(transaction: IDBTransaction): Promise<void> {
    try {
      await transactionDone(transaction);
    } catch (error) {
      this.#setDegraded(error);
      throw error;
    }
  }

  #setDegraded(error: unknown): void {
    this.#status = "degraded";
    for (const listener of this.#statusListeners) listener(this.#status, error);
  }

  #open(): Promise<IDBDatabase> {
    this.#database ??= new Promise((resolve, reject) => {
      const request = this.#indexedDB.open(
        this.#databaseName,
        DATABASE_VERSION,
      );
      request.onupgradeneeded = () => createSchema(request.result);
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => {
          database.close();
          this.#database = undefined;
        };
        resolve(database);
      };
      request.onerror = () => {
        this.#database = undefined;
        this.#setDegraded(request.error);
        reject(request.error);
      };
      request.onblocked = () => {
        this.#database = undefined;
        const error = new Error("IndexedDB upgrade is blocked");
        this.#setDegraded(error);
        reject(error);
      };
    });
    return this.#database;
  }
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

function maxRevision(current: number | undefined, incoming: unknown): number | undefined {
  return typeof incoming === "number"
    ? Math.max(current ?? 0, incoming)
    : current;
}

function createSchema(database: IDBDatabase): void {
  if (!database.objectStoreNames.contains("incidents")) {
    database.createObjectStore("incidents", { keyPath: "incidentId" });
  }
  if (!database.objectStoreNames.contains("events")) {
    const events = database.createObjectStore("events", { keyPath: "eventId" });
    events.createIndex(
      "incidentStatusSequence",
      ["incidentId", "syncStatus", "clientSequence"],
      { unique: false },
    );
  }
  if (!database.objectStoreNames.contains("commands")) {
    database.createObjectStore("commands", { keyPath: "commandId" });
  }
  if (!database.objectStoreNames.contains("ruleBundles")) {
    database.createObjectStore("ruleBundles", { keyPath: "ruleVersion" });
  }
  if (!database.objectStoreNames.contains("counters")) {
    database.createObjectStore("counters", { keyPath: "counterId" });
  }
}

function toBatchEvent(event: StoredEvent): EventBatchEvent {
  return {
    eventId: event.eventId,
    type: event.type,
    detail: event.detail,
    clientId: event.clientId,
    clientInstanceId: event.clientInstanceId,
    clientSequence: event.clientSequence,
    clientTime: event.clientTime,
    authorityEpoch: event.authorityEpoch,
    stateRevision: event.stateRevision,
    modeRevision: event.modeRevision,
    ruleVersion: event.ruleVersion,
  };
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error("Transaction aborted"));
  });
}

function walkCursor(
  request: IDBRequest<IDBCursorWithValue | null>,
  visit: (cursor: IDBCursorWithValue) => boolean,
): Promise<void> {
  return new Promise((resolve, reject) => {
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor || !visit(cursor)) {
        resolve();
        return;
      }
      cursor.continue();
    };
  });
}
