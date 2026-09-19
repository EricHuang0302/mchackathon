/**
 * Firestore Security Rules tests for the incident data layer.
 *
 * Requires the Firebase Emulator Suite, which needs a Java runtime. Run with:
 *
 *     cd firebase/tests && npm install
 *     npm run test:emulator
 *
 * When FIRESTORE_EMULATOR_HOST is not set, every test is skipped with an
 * explicit reason rather than reported as passing. A skipped run proves
 * nothing about the rules.
 */

import { readFileSync } from 'node:fs';
import { after, before, describe, it } from 'node:test';

const EMULATOR = process.env.FIRESTORE_EMULATOR_HOST;
const SKIP = EMULATOR
  ? false
  : 'FIRESTORE_EMULATOR_HOST is not set: start the Firestore emulator (npm run test:emulator).';

const PROJECT_ID = 'demo-firstaid';

const OWNER_UID = 'primary-uid';
const OTHER_OWNER_UID = 'other-primary-uid';
const RUNNER_UID = 'runner-uid';
const GREETER_UID = 'greeter-uid';
const EMS_UID = 'ems-uid';
const EXPIRED_UID = 'expired-uid';
const REVOKED_UID = 'revoked-uid';
const STRANGER_UID = 'stranger-uid';

const INCIDENT = 'incident-1';
const OTHER_INCIDENT = 'incident-2';
const DEAD_INCIDENT = 'incident-expired';

const RUNNER_ID = 'runner-1';
const GREETER_ID = 'greeter-1';

let testing;
let testEnv;
let assertSucceeds;
let assertFails;

const hour = 60 * 60 * 1000;
const future = () => new Date(Date.now() + 4 * hour);
const past = () => new Date(Date.now() - 4 * hour);

async function seed(context) {
  const db = context.firestore();
  const { doc, setDoc } = await import('firebase/firestore');

  await setDoc(doc(db, `incidents/${INCIDENT}`), {
    ownerUid: OWNER_UID,
    primaryClientId: 'primary-client',
    ruleVersion: 'demo-v1',
    status: 'active',
    interactionMode: 'on_call',
    modeRevision: 2,
    stateRevision: 1,
    authorityEpoch: 0,
    expiresAt: future(),
  });
  await setDoc(doc(db, `incidents/${INCIDENT}/events/event-1`), {
    type: 'observation.confirmed',
    detail: { key: 'patient.breathing', value: false },
    serverSequence: 1,
    expiresAt: future(),
  });
  await setDoc(doc(db, `incidents/${INCIDENT}/events/event-expired`), {
    type: 'action.reported',
    detail: { action: 'synthetic' },
    serverSequence: 2,
    expiresAt: past(),
  });
  await setDoc(doc(db, `incidents/${INCIDENT}/sceneSnapshots/current`), {
    snapshotRevision: 3,
    generatedThroughRevision: 1,
    expiresAt: future(),
  });
  await setDoc(doc(db, `incidents/${INCIDENT}/handoffViews/current`), {
    mist: {},
    generatedThroughRevision: 1,
    expiresAt: future(),
  });
  for (const helperId of [RUNNER_ID, GREETER_ID]) {
    await setDoc(doc(db, `incidents/${INCIDENT}/helpers/${helperId}`), {
      role: helperId === RUNNER_ID ? 'aed_runner' : 'ambulance_greeter',
      status: 'en_route',
      assignmentRevision: 1,
      expiresAt: future(),
    });
    await setDoc(doc(db, `incidents/${INCIDENT}/helperViews/${helperId}`), {
      status: 'en_route',
      expiresAt: future(),
    });
  }
  await setDoc(doc(db, `incidents/${INCIDENT}/helpers/helper-expired`), {
    role: 'aed_runner',
    status: 'en_route',
    assignmentRevision: 1,
    expiresAt: past(),
  });

  const grants = [
    [RUNNER_UID, { scope: 'aed_runner', helperId: RUNNER_ID, expiresAt: future(), revokedAt: null }],
    [GREETER_UID, { scope: 'ambulance_greeter', helperId: GREETER_ID, expiresAt: future(), revokedAt: null }],
    [EMS_UID, { scope: 'ems_viewer', expiresAt: future(), revokedAt: null }],
    [EXPIRED_UID, { scope: 'ems_viewer', expiresAt: past(), revokedAt: null }],
    [REVOKED_UID, { scope: 'ems_viewer', expiresAt: future(), revokedAt: past() }],
  ];
  for (const [uid, data] of grants) {
    await setDoc(doc(db, `incidents/${INCIDENT}/grants/${uid}`), data);
  }

  // A second incident the same participants must not reach.
  await setDoc(doc(db, `incidents/${OTHER_INCIDENT}`), {
    ownerUid: OTHER_OWNER_UID,
    expiresAt: future(),
  });
  await setDoc(doc(db, `incidents/${OTHER_INCIDENT}/sceneSnapshots/current`), {
    snapshotRevision: 1,
    expiresAt: future(),
  });

  // An incident past its retention expiry, with deletion still pending.
  await setDoc(doc(db, `incidents/${DEAD_INCIDENT}`), {
    ownerUid: OWNER_UID,
    expiresAt: past(),
  });
  await setDoc(doc(db, `incidents/${DEAD_INCIDENT}/sceneSnapshots/current`), {
    snapshotRevision: 1,
    expiresAt: past(),
  });

  await setDoc(doc(db, 'shareInvites/invite-1'), {
    secretHash: 'synthetic-hash',
    incidentId: INCIDENT,
    scope: 'ems_viewer',
    expiresAt: future(),
  });
  await setDoc(doc(db, 'aeds/aed-1'), {
    name: 'Synthetic Demo AED',
    datasetVersion: '2026-01',
  });
}

