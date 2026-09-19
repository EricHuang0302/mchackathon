import { FileText, MicOff, PhoneCall } from 'lucide-react'
import { Timeline } from '../../components/Timeline'
import { ShareInviteControl } from '../../components/ShareInviteControl'
import { getPatientStatusText, getTreatmentSummary } from '../../store/rescueSelectors'
import { useRescueStore } from '../../store/rescueStore'

export function OnCallScreen() {
  const incidentSnapshot = useRescueStore((state) => state.incidentSnapshot)
  const patient = useRescueStore((state) => state.patient)
  const timeline = useRescueStore((state) => state.timeline)
  const aedStatus = useRescueStore((state) => state.aedStatus)
  const cprStarted = timeline.some((event) => event.type === 'CPR_STARTED')
  const endCall = useRescueStore((state) => state.endCall)
  const addTimelineEvent = useRescueStore((state) => state.addTimelineEvent)
  const recordCprStarted = useRescueStore((state) => state.recordCprStarted)
  const requestAed = useRescueStore((state) => state.requestAed)
  const markAedArrived = useRescueStore((state) => state.markAedArrived)
  const aedInProgress = ['assigned', 'en_route', 'reassigned'].includes(aedStatus)
  const canRequestAed = aedStatus === 'idle' || aedStatus === 'unavailable'
  const aedButtonLabel = aedStatus === 'idle'
    ? '派人拿 AED'
    : aedStatus === 'unavailable'
      ? '重新指派 AED'
      : aedStatus === 'arrived'
        ? 'AED 已抵達'
        : 'AED 取件中'
  const patientStatus = getPatientStatusText(patient)
  const treatmentSummary = getTreatmentSummary(timeline, aedStatus)

  return (
    <section className="screen" aria-labelledby="on-call-title">
      <div className="call-status">
        <span className="call-status-icon"><PhoneCall size={23} /></span>
        <div><strong id="on-call-title">119 派遣員通話中</strong><span>請優先聽從派遣員指示</span></div>
      </div>

      <div className="muted-notice" role="status">
        <MicOff size={22} /><span>Agent 語音指引目前靜音，避免干擾 119 通話。</span>
      </div>

      <div className="card">
        <h2 className="card-title"><FileText size={23} />報案小抄</h2>
        <dl className="report-grid">
          <div className="report-item"><dt>位置</dt><dd>{incidentSnapshot.location}</dd></div>
          <div className="report-item"><dt>發生經過</dt><dd>{incidentSnapshot.incidentDescription}</dd></div>
          <div className="report-item"><dt>患者狀態</dt><dd>{patientStatus}</dd></div>
          <div className="report-item"><dt>已做處置</dt><dd>{treatmentSummary}</dd></div>
        </dl>
      </div>

      <div className="card">
        <h2 className="card-title">快速記錄</h2>
        <div className="quick-grid">
          <button className="quick-action" type="button" onClick={recordCprStarted} disabled={cprStarted}>
            {cprStarted ? 'CPR 進行中' : '開始 CPR'}
          </button>
          <button className="quick-action" type="button" onClick={requestAed} disabled={!canRequestAed}>
            {aedButtonLabel}
          </button>
          <button className="quick-action" type="button" onClick={markAedArrived} disabled={aedStatus === 'arrived'}>
            {aedStatus === 'arrived' ? 'AED 已抵達' : 'AED 抵達'}
          </button>
          <button
            className="quick-action"
            type="button"
            onClick={() => addTimelineEvent('PATIENT_STATUS_CHANGED', '患者狀態有新的變化，待補充描述')}
          >
            患者狀態改變
          </button>
        </div>
        {aedInProgress && <p className="quick-hint">AED 已有人負責，取件期間不會重複記錄。</p>}
      </div>

      <div className="card">
        <h2 className="card-title">最近事件</h2>
        <Timeline limit={4} compact />
      </div>

      <div className="card">
        <h2 className="card-title">協助者授權</h2>
        <ShareInviteControl scope="aed_runner" label="建立 AED 取件者連結" />
      </div>

      <div className="sticky-action">
        <button className="primary-action" type="button" onClick={endCall}>通話已結束，恢復語音指引</button>
      </div>
    </section>
  )
}
