import { create } from 'zustand'
import { incidentRuntime, type IntegrationStatus } from '../lib/connection/incidentRuntime'
import { audioGate } from '../lib/media/audioGate'
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
  addTimelineEvent: (type: string, note?: string) => void
  setAedStatus: (status: AedStatus) => void
  recordCprStarted: () => void
  requestAed: () => void
  markAedArrived: () => void
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

const appendUnlessDuplicate = (
  timeline: TimelineEvent[],
  type: string,
  note?: string,
) => {
  const latest = timeline.at(-1)
  if (latest?.type === type && latest.note === note) return timeline
  return [...timeline, makeEvent(type, note)]
}

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
  integration: { phase: 'idle', message: '救援入口可立即使用' },
  startCall: () => {
    audioGate.silence()
    incidentRuntime.enqueueMode('on_call', 'dial_started')
    set((state) => ({ mode: 'on_call', timeline: [...state.timeline, makeEvent('撥打 119', '已切換至通話模式，Agent 語音指引靜音')] }))
  },
  endCall: () => {
    audioGate.requestResume()
    incidentRuntime.enqueueMode('voice_guidance', 'user_reports_call_ended_or_failed')
    set((state) => ({ mode: 'voice_guidance', timeline: [...state.timeline, makeEvent('119 通話結束', '已要求恢復語音指引')] }))
  },
  redial: () => {
    audioGate.silence()
    incidentRuntime.enqueueMode('on_call', 'dial_started')
    set((state) => ({ mode: 'on_call', timeline: [...state.timeline, makeEvent('重新撥打 119', 'Agent 語音指引再次靜音')] }))
  },
  beginHandover: () => {
    audioGate.silence()
    incidentRuntime.enqueueMode('handover', 'user_reports_ems_arrived')
    set((state) => ({ mode: 'handover', timeline: [...state.timeline, makeEvent('救護人員到場', '開始現場資訊交接')] }))
  },
  setMode: (mode) => set({ mode }),
  setOnline: (isOnline) => set({ isOnline }),
  setDemoNetworkOverride: (demoNetworkOverride) => set({ demoNetworkOverride }),
  setDataStale: (isDataStale) => set({ isDataStale }),
  addTimelineEvent: (type, note) => set((state) => {
    const timeline = appendUnlessDuplicate(state.timeline, type, note)
    if (timeline !== state.timeline) {
      incidentRuntime.enqueueAction(type.toLowerCase(), timeline.at(-1)?.id)
      if (type === 'PATIENT_STATUS_CHANGED') void incidentRuntime.addObservation('patient_status_changed', 'reported_change')
    }
    return timeline === state.timeline ? state : { timeline }
  }),
  setAedStatus: (aedStatus) => set({ aedStatus }),
  recordCprStarted: () => set((state) => {
    if (state.timeline.some((event) => event.type === 'CPR_STARTED')) return state
    const event = makeEvent('CPR_STARTED', '已開始胸外按壓')
    incidentRuntime.enqueueAction('cpr_started', event.id)
    return {
      timeline: [...state.timeline, event],
    }
  }),
  requestAed: () => set((state) => {
    if (state.aedStatus === 'idle') {
      const event = makeEvent('AED_ASSIGNED', '已指派現場人員尋找 AED')
      incidentRuntime.enqueueAction('aed_assigned', event.id)
      return {
        aedStatus: 'assigned',
        timeline: [...state.timeline, event],
      }
    }
    if (state.aedStatus !== 'unavailable') return state
    const event = makeEvent('AED_REASSIGNED', 'AED 無法取得，已重新指派現場人員尋找')
    incidentRuntime.enqueueAction('aed_reassigned', event.id)
    return {
      aedStatus: 'reassigned',
      timeline: [...state.timeline, event],
    }
  }),
  markAedArrived: () => set((state) => {
    if (state.aedStatus === 'arrived') return state
    const event = makeEvent('AED_ARRIVED', 'AED 已送達患者身邊')
    incidentRuntime.enqueueAction('aed_arrived', event.id)
    return {
      aedStatus: 'arrived',
      timeline: [...state.timeline, event],
    }
  }),
  resetIncident: () => {
    audioGate.silence()
    void incidentRuntime.resetIncident()
    set({ mode: 'call_119', aedStatus: 'idle', incidentSnapshot: mockIncident, patient: mockPatient, timeline: [], isDataStale: true, lastSyncedAt: new Date(Date.now() - 7 * 60 * 1000).toISOString(), demoNetworkOverride: null })
  },
  setIntegrationStatus: (integration) => set({ integration }),
}))
