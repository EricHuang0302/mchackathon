import type { ObservationRecord, ReportedAction } from '../types/api'

const latestValue = (observations: ObservationRecord[], key: string) =>
  [...observations]
    .filter((item) => item.key === key)
    .sort((left, right) => Date.parse(right.observedAt) - Date.parse(left.observedAt))[0]?.value

const booleanLabel = (value: ObservationRecord['value'] | undefined, yes: string, no: string, unknown: string) =>
  value === true ? yes : value === false ? no : unknown

export const getPatientStatusText = (observations: ObservationRecord[]) => {
  const responsive = booleanLabel(latestValue(observations, 'patient.responsive'), '有反應', '無反應', '反應不明')
  const breathing = booleanLabel(latestValue(observations, 'patient.breathing'), '有呼吸', '沒有呼吸', '呼吸不明')
  return `${responsive}、${breathing}`
}

export const getTreatmentSummary = (actions: ReportedAction[]) => {
  const active = actions.filter((action) => !action.retracted).map((action) => action.action)
  const treatments: string[] = []
  if (active.includes('cpr_started')) treatments.push('CPR 已開始')
  if (active.includes('aed_arrived')) treatments.push('AED 已抵達')
  else if (active.some((action) => ['aed_assigned', 'aed_reassigned'].includes(action))) treatments.push('已派人取得 AED')
  return treatments.length > 0 ? treatments.join('、') : '尚未記錄處置'
}
