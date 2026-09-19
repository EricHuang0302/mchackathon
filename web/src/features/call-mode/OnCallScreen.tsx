import { useEffect } from 'react'
import { Camera, FileText, MicOff, PhoneCall } from 'lucide-react'
import { Timeline } from '../../components/Timeline'
import { CprVisualMetronome } from '../../components/CprVisualMetronome'
import { ShareInviteControl } from '../../components/ShareInviteControl'
import { CanonicalSnapshotCard } from '../rescue/CanonicalSnapshotCard'
import { SceneObservationForm } from '../rescue/SceneObservationForm'
import { SceneCameraAnalysis } from '../rescue/SceneCameraAnalysis'
import { formatObservationValue, getSnapshotField } from '../rescue/snapshotFields'
import { getPatientStatusText, getTreatmentSummary } from '../../store/rescueSelectors'
import { useRescueStore } from '../../store/rescueStore'

export function OnCallScreen() {
  const snapshot = useRescueStore((state) => state.snapshot)
  const timeline = useRescueStore((state) => state.timeline)
  const aedStatus = useRescueStore((state) => state.aedStatus)
  const aedAssignmentRevision = useRescueStore((state) => state.aedAssignmentRevision)
  const aedHelperStatus = useRescueStore((state) => state.aedHelperStatus)
  const aedMessage = useRescueStore((state) => state.aedMessage)
  const refreshAedAssignment = useRescueStore((state) => state.refreshAedAssignment)
  const cprStarted = timeline.some((event) => event.type === 'CPR_STARTED')
  const endCall = useRescueStore((state) => state.endCall)
  const reportCallFailed = useRescueStore((state) => state.reportCallFailed)
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
  const patientStatus = getPatientStatusText(snapshot?.observations ?? [])
  const treatmentSummary = getTreatmentSummary(snapshot?.actionsPerformed ?? [])
  const address = formatObservationValue(getSnapshotField(snapshot, 'location.address')?.value ?? null)
  const landmark = formatObservationValue(getSnapshotField(snapshot, 'location.landmark')?.value ?? null)
  const incidentDescription = formatObservationValue(getSnapshotField(snapshot, 'circumstances.whatHappened')?.value ?? null)

  useEffect(() => {
    if (aedAssignmentRevision == null || aedStatus === 'arrived' || aedStatus === 'unavailable') return
    void refreshAedAssignment()
    const timer = window.setInterval(() => void refreshAedAssignment(), 10_000)
    return () => window.clearInterval(timer)
  }, [aedAssignmentRevision, aedStatus, refreshAedAssignment])

  return (
    <section className="screen" aria-labelledby="on-call-title">
      <div className="call-status">
        <span className="call-status-icon"><PhoneCall size={23} /></span>
        <div><strong id="on-call-title">119 派遣員通話中</strong><span>請優先聽從派遣員指示 · 快照 r{snapshot?.snapshotRevision ?? 0}</span></div>
      </div>

      <div className="muted-notice" role="status">
        <MicOff size={22} /><span>Agent 語音指引目前靜音，避免干擾 119 通話。</span>
      </div>

      <div className="card">
        <h2 className="card-title"><FileText size={23} />報案小抄</h2>
        <dl className="report-grid">
          <div className="report-item"><dt>位置</dt><dd>{address}{landmark !== '不明' ? `，${landmark}` : ''}</dd></div>
          <div className="report-item"><dt>發生經過</dt><dd>{incidentDescription}</dd></div>
          <div className="report-item"><dt>患者狀態</dt><dd>{patientStatus}</dd></div>
          <div className="report-item"><dt>已做處置</dt><dd>{treatmentSummary}</dd></div>
        </dl>
      </div>

      {cprStarted && <CprVisualMetronome />}

      <div className="card">
        <h2 className="card-title"><Camera size={23} />現場影像</h2>
        <SceneCameraAnalysis />
      </div>

      <div className="card">
        <h2 className="card-title">現場資料確認</h2>
        <SceneObservationForm />
      </div>

      <div className="card">
        <h2 className="card-title">Canonical snapshot · r{snapshot?.snapshotRevision ?? 0}</h2>
        <CanonicalSnapshotCard snapshot={snapshot} />
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
        {aedAssignmentRevision != null && (
          <p className="quick-hint">指派 r{aedAssignmentRevision} · 協助者狀態：{aedHelperStatus ?? '尚未回報'}</p>
        )}
        {aedMessage && <p className="quick-hint" role="status">{aedMessage}</p>}
      </div>

      <div className="card">
        <h2 className="card-title">最近事件</h2>
        <Timeline limit={4} compact />
      </div>

      <div className="card">
        <h2 className="card-title">協助者授權</h2>
        <ShareInviteControl scope="aed_runner" label="建立 AED 取件者連結" />
        <div className="share-control-divider" />
        <ShareInviteControl scope="ambulance_greeter" label="建立救護車接應者連結" />
      </div>

      <div className="sticky-action">
        <div className="action-stack">
          <button className="primary-action" type="button" onClick={endCall}>通話已結束，恢復語音指引</button>
          <button className="secondary-action" type="button" onClick={reportCallFailed}>無法接通，啟用語音指引</button>
        </div>
      </div>
    </section>
  )
}
