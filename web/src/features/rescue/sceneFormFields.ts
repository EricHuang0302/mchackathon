import type { SnapshotSectionName } from '../../types/api'
import type { ObservationKey } from './snapshotFields'

export type FieldControl =
  | { kind: 'text'; wide?: boolean }
  | { kind: 'tristate' }
  | { kind: 'number'; min?: number; max?: number }
  | { kind: 'datetime' }
  | { kind: 'choice'; options: ReadonlyArray<{ value: string; label: string }> }

export interface SceneFormField {
  key: ObservationKey
  section: SnapshotSectionName
  control: FieldControl
}

/** Written by the geolocation control rather than by a typed input. */
export const DEVICE_ONLY_KEYS: readonly ObservationKey[] = [
  'location.coordinates',
  'location.accuracyMeters',
]

export const SECTION_ORDER: readonly SnapshotSectionName[] = [
  'location',
  'circumstances',
  'patientCondition',
  'peoplePresent',
  'hazards',
]

// Values stay coded rather than free prose so the same observation can be
// matched by rules later. 'unknown' is a reported answer, not a missing one.
const BLEEDING = [
  { value: 'none', label: '沒有出血' },
  { value: 'minor', label: '輕微' },
  { value: 'severe', label: '嚴重' },
  { value: 'life_threatening', label: '危及生命' },
  { value: 'unknown', label: '不確定' },
] as const

const AIRWAY = [
  { value: 'clear', label: '通暢' },
  { value: 'partially_obstructed', label: '部分阻塞' },
  { value: 'obstructed', label: '完全阻塞' },
  { value: 'unknown', label: '不確定' },
] as const

const SKIN_COLOR = [
  { value: 'normal', label: '正常' },
  { value: 'pale', label: '蒼白' },
  { value: 'cyanotic', label: '發紺' },
  { value: 'flushed', label: '潮紅' },
  { value: 'unknown', label: '不確定' },
] as const

const AGE_RANGE = [
  { value: 'infant', label: '嬰幼兒' },
  { value: 'child', label: '兒童' },
  { value: 'adolescent', label: '青少年' },
  { value: 'adult', label: '成人' },
  { value: 'older_adult', label: '長者' },
  { value: 'unknown', label: '不確定' },
] as const

export const SCENE_FORM_FIELDS: readonly SceneFormField[] = [
  { key: 'location.address', section: 'location', control: { kind: 'text' } },
  { key: 'location.landmark', section: 'location', control: { kind: 'text' } },
  { key: 'location.floor', section: 'location', control: { kind: 'text' } },
  { key: 'location.entrance', section: 'location', control: { kind: 'text' } },
  { key: 'location.accessNotes', section: 'location', control: { kind: 'text', wide: true } },

  { key: 'circumstances.whatHappened', section: 'circumstances', control: { kind: 'text', wide: true } },
  { key: 'circumstances.occurredAt', section: 'circumstances', control: { kind: 'datetime' } },
  { key: 'circumstances.witnessed', section: 'circumstances', control: { kind: 'tristate' } },

  { key: 'patient.responsive', section: 'patientCondition', control: { kind: 'tristate' } },
  { key: 'patient.breathing', section: 'patientCondition', control: { kind: 'tristate' } },
  { key: 'patient.breathingNormal', section: 'patientCondition', control: { kind: 'tristate' } },
  { key: 'patient.pulse', section: 'patientCondition', control: { kind: 'tristate' } },
  { key: 'patient.airway', section: 'patientCondition', control: { kind: 'choice', options: AIRWAY } },
  { key: 'patient.bleeding', section: 'patientCondition', control: { kind: 'choice', options: BLEEDING } },
  { key: 'patient.skinColor', section: 'patientCondition', control: { kind: 'choice', options: SKIN_COLOR } },
  { key: 'patient.ageRange', section: 'patientCondition', control: { kind: 'choice', options: AGE_RANGE } },
  { key: 'patient.chiefComplaint', section: 'patientCondition', control: { kind: 'text', wide: true } },
  { key: 'patient.injuries', section: 'patientCondition', control: { kind: 'text', wide: true } },

  { key: 'people.patientCount', section: 'peoplePresent', control: { kind: 'number', min: 0, max: 99 } },
  { key: 'people.bystanderCount', section: 'peoplePresent', control: { kind: 'number', min: 0, max: 99 } },
  { key: 'people.helperSummary', section: 'peoplePresent', control: { kind: 'text', wide: true } },

  { key: 'hazards.present', section: 'hazards', control: { kind: 'tristate' } },
  { key: 'hazards.traffic', section: 'hazards', control: { kind: 'tristate' } },
  { key: 'hazards.fire', section: 'hazards', control: { kind: 'tristate' } },
  { key: 'hazards.standingWater', section: 'hazards', control: { kind: 'tristate' } },
  { key: 'hazards.crowd', section: 'hazards', control: { kind: 'tristate' } },
  { key: 'hazards.description', section: 'hazards', control: { kind: 'text', wide: true } },
]

export type ObservationValue = boolean | number | string

/** Returns undefined for a field the user left blank, which stays unobserved. */
export const parseFieldValue = (
  control: FieldControl,
  raw: string,
): ObservationValue | undefined => {
  const text = raw.trim()
  if (!text) return undefined
  switch (control.kind) {
    case 'tristate':
      return text === 'true' ? true : text === 'false' ? false : 'unknown'
    case 'number': {
      const value = Number(text)
      return Number.isFinite(value) ? value : undefined
    }
    case 'datetime': {
      const parsed = new Date(text)
      return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString()
    }
    default:
      return text
  }
}
