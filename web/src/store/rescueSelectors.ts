import type { AedStatus, PatientState, TimelineEvent } from '../types/rescue'

const consciousnessLabels: Record<PatientState['consciousness'], string> = {
  conscious: '有意識',
  unresponsive: '無反應',
  unknown: '意識狀態不明',
}

const breathingLabels: Record<PatientState['breathing'], string> = {
  normal: '呼吸正常',
  abnormal: '呼吸不正常',
  not_breathing: '沒有呼吸',
  unknown: '呼吸狀態不明',
}

export const getPatientStatusText = (patient: PatientState) =>
  `${consciousnessLabels[patient.consciousness]}、${breathingLabels[patient.breathing]}`

export const getTreatmentSummary = (
  timeline: TimelineEvent[],
  aedStatus: AedStatus,
) => {
  const treatments: string[] = []

  if (timeline.some((event) => event.type === 'CPR_STARTED')) {
    treatments.push('CPR 已開始')
  }

  if (['assigned', 'en_route', 'reassigned'].includes(aedStatus)) {
    treatments.push('已派人取得 AED')
  } else if (aedStatus === 'arrived') {
    treatments.push('AED 已抵達')
  }

  return treatments.length > 0 ? treatments.join('、') : '尚未記錄處置'
}
