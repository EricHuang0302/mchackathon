import { randomUUID } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const origin = process.env.DEMO_ORIGIN ?? process.env.PUBLIC_ORIGIN ?? 'http://127.0.0.1:8080'
const statePath = join(tmpdir(), 'mchackathon-demo-seed.json')
const reset = process.argv.includes('--reset')

async function request(path, init = {}, token) {
  const response = await fetch(`${origin}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(token ? { authorization: `Bearer ${token}` } : {}), ...init.headers },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(`${response.status} ${body?.error?.code ?? response.statusText}: ${body?.error?.message ?? ''}`)
  return body
}

if (reset) {
  try {
    const previous = JSON.parse(await readFile(statePath, 'utf8'))
    await request(`/v1/incidents/${previous.incidentId}`, {
      method: 'PATCH', body: JSON.stringify({ status: 'closed', expectedStateRevision: previous.stateRevision ?? 0 }),
    }, previous.sessionToken)
  } catch {
    // Reset is best effort when the previous local seed has expired or changed.
  }
}

const session = await request('/v1/sessions', { method: 'POST' })
const incidentId = randomUUID()
const primaryClientId = randomUUID()
const incident = await request('/v1/incidents', {
  method: 'POST', body: JSON.stringify({ incidentId, primaryClientId, ruleVersion: 'demo-v1' }),
}, session.sessionToken)

const observedAt = new Date().toISOString()
const values = [
  ['location.coordinates', { latitude: 25.033, longitude: 121.565 }],
  ['location.address', '台北市信義區市府路 1 號'],
  ['location.landmark', '一樓大廳'],
  ['circumstances.whatHappened', '一名成人突然倒地'],
  ['patient.responsive', false],
  ['patient.breathing', false],
  ['hazards.present', false],
]
await request(`/v1/incidents/${incidentId}/scene-observations`, {
  method: 'POST',
  body: JSON.stringify({
    expectedSnapshotRevision: 0,
    idempotencyKey: randomUUID(),
    observations: values.map(([key, value]) => ({
      observationId: randomUUID(), key, value, source: 'manual_report', observedAt,
      confirmation: 'user_confirmed', evidenceEventIds: [],
    })),
  }),
}, session.sessionToken)

const seeded = { incidentId, stateRevision: incident.stateRevision, sessionToken: session.sessionToken, origin }
await writeFile(statePath, JSON.stringify(seeded), { mode: 0o600 })
console.log(JSON.stringify({ incidentId, snapshotRevision: 1, origin, statePath }, null, 2))