before(async () => {
  if (SKIP) return;
  testing = await import('@firebase/rules-unit-testing');
  ({ assertSucceeds, assertFails } = testing);
  testEnv = await testing.initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      rules: readFileSync(new URL('../firestore.rules', import.meta.url), 'utf8'),
      host: EMULATOR.split(':')[0],
      port: Number(EMULATOR.split(':')[1]),
    },
  });
  await testEnv.clearFirestore();
  await testEnv.withSecurityRulesDisabled(seed);
});

after(async () => {
  if (testEnv) await testEnv.cleanup();
});

const as = (uid) =>
  uid === null
    ? testEnv.unauthenticatedContext().firestore()
    : testEnv.authenticatedContext(uid).firestore();

async function read(db, path) {
  const { doc, getDoc } = await import('firebase/firestore');
  return getDoc(doc(db, path));
}

async function write(db, path, data) {
  const { doc, setDoc } = await import('firebase/firestore');
  return setDoc(doc(db, path), data);
}

describe('deny by default', { skip: SKIP }, () => {
  it('refuses an unauthenticated read of an incident', async () => {
    await assertFails(read(as(null), `incidents/${INCIDENT}`));
  });

  it('refuses a signed-in stranger with no grant', async () => {
    const db = as(STRANGER_UID);
    await assertFails(read(db, `incidents/${INCIDENT}`));
    await assertFails(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertFails(read(db, `incidents/${INCIDENT}/handoffViews/current`));
  });

  it('refuses a collection nobody declared', async () => {
    await assertFails(read(as(OWNER_UID), 'auditLogs/entry-1'));
    await assertFails(write(as(OWNER_UID), 'auditLogs/entry-1', { note: 'x' }));
  });
});

describe('primary ownership', { skip: SKIP }, () => {
  it('lets the owner read its incident, events and projections', async () => {
    const db = as(OWNER_UID);
    await assertSucceeds(read(db, `incidents/${INCIDENT}`));
    await assertSucceeds(read(db, `incidents/${INCIDENT}/events/event-1`));
    await assertSucceeds(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertSucceeds(read(db, `incidents/${INCIDENT}/handoffViews/current`));
    await assertSucceeds(read(db, `incidents/${INCIDENT}/helpers/${RUNNER_ID}`));
  });

  it('refuses the owner of a different incident', async () => {
    const db = as(OTHER_OWNER_UID);
    await assertFails(read(db, `incidents/${INCIDENT}`));
    await assertFails(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertSucceeds(read(db, `incidents/${OTHER_INCIDENT}`));
  });
});

describe('aed runner receives retrieval information only', { skip: SKIP }, () => {
  it('reads its own helper task and view', async () => {
    const db = as(RUNNER_UID);
    await assertSucceeds(read(db, `incidents/${INCIDENT}/helpers/${RUNNER_ID}`));
    await assertSucceeds(read(db, `incidents/${INCIDENT}/helperViews/${RUNNER_ID}`));
  });

  it('is refused every clinical document', async () => {
    const db = as(RUNNER_UID);
    await assertFails(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertFails(read(db, `incidents/${INCIDENT}/handoffViews/current`));
    await assertFails(read(db, `incidents/${INCIDENT}/events/event-1`));
    await assertFails(read(db, `incidents/${INCIDENT}`));
  });

  it('cannot read another helper', async () => {
    const db = as(RUNNER_UID);
    await assertFails(read(db, `incidents/${INCIDENT}/helpers/${GREETER_ID}`));
    await assertFails(read(db, `incidents/${INCIDENT}/helperViews/${GREETER_ID}`));
  });
});

describe('ambulance greeter is snapshot-only', { skip: SKIP }, () => {
  it('reads the shared scene snapshot and its own task', async () => {
    const db = as(GREETER_UID);
    await assertSucceeds(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertSucceeds(read(db, `incidents/${INCIDENT}/helperViews/${GREETER_ID}`));
  });

  it('is refused the clinical timeline and the handoff view', async () => {
    const db = as(GREETER_UID);
    await assertFails(read(db, `incidents/${INCIDENT}/handoffViews/current`));
    await assertFails(read(db, `incidents/${INCIDENT}/events/event-1`));
    await assertFails(read(db, `incidents/${INCIDENT}/helperViews/${RUNNER_ID}`));
  });
});

describe('ems viewer is read-only', { skip: SKIP }, () => {
  it('reads the snapshot and the handoff view', async () => {
    const db = as(EMS_UID);
    await assertSucceeds(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertSucceeds(read(db, `incidents/${INCIDENT}/handoffViews/current`));
  });

  it('never reads raw events', async () => {
    await assertFails(read(as(EMS_UID), `incidents/${INCIDENT}/events/event-1`));
  });

  it('cannot write anything', async () => {
    const db = as(EMS_UID);
    await assertFails(write(db, `incidents/${INCIDENT}/events/forged`, { type: 'action.reported' }));
    await assertFails(write(db, `incidents/${INCIDENT}/sceneSnapshots/current`, { snapshotRevision: 99 }));
    await assertFails(write(db, `incidents/${INCIDENT}/handoffViews/current`, { mist: {} }));
  });
});

describe('expiry and revocation', { skip: SKIP }, () => {
  it('denies an expired grant', async () => {
    const db = as(EXPIRED_UID);
    await assertFails(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertFails(read(db, `incidents/${INCIDENT}/handoffViews/current`));
  });

  it('denies a revoked grant', async () => {
    const db = as(REVOKED_UID);
    await assertFails(read(db, `incidents/${INCIDENT}/sceneSnapshots/current`));
    await assertFails(read(db, `incidents/${INCIDENT}/handoffViews/current`));
  });

  it('denies an incident past expiry even before TTL deletion runs', async () => {
    const db = as(OWNER_UID);
    await assertFails(read(db, `incidents/${DEAD_INCIDENT}`));
    await assertFails(read(db, `incidents/${DEAD_INCIDENT}/sceneSnapshots/current`));
  });

  it('denies expired subcollection documents before TTL deletion runs', async () => {
    const db = as(OWNER_UID);
    await assertFails(read(db, `incidents/${INCIDENT}/events/event-expired`));
    await assertFails(read(db, `incidents/${INCIDENT}/helpers/helper-expired`));
  });

  it('does not expose an expired participant grant', async () => {
    await assertFails(read(as(EXPIRED_UID), `incidents/${INCIDENT}/grants/${EXPIRED_UID}`));
  });

  it('lets a participant read only its own grant', async () => {
    await assertSucceeds(read(as(EMS_UID), `incidents/${INCIDENT}/grants/${EMS_UID}`));
    await assertFails(read(as(EMS_UID), `incidents/${INCIDENT}/grants/${RUNNER_UID}`));
  });
});

describe('canonical writes are server-only', { skip: SKIP }, () => {
  it('refuses the primary session every write path', async () => {
    const db = as(OWNER_UID);
    await assertFails(write(db, `incidents/${INCIDENT}`, { status: 'closed' }));
    await assertFails(write(db, `incidents/${INCIDENT}/events/forged`, { type: 'action.reported' }));
    await assertFails(write(db, `incidents/${INCIDENT}/sceneSnapshots/current`, { snapshotRevision: 99 }));
    await assertFails(write(db, `incidents/${INCIDENT}/helpers/${RUNNER_ID}`, { status: 'delivered' }));
    await assertFails(write(db, `incidents/${INCIDENT}/grants/${EMS_UID}`, { scope: 'primary' }));
    await assertFails(write(db, `incidents/new-incident`, { ownerUid: OWNER_UID }));
  });

  it('refuses a helper writing its own task document directly', async () => {
    await assertFails(
      write(as(RUNNER_UID), `incidents/${INCIDENT}/helpers/${RUNNER_ID}`, { status: 'delivered' })
    );
  });

  it('keeps invitation secrets unreadable and unwritable', async () => {
    for (const uid of [OWNER_UID, EMS_UID, RUNNER_UID, STRANGER_UID]) {
      await assertFails(read(as(uid), 'shareInvites/invite-1'));
      await assertFails(write(as(uid), 'shareInvites/invite-2', { secretHash: 'x' }));
    }
  });

  it('serves public AED reference data read-only', async () => {
    await assertSucceeds(read(as(RUNNER_UID), 'aeds/aed-1'));
    await assertFails(read(as(null), 'aeds/aed-1'));
    await assertFails(write(as(OWNER_UID), 'aeds/aed-1', { name: 'forged' }));
  });
});
