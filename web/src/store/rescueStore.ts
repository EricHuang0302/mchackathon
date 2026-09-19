import { create } from 'zustand'
import { incidentRuntime, type IntegrationStatus } from '../lib/connection/incidentRuntime'
import { userMessageForApiError } from '../lib/connection/apiClient'
import type { CameraObservationProposal, LiveObservationProposal, ObservationInput, RuleEvaluationResponse, SceneImageAnalysisResponse, SceneSnapshotResponse } from '../types/api'
import type { CameraFrame } from '../lib/media/camera'
import type { AedStatus, RescueMode, TimelineEvent } from '../types/rescue'

type RescueState = {
  mode: RescueMode
  isOnline: boolean
  demoNetworkOverride: boolean | null
  isDataStale: boolean
  lastSyncedAt: string | null
  aedStatus: AedStatus
  aedAssignmentRevision: number | null
  aedHelperStatus: string | null
  aedMessage: string | null
  snapshot: SceneSnapshotResponse | null
  timeline: TimelineEvent[]
  integration: IntegrationStatus
  dialAttempted: boolean
  observationProposal: LiveObservationProposal | null
  lastObservationProposal: LiveObservationProposal | null
  guidance: RuleEvaluationResponse | null
  guidanceError: string | null
  voiceStopped: boolean
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
  analyzeSceneImage: (frame: CameraFrame) => Promise<SceneImageAnalysisResponse>
  confirmCameraProposals: (proposals: CameraObservationProposal[], values: Record<CameraObservationProposal['key'], CameraObservationProposal['value']>) => Promise<void>
  setObservationProposal: (proposal: LiveObservationProposal) => void
  confirmObservation: (value: boolean | 'unknown') => Promise<void>
  evaluateGuidance: () => Promise<void>
  repeatGuidance: () => Promise<void>
  stopGuidance: () => void
  correctObservation: () => void
  addTimelineEvent: (type: string, note?: string) => Promise<void>
  setAedStatus: (status: AedStatus) => void
  recordCprStarted: () => Promise<void>
  requestAed: () => Promise<void>
  refreshAedAssignment: () => Promise<void>
  markAedArrived: () => Promise<void>
  resetIncident: () => void
  setIntegrationStatus: (status: IntegrationStatus) => void
}

