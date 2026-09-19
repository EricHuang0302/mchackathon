export interface ClientIdentity {
  clientId: string;
  clientInstanceId: string;
  persistent: boolean;
}

const CLIENT_ID_KEY = "first-aid-copilot:client-id";
const INSTANCE_ID_KEY = "first-aid-copilot:client-instance-id";

export function getClientIdentity(
  persistentStorage: Pick<Storage, "getItem" | "setItem"> = localStorage,
  sessionStorageRef: Pick<Storage, "getItem" | "setItem"> = sessionStorage,
  randomUUID: () => string = () => crypto.randomUUID(),
): ClientIdentity {
  const client = getOrCreate(persistentStorage, CLIENT_ID_KEY, randomUUID);
  const instance = getOrCreate(
    sessionStorageRef,
    INSTANCE_ID_KEY,
    randomUUID,
  );
  return {
    clientId: client.value,
    clientInstanceId: instance.value,
    persistent: client.stored && instance.stored,
  };
}

function getOrCreate(
  storage: Pick<Storage, "getItem" | "setItem">,
  key: string,
  randomUUID: () => string,
): { value: string; stored: boolean } {
  try {
    const existing = storage.getItem(key);
    if (existing) return { value: existing, stored: true };
    const value = randomUUID();
    storage.setItem(key, value);
    return { value, stored: true };
  } catch {
    return { value: randomUUID(), stored: false };
  }
}
