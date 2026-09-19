import type { CameraObservationProposal, ObservationInput } from '../../types/api'

export type CameraReviewValues = Record<
  CameraObservationProposal['key'],
  CameraObservationProposal['value']
>

export function buildCameraConfirmationObservations(
  proposals: CameraObservationProposal[],
  values: CameraReviewValues,
  confirmedAt = new Date().toISOString(),
  createId: () => string = () => crypto.randomUUID(),
): ObservationInput[] {
  const proposalRows: ObservationInput[] = proposals.map(({
    confidence: _confidence,
    ...proposal
  }) => proposal)
  const confirmedRows: ObservationInput[] = proposals.map((proposal) => ({
    observationId: createId(),
    key: proposal.key,
    value: values[proposal.key],
    source: 'manual_report',
    observedAt: confirmedAt,
    confirmation: 'user_confirmed',
    evidenceEventIds: [proposal.observationId],
  }))
  const hazardProposals = proposals.filter((proposal) => proposal.key.startsWith('hazards.'))
  const hazardValues = hazardProposals.map((proposal) => values[proposal.key])
  let hazardsPresent: boolean | 'unknown' = 'unknown'
  if (hazardValues.length === 4) {
    if (hazardValues.some((value) => value === true)) hazardsPresent = true
    else if (hazardValues.every((value) => value === false)) hazardsPresent = false
  }
  confirmedRows.push({
    observationId: createId(),
    key: 'hazards.present',
    value: hazardsPresent,
    source: 'manual_report',
    observedAt: confirmedAt,
    confirmation: 'user_confirmed',
    evidenceEventIds: hazardProposals.map((proposal) => proposal.observationId),
  })
  return [...proposalRows, ...confirmedRows]
}
