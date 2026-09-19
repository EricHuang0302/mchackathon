import { afterEach, assert, beforeEach, test, vi } from 'vitest'

import { incidentRuntime } from '../lib/connection/incidentRuntime'
import { useRescueStore } from './rescueStore'

beforeEach(() => {
  useRescueStore.setState({ mode: 'call_119', dialAttempted: false, timeline: [] })
})

afterEach(() => vi.restoreAllMocks())

test('opening the telephone link records only an attempted call', () => {
  vi.spyOn(incidentRuntime, 'suspend').mockImplementation(() => undefined)
  const reportCallState = vi.spyOn(incidentRuntime, 'reportCallState').mockImplementation(() => undefined)
  const reportModeChange = vi.spyOn(incidentRuntime, 'reportModeChange').mockImplementation(() => undefined)

  useRescueStore.getState().startCall()

  assert.equal(useRescueStore.getState().mode, 'call_119')
  assert.equal(useRescueStore.getState().dialAttempted, true)
  assert.deepEqual(reportCallState.mock.calls, [['attempted']])
  assert.equal(reportModeChange.mock.calls.length, 0)
})

test('only explicit confirmation enters call mode', () => {
  const reportCallState = vi.spyOn(incidentRuntime, 'reportCallState').mockImplementation(() => undefined)
  const reportModeChange = vi.spyOn(incidentRuntime, 'reportModeChange').mockImplementation(() => undefined)

  useRescueStore.getState().confirmCallConnected()

  assert.equal(useRescueStore.getState().mode, 'on_call')
  assert.deepEqual(reportCallState.mock.calls, [['active']])
  assert.deepEqual(reportModeChange.mock.calls, [['on_call', 'dispatcher_reported_active']])
})
