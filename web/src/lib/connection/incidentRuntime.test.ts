import { afterEach, assert, test, vi } from 'vitest'

import { BrowserMicrophone } from '../media/microphone'
import { BrowserPcmPlayback } from '../media/pcmPlayback'
import { hasSpeechActivity, IncidentRuntime, observationProposalFromLive, stopPlaybackOnSpeech } from './incidentRuntime'
import type { LiveObservationProposal, RuleEvaluationResponse, SceneSnapshotResponse } from '../../types/api'

afterEach(() => vi.restoreAllMocks())

test('suspend stops queued playback and microphone upload through MediaGate', () => {
  const stopPlayback = vi.spyOn(BrowserPcmPlayback.prototype, 'stopAll')
  const stopMicrophone = vi.spyOn(BrowserMicrophone.prototype, 'stop')

  new IncidentRuntime().suspend()

  assert.equal(stopPlayback.mock.calls.length, 1)
  assert.equal(stopMicrophone.mock.calls.length, 1)
})

test('speech activity detection distinguishes voice-level samples from silence', () => {
  assert.equal(hasSpeechActivity(new Float32Array([0.03, -0.03, 0.04])), true)
  assert.equal(hasSpeechActivity(new Float32Array([0.001, -0.001, 0.002])), false)
})

test('barge-in clears queued playback when the user speaks', () => {
  const stopAll = vi.fn()

  assert.equal(stopPlaybackOnSpeech(new Float32Array([0.03, -0.03]), stopAll), true)
  assert.equal(stopAll.mock.calls.length, 1)
})

test('accepts only typed allowlisted Live observation proposals', () => {
  const proposal = {
    observationId: crypto.randomUUID(), key: 'responsive', value: false,
    source: 'model_proposal', observedAt: new Date().toISOString(),
    confirmation: 'proposed', evidenceEventIds: [],
  } satisfies LiveObservationProposal

  assert.deepEqual(observationProposalFromLive({ type: 'observation.proposed', messageId: proposal.observationId, observation: proposal }), proposal)
  assert.equal(observationProposalFromLive({ type: 'observation.proposed', messageId: 'different', observation: proposal }), null)
  assert.equal(observationProposalFromLive({ type: 'observation.proposed', messageId: proposal.observationId, observation: { ...proposal, key: 'treatment' } }), null)
  assert.equal(observationProposalFromLive({ type: 'observation.proposed', messageId: proposal.observationId, observation: { ...proposal, source: 'user_report' } }), null)
})

test('human confirmation writes a confirmed user report before evaluating rules', async () => {
  const runtime = new IncidentRuntime()
  const proposal = {
    observationId: crypto.randomUUID(), key: 'breathing_normal', value: true,
    source: 'model_proposal', observedAt: new Date().toISOString(),
    confirmation: 'proposed', evidenceEventIds: [],
  } satisfies LiveObservationProposal
  const snapshot = { observations: [] } as unknown as SceneSnapshotResponse
  const evaluation = { decision: {} } as unknown as RuleEvaluationResponse
  const save = vi.spyOn(runtime, 'addObservations').mockResolvedValue(snapshot)
  const evaluate = vi.spyOn(runtime, 'evaluateRules').mockResolvedValue(evaluation)

  assert.deepEqual(await runtime.confirmObservation(proposal, false), { snapshot, evaluation })
  assert.equal(save.mock.calls[0]![0][0]!.source, 'manual_report')
  assert.equal(save.mock.calls[0]![0][0]!.confirmation, 'user_confirmed')
  assert.equal(save.mock.calls[0]![0][0]!.value, false)
  assert.equal(evaluate.mock.calls[0]![0]![0]!.source, 'button')
  assert.equal(evaluate.mock.calls[0]![0]![0]!.confirmation, 'confirmed')
})