// The rule decision declares whether this step may be spoken. Never read out
// anything the interpreter did not put on the audio channel, and never while
// the user has stopped the voice.
const speakGuidance = (guidance: RuleEvaluationResponse | null | undefined) => {
  if (useRescueStore.getState().voiceStopped) return
  const text = guidance?.decision.instruction?.text
  if (text && guidance?.decision.outputChannels.includes('audio')) incidentRuntime.speakTemplate(text)
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
  aedAssignmentRevision: null,
  aedHelperStatus: null,
  aedMessage: null,
  snapshot: null,
  timeline: [],
  integration: { phase: 'initializing', message: '救援入口可立即使用' },
  dialAttempted: false,
  observationProposal: null,
  lastObservationProposal: null,
  guidance: null,
  guidanceError: null,
  voiceStopped: true,
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
    set((state) => ({ mode: 'voice_guidance', voiceStopped: false, dialAttempted: false, timeline: [...state.timeline, makeEvent('無法接通', '由使用者回報，已切換至語音指引')] }))
  },
  endCall: () => {
    incidentRuntime.reportCallState('ended')
    incidentRuntime.reportModeChange('voice_guidance', 'user_reports_call_ended_or_failed')
    incidentRuntime.resumeGuidance()
    set((state) => ({ mode: 'voice_guidance', voiceStopped: false, dialAttempted: false, timeline: [...state.timeline, makeEvent('119 通話結束', '已要求恢復語音指引')] }))
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
  analyzeSceneImage: (frame) => incidentRuntime.analyzeSceneImage(frame),
  confirmCameraProposals: async (proposals, values) => {
    const snapshot = await incidentRuntime.confirmCameraProposals(proposals, values)
    set(updateSnapshot(snapshot))
  },
  setObservationProposal: (observationProposal) => set({ observationProposal, lastObservationProposal: observationProposal }),
  confirmObservation: async (value) => {
    const proposal = useRescueStore.getState().observationProposal
    if (!proposal) return
    const { snapshot, evaluation } = await incidentRuntime.confirmObservation(proposal, value)
    set({ ...updateSnapshot(snapshot), guidance: evaluation, guidanceError: null, observationProposal: null })
    speakGuidance(evaluation)
  },
  evaluateGuidance: async () => {
    try {
      const guidance = await incidentRuntime.evaluateRules()
      set({ guidance, guidanceError: null })
      speakGuidance(guidance)
    } catch {
      set({ guidanceError: '目前無法取得規則模板，請以 119 派遣員指示為準。' })
    }
  },
  repeatGuidance: async () => {
    try {
      const guidance = await incidentRuntime.evaluateRules([], { type: 'resume' })
      set({ guidance, guidanceError: null })
      speakGuidance(guidance)
    } catch {
      set({ guidanceError: '無法重新載入指引，請以 119 派遣員指示為準。' })
    }
  },
  stopGuidance: () => {
    incidentRuntime.stopSpeech()
    incidentRuntime.suspend()
    set({ voiceStopped: true })
  },
  correctObservation: () => set((state) => ({ observationProposal: state.lastObservationProposal })),
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
    if (state.aedStatus !== 'idle' && state.aedStatus !== 'unavailable') return
    set({ aedMessage: null })
    try {
      const result = await incidentRuntime.dispatchAed()
      const assigned = result.outcome === 'assigned' || result.outcome === 'reassigned'
      const nextStatus: AedStatus = result.outcome === 'no_candidate'
        ? 'unavailable'
        : result.outcome === 'reassigned' ? 'reassigned' : assigned ? 'assigned' : state.aedStatus
      const note = result.outcome === 'no_candidate'
        ? '目前沒有可指派的 AED'
        : result.outcome === 'reassigned' ? '已改派其他 AED' : '已建立 AED 指派'
      set((current) => ({
        aedStatus: nextStatus,
        aedAssignmentRevision: result.assignmentRevision,
        aedMessage: note,
        timeline: assigned || result.outcome === 'no_candidate'
          ? [...current.timeline, makeEvent(`AED_${result.outcome.toUpperCase()}`, note)]
          : current.timeline,
      }))
    } catch (reason) {
      set({ aedMessage: reason instanceof Error && !(reason as { code?: string }).code ? reason.message : userMessageForApiError(reason) })
    }
  },
  refreshAedAssignment: async () => {
    try {
      const assignment = await incidentRuntime.getAedAssignment()
      if (!assignment) return
      const helperStatus = assignment.helperStatus
      const aedStatus: AedStatus = helperStatus === 'delivered'
        ? 'arrived'
        : helperStatus === 'unavailable' ? 'unavailable'
          : helperStatus === 'en_route' || helperStatus === 'arrived' || helperStatus === 'obtained'
            ? 'en_route'
            : assignment.status === 'no_candidate' ? 'unavailable' : 'assigned'
      set({
        aedStatus,
        aedAssignmentRevision: assignment.assignmentRevision,
        aedHelperStatus: helperStatus,
      })
    } catch (reason) {
      set({ aedMessage: userMessageForApiError(reason) })
    }
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
    set({ mode: 'call_119', dialAttempted: false, aedStatus: 'idle', aedAssignmentRevision: null, aedHelperStatus: null, aedMessage: null, snapshot: null, timeline: [], isDataStale: true, lastSyncedAt: null, demoNetworkOverride: null, observationProposal: null, lastObservationProposal: null, guidance: null, guidanceError: null, voiceStopped: true })
  },
  setIntegrationStatus: (integration) => set((state) => ({ integration, mode: integration.interactionMode ?? state.mode })),
}))
