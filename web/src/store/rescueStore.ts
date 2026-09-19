import { create } from 'zustand'
import { incidentRuntime, type IntegrationStatus } from '../lib/connection/incidentRuntime'
import type { ObservationInput, SceneSnapshotResponse } from '../types/api'
import type { AedStatus, RescueMode, TimelineEvent } from '../types/rescue'

type RescueState = {
  mode: RescueMode
  isOnline: boolean
  demoNetworkOverride: boolean | null
  isDataStale: boolean
  lastSyncedAt: string | null
  aedStatus: AedStatus
  snapshot: SceneSnapshotResponse | null
  timeline: TimelineEvent[]
  integration: IntegrationStatus
  dialAttempted: boolean
  startCall: () => void
  confirmCallConnected: () => void
  reportCallFailed: () => void
  endCall: () => void
  redial: () => void
  beginHandover: () => void
  setMode: (mode: RescueMode) => void
  setOnline: (isOnline: boolean) => void
  setDemoNetworkOverride: (isOnline: boolean | null) => void
  setDataStale: (isDataStale: boolean) => void
  refreshSnapshot: () => Promise<void>
  saveSceneObservations: (observations: ObservationInput[]) => Promise<void>
  addTimelineEvent: (type: string, note?: string) => Promise<void>
  setAedStatus: (status: AedStatus) => void
  recordCprStarted: () => Promise<void>
  requestAed: () => Promise<void>
  markAedArrived: () => Promise<void>
  resetIncident: () => void
  setIntegrationStatus: (status: IntegrationStatus) => void
}

const makeEvent = (type: string, note?: string): TimelineEvent => ({
  id: crypto.randomUUID(), type, timestamp: new Date().toISOString(), note,
})

const updateSnapshot = (snapshot: SceneSnapshotResponse) => ({
  snapshot,
  lastSyncedAt: snapshot.updatedAt ?? new Date().toISOString(),
  isDataStale: Object.values(snapshot.sections).flat().some((field) => field.freshness === 'stale'),
})

