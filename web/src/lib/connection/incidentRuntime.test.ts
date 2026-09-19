import { afterEach, assert, test, vi } from 'vitest'

import { BrowserMicrophone } from '../media/microphone'
import { BrowserPcmPlayback } from '../media/pcmPlayback'
import { hasSpeechActivity, IncidentRuntime, stopPlaybackOnSpeech } from './incidentRuntime'

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
