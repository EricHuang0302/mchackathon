import { assert, test } from 'vitest'

import type { CameraObservationProposal } from '../../types/api'
import { buildCameraConfirmationObservations, type CameraReviewValues } from './cameraObservations'

const proposals = (): CameraObservationProposal[] => {
  const observedAt = '2026-09-20T00:00:00.000Z'
  return [
    ['hazards.traffic', true],
    ['hazards.fire', false],
    ['hazards.standingWater', 'unknown'],
    ['hazards.crowd', false],
    ['patient.bleeding', 'minor'],
  ].map(([key, value], index) => ({
    observationId: `00000000-0000-4000-8000-00000000000${index}`,
    key,
    value,
    source: 'camera_proposal',
    observedAt,
    confirmation: 'proposed',
    evidenceEventIds: [],
    confidence: 'medium',
  })) as CameraObservationProposal[]
}

test('preserves camera proposals and appends evidence-linked human confirmations', () => {
  const input = proposals()
  const values = Object.fromEntries(
    input.map((proposal) => [proposal.key, proposal.value]),
  ) as CameraReviewValues
  let id = 10
  const rows = buildCameraConfirmationObservations(
    input,
    values,
    '2026-09-20T00:01:00.000Z',
    () => `00000000-0000-4000-8000-0000000000${id++}`,
  )

  assert.equal(rows.length, 11)
  assert.equal(rows.filter((row) => row.source === 'camera_proposal').length, 5)
  const traffic = rows.find((row) => row.key === 'hazards.traffic' && row.source === 'manual_report')
  assert.equal(traffic?.value, true)
  assert.deepEqual(traffic?.evidenceEventIds, [input[0]!.observationId])
  assert.equal(rows.find((row) => row.key === 'hazards.present')?.value, true)
})

test('keeps aggregate hazard unknown when no risk is present but one view is unknown', () => {
  const input = proposals()
  const values = Object.fromEntries(
    input.map((proposal) => [proposal.key, proposal.key === 'hazards.traffic' ? false : proposal.value]),
  ) as CameraReviewValues
  const rows = buildCameraConfirmationObservations(input, values, undefined, () => crypto.randomUUID())

  assert.equal(rows.find((row) => row.key === 'hazards.present')?.value, 'unknown')
})