export const useRescueStore = create<RescueState>((set) => ({
  mode: 'call_119',
  isOnline: typeof navigator === 'undefined' ? true : navigator.onLine,
  demoNetworkOverride: null,
  isDataStale: true,
  lastSyncedAt: null,
  aedStatus: 'idle',
  snapshot: null,
  timeline: [],
  integration: { phase: 'initializing', message: '救援入口可立即使用' },
  dialAttempted: false,
  startCall: () => {
    incidentRuntime.suspend()
    incidentRuntime.reportCallState('attempted')
    set((state) => ({ dialAttempted: true, timeline: [...state.timeline, makeEvent('嘗試撥號', '已啟動電話連結；尚未確認接通')] }))
  },
  confirmCallConnected: () => {
    incidentRuntime.reportCallState('active')
    incidentRuntime.reportModeChange('on_call', 'dispatcher_reported_active')
    set((state) => ({ mode: 'on_call', dialAttempted: false, timeline: [...state.timeline, makeEvent('通話已接通', '由使用者確認已接通派遣員')] }))
  },
  reportCallFailed: () => {
    const mode = useRescueStore.getState().mode
    incidentRuntime.reportCallState('failed')
    if (mode === 'call_119') {
      incidentRuntime.reportModeChange('voice_guidance', 'user_reports_call_failed')
    } else if (mode === 'on_call') {
      incidentRuntime.reportModeChange('voice_guidance', 'user_reports_call_ended_or_failed')
    }
    incidentRuntime.resumeGuidance()
    set((state) => ({ mode: 'voice_guidance', dialAttempted: false, timeline: [...state.timeline, makeEvent('無法接通', '由使用者回報，已切換至語音指引')] }))
  },
  endCall: () => {
    incidentRuntime.reportCallState('ended')
    incidentRuntime.reportModeChange('voice_guidance', 'user_reports_call_ended_or_failed')
    incidentRuntime.resumeGuidance()
    set((state) => ({ mode: 'voice_guidance', dialAttempted: false, timeline: [...state.timeline, makeEvent('119 通話結束', '已要求恢復語音指引')] }))
  },
  redial: () => {
    incidentRuntime.suspend()
    incidentRuntime.reportCallState('attempted')
    set((state) => ({ dialAttempted: true, timeline: [...state.timeline, makeEvent('重新嘗試撥號', '已啟動電話連結；尚未確認接通')] }))
  },
  beginHandover: () => {
    incidentRuntime.suspend()
    incidentRuntime.reportModeChange('handover', 'user_reports_ems_arrived')
    set((state) => ({ mode: 'handover', timeline: [...state.timeline, makeEvent('救護人員到場', '開始現場資訊交接')] }))
  },
  setMode: (mode) => set({ mode }),
  setOnline: (isOnline) => set({ isOnline }),
  setDemoNetworkOverride: (demoNetworkOverride) => set({ demoNetworkOverride }),
  setDataStale: (isDataStale) => set({ isDataStale }),
  refreshSnapshot: async () => {
    const snapshot = await incidentRuntime.getSnapshot()
    set(updateSnapshot(snapshot))
  },
  saveSceneObservations: async (observations) => {
    const snapshot = await incidentRuntime.addObservations(observations)
    set(updateSnapshot(snapshot))
  },
  addTimelineEvent: async (type, note) => {
    const latest = useRescueStore.getState().timeline.at(-1)
    if (latest?.type === type && latest.note === note) return
    const event = makeEvent(type, note)
    await incidentRuntime.reportAction(type.toLowerCase(), event.id)
    set((state) => ({ timeline: [...state.timeline, event] }))
    await useRescueStore.getState().refreshSnapshot()
  },
  setAedStatus: (aedStatus) => set({ aedStatus }),
  recordCprStarted: async () => {
    const state = useRescueStore.getState()
    if (state.timeline.some((event) => event.type === 'CPR_STARTED')) return
    const event = makeEvent('CPR_STARTED', '已開始胸外按壓')
    await incidentRuntime.reportAction('cpr_started', event.id)
    set({ timeline: [...useRescueStore.getState().timeline, event] })
    await useRescueStore.getState().refreshSnapshot()
  },
  requestAed: async () => {
    const state = useRescueStore.getState()
    const action = state.aedStatus === 'idle' ? 'aed_assigned' : state.aedStatus === 'unavailable' ? 'aed_reassigned' : null
    if (!action) return
    const event = makeEvent(action.toUpperCase(), action === 'aed_assigned' ? '已指派現場人員尋找 AED' : 'AED 無法取得，已重新指派')
    await incidentRuntime.reportAction(action, event.id)
    set({ aedStatus: action === 'aed_assigned' ? 'assigned' : 'reassigned', timeline: [...useRescueStore.getState().timeline, event] })
    await useRescueStore.getState().refreshSnapshot()
  },
  markAedArrived: async () => {
    if (useRescueStore.getState().aedStatus === 'arrived') return
    const event = makeEvent('AED_ARRIVED', 'AED 已送達患者身邊')
    await incidentRuntime.reportAction('aed_arrived', event.id)
    set({ aedStatus: 'arrived', timeline: [...useRescueStore.getState().timeline, event] })
    await useRescueStore.getState().refreshSnapshot()
  },
  resetIncident: () => {
    incidentRuntime.suspend()
    void incidentRuntime.resetIncident().then(() => incidentRuntime.initialize()).then(() => useRescueStore.getState().refreshSnapshot())
    set({ mode: 'call_119', dialAttempted: false, aedStatus: 'idle', snapshot: null, timeline: [], isDataStale: true, lastSyncedAt: null, demoNetworkOverride: null })
  },
  setIntegrationStatus: (integration) => set((state) => ({ integration, mode: integration.interactionMode ?? state.mode })),
}))
