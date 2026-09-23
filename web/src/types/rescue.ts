export type RescueMode =
  | 'call_119'
  | 'on_call'
  | 'voice_guidance'
  | 'handover'

export type TimelineEvent = {
  id: string
  type: string
  timestamp: string
  note?: string
}

export type AedStatus =
  | 'idle'
  | 'assigned'
  | 'en_route'
  | 'unavailable'
  | 'reassigned'
  | 'arrived'

export type IncidentSnapshot = {
  location: string
  incidentDescription: string
  hazards: string
}

export type PatientState = {
  consciousness: 'conscious' | 'unresponsive' | 'unknown'
  breathing: 'normal' | 'abnormal' | 'not_breathing' | 'unknown'
}

/**
 * One typed scene report and what the Agent made of it. Held in memory for the
 * on-screen record; the incident timeline keeps clinical events separately.
 */
export interface SceneReportEntry {
  id: string
  text: string
  sentAt: string
  status: 'pending' | 'answered' | 'failed'
  observations?: Array<{ key: string; value: boolean | string }>
  steps?: string[]
  error?: string
}
