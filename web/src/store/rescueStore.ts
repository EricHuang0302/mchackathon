import { create } from 'zustand'
import { incidentRuntime, type IntegrationStatus } from '../lib/connection/incidentRuntime'
import type { AedStatus, IncidentSnapshot, PatientState, RescueMode, TimelineEvent } from '../types/rescue'

type RescueState = {
  mode: RescueMode
  isOnline: boolean
  demoNetworkOverride: boolean | null
  isDataStale: boolean
  lastSyncedAt: string
  aedStatus: AedStatus
  incidentSnapshot: IncidentSnapshot
  patient: PatientState
  timeline: TimelineEvent[]
  integration: IntegrationStatus
  startCall: () => void
  endCall: () => void
  redial: () => void
  beginHandover: () => void
  setMode: (mode: RescueMode) => void
  setOnline: (isOnline: boolean) => void
  setDemoNetworkOverride: (isOnline: boolean | null) => void
  setDataStale: (isDataStale: boolean) => void
  addTimelineEvent: (type: string, note?: string) => Promise<void>
  setAedStatus: (status: AedStatus) => void
  recordCprStarted: () => Promise<void>
  requestAed: () => Promise<void>
  markAedArrived: () => Promise<void>
  resetIncident: () => void
  setIntegrationStatus: (status: IntegrationStatus) => void
}

const now = Date.now()
const makeEvent = (type: string, note?: string): TimelineEvent => ({
  id: crypto.randomUUID(),
  type,
  timestamp: new Date().toISOString(),
  note,
})

const mockIncident: IncidentSnapshot = {
  location: '台北市信義區市府路 1 號，一樓大廳',
  incidentDescription: '一名成人突然倒地，目擊者立即上前查看。',
  hazards: '現場室內、地面乾燥，目前未發現明顯危險',
}

const mockPatient: PatientState = {
  consciousness: 'unresponsive',
  breathing: 'abnormal',
}

const mockTimeline: TimelineEvent[] = [
  {
    id: 'event-detected',
    type: '發現患者倒地',
    timestamp: new Date(now - 9 * 60 * 1000).toISOString(),
    note: '患者無反應，呼吸不正常',
  },
  {
    id: 'event-help',
    type: '已呼叫支援',
    timestamp: new Date(now - 8 * 60 * 1000).toISOString(),
    note: '請現場人員協助報案並尋找 AED',
  },
]

export const useRescueStore = create<RescueState>((set) => ({
  mode: 'call_119',
  isOnline: typeof navigator === 'undefined' ? true : navigator.onLine,
  demoNetworkOverride: null,
  isDataStale: true,
  lastSyncedAt: new Date(now - 7 * 60 * 1000).toISOString(),
  aedStatus: 'idle',
  incidentSnapshot: mockIncident,
  patient: mockPatient,
  timeline: mockTimeline,
  integration: { phase: 'initializing', message: '救援入口可立即使用' },
  startCall: () => {
    incidentRuntime.suspend()
    incidentRuntime.reportModeChange('on_call', 'dial_started')
    set((state) => ({ mode: 'on_call', timeline: [...state.timeline, makeEvent('撥打 119', '已切換至通話模式，Agent 語音指引靜音')] }))
  },
  endCall: () => {
    incidentRuntime.reportModeChange('voice_guidance', 'user_reports_call_ended_or_failed')
    incidentRuntime.resumeGuidance()
    set((state) => ({ mode: 'voice_guidance', timeline: [...state.timeline, makeEvent('119 通話結束', '已要求恢復語音指引')] }))
  },
  redial: () => {
    incidentRuntime.suspend()
    incidentRuntime.reportModeChange('on_call', 'dial_started')
    set((state) => ({ mode: 'on_call', timeline: [...state.timeline, makeEvent('重新撥打 119', 'Agent 語音指引再次靜音')] }))
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
  addTimelineEvent: async (type, note) => {
    const latest = useRescueStore.getState().timeline.at(-1)
    if (latest?.type === type && latest.note === note) return
    const event = makeEvent(type, note)
    await incidentRuntime.reportAction(type.toLowerCase(), event.id)
    set((state) => ({ timeline: [...state.timeline, event] }))
    if (type === 'PATIENT_STATUS_CHANGED') {
      await incidentRuntime.addObservation('patient_status_changed', 'reported_change')
    }
  },
  setAedStatus: (aedStatus) => set({ aedStatus }),
  recordCprStarted: async () => {
    const state = useRescueStore.getState()
    if (state.timeline.some((event) => event.type === 'CPR_STARTED')) return
    const event = makeEvent('CPR_STARTED', '已開始胸外按壓')
    await incidentRuntime.reportAction('cpr_started', event.id)
    set({ timeline: [...useRescueStore.getState().timeline, event] })
  },
  requestAed: async () => {
    const state = useRescueStore.getState()
    if (state.aedStatus === 'idle') {
      const event = makeEvent('AED_ASSIGNED', '已指派現場人員尋找 AED')
      await incidentRuntime.reportAction('aed_assigned', event.id)
      set({
        aedStatus: 'assigned',
        timeline: [...useRescueStore.getState().timeline, event],
      })
      return
    }
    if (state.aedStatus !== 'unavailable') return
    const event = makeEvent('AED_REASSIGNED', 'AED 無法取得，已重新指派現場人員尋找')
    await incidentRuntime.reportAction('aed_reassigned', event.id)
    set({
      aedStatus: 'reassigned',
      timeline: [...useRescueStore.getState().timeline, event],
    })
  },
  markAedArrived: async () => {
    if (useRescueStore.getState().aedStatus === 'arrived') return
    const event = makeEvent('AED_ARRIVED', 'AED 已送達患者身邊')
    await incidentRuntime.reportAction('aed_arrived', event.id)
    set({
      aedStatus: 'arrived',
      timeline: [...useRescueStore.getState().timeline, event],
    })
  },
  resetIncident: () => {
    incidentRuntime.suspend()
    void incidentRuntime.resetIncident()
    set({ mode: 'call_119', aedStatus: 'idle', incidentSnapshot: mockIncident, patient: mockPatient, timeline: [], isDataStale: true, lastSyncedAt: new Date(Date.now() - 7 * 60 * 1000).toISOString(), demoNetworkOverride: null })
  },
  setIntegrationStatus: (integration) => set((state) => ({
    integration,
    mode: integration.interactionMode ?? state.mode,
  })),
}))
