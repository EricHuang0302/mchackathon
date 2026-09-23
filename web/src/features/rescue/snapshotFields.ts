import type { ObservationValue, SceneSnapshotResponse, SnapshotField, SnapshotSectionName } from '../../types/api'

export const OBSERVATION_KEYS = [
  'location.coordinates',
  'location.accuracyMeters',
  'location.address',
  'location.landmark',
  'location.floor',
  'location.entrance',
  'location.accessNotes',
  'circumstances.whatHappened',
  'circumstances.occurredAt',
  'circumstances.witnessed',
  'patient.responsive',
  'patient.breathing',
  'patient.breathingNormal',
  'patient.pulse',
  'patient.airway',
  'patient.bleeding',
  'patient.skinColor',
  'patient.ageRange',
  'patient.chiefComplaint',
  'patient.injuries',
  'people.patientCount',
  'people.bystanderCount',
  'people.helperSummary',
  'hazards.present',
  'hazards.traffic',
  'hazards.fire',
  'hazards.standingWater',
  'hazards.crowd',
  'hazards.description',
] as const

export type ObservationKey = (typeof OBSERVATION_KEYS)[number]

export const observationLabels: Record<ObservationKey, string> = {
  'location.coordinates': '座標',
  'location.accuracyMeters': '定位精度',
  'location.address': '地址',
  'location.landmark': '地標',
  'location.floor': '樓層',
  'location.entrance': '入口',
  'location.accessNotes': '進入方式',
  'circumstances.whatHappened': '發生經過',
  'circumstances.occurredAt': '發生時間',
  'circumstances.witnessed': '是否目擊',
  'patient.responsive': '患者有無反應',
  'patient.breathing': '患者有無呼吸',
  'patient.breathingNormal': '呼吸是否正常',
  'patient.pulse': '脈搏',
  'patient.airway': '呼吸道',
  'patient.bleeding': '出血',
  'patient.skinColor': '膚色',
  'patient.ageRange': '年齡範圍',
  'patient.chiefComplaint': '主要不適',
  'patient.injuries': '傷勢',
  'people.patientCount': '患者人數',
  'people.bystanderCount': '旁觀者人數',
  'people.helperSummary': '協助者',
  'hazards.present': '現場有無危險',
  'hazards.traffic': '車流風險',
  'hazards.fire': '火源風險',
  'hazards.standingWater': '積水風險',
  'hazards.crowd': '人群阻礙',
  'hazards.description': '危險說明',
}

export const sectionLabels: Record<SnapshotSectionName, string> = {
  location: '位置',
  circumstances: '現場狀況',
  patientCondition: '患者狀態',
  peoplePresent: '現場人員',
  hazards: '危險資訊',
}

export const getSnapshotField = (snapshot: SceneSnapshotResponse | null, key: ObservationKey): SnapshotField | undefined =>
  snapshot ? Object.values(snapshot.sections).flat().find((field) => field.key === key) : undefined

export const formatObservationValue = (value: ObservationValue): string => {
  if (value === null || value === 'unknown') return '不明'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return `${value.latitude.toFixed(5)}, ${value.longitude.toFixed(5)}`
  return String(value)
}
