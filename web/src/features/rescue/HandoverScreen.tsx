import { useEffect, useRef, useState } from 'react'
import { ClipboardCheck, MapPin, Radio } from 'lucide-react'
import { StaleDataWarning } from '../../components/StaleDataWarning'
import { Timeline } from '../../components/Timeline'
import { ShareInviteControl } from '../../components/ShareInviteControl'
import { CanonicalSnapshotCard } from './CanonicalSnapshotCard'
import { getPatientStatusText, getTreatmentSummary } from '../../store/rescueSelectors'
import { useRescueStore } from '../../store/rescueStore'
import type { AedStatus } from '../../types/rescue'

const aedLabels: Record<AedStatus, string> = {
  idle: '尚未指派',
  assigned: '已指派',
  en_route: '運送中',
  unavailable: '無法取得',
  reassigned: '已重新指派',
  arrived: '已抵達',
}

export function HandoverScreen() {
  const [isConfirmingReset, setIsConfirmingReset] = useState(false)
  const confirmButtonRef = useRef<HTMLButtonElement>(null)
  const resetIncident = useRescueStore((state) => state.resetIncident)
  const snapshot = useRescueStore((state) => state.snapshot)
  const aedStatus = useRescueStore((state) => state.aedStatus)
  const patientStatus = getPatientStatusText(snapshot?.observations ?? [])
  const treatmentSummary = getTreatmentSummary(snapshot?.actionsPerformed ?? [])

  useEffect(() => {
    if (!isConfirmingReset) return

    confirmButtonRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsConfirmingReset(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [isConfirmingReset])

  return (
    <section className="screen" aria-labelledby="handover-title">
      <div>
        <p className="eyebrow">救護人員已到場</p>
        <h1 className="screen-title" id="handover-title">現場資訊交接 · r{snapshot?.snapshotRevision ?? 0}</h1>
        <p className="screen-subtitle">將此畫面交給救護人員，快速掌握現場資訊與處置時間。</p>
      </div>

      <div className="handover-alert"><ClipboardCheck size={20} /> 保持急救操作，直到救護人員明確接手。</div>
      <StaleDataWarning />

      <div className="card">
        <h2 className="card-title"><MapPin size={22} />現場快照</h2>
        <dl className="snapshot-grid">
          <div className="snapshot-item"><dt>患者狀態</dt><dd>{patientStatus}</dd></div>
          <div className="snapshot-item"><dt>已做處置</dt><dd>{treatmentSummary}</dd></div>
        </dl>
        <CanonicalSnapshotCard snapshot={snapshot} />
      </div>

      <div className="card aed-status">
        <h2 className="card-title"><Radio size={22} />目前 AED 狀態</h2>
        <span className="aed-badge">{aedLabels[aedStatus]}</span>
      </div>

      <div className="card">
        <h2 className="card-title">完整事件時間軸</h2>
        <Timeline />
      </div>

      <div className="card">
        <h2 className="card-title">EMS 限時檢視</h2>
        <ShareInviteControl scope="ems_viewer" label="建立 EMS 交接連結" />
      </div>

      <button
        className="secondary-action handover-reset"
        type="button"
        onClick={() => setIsConfirmingReset(true)}
      >
        結束交接並返回首頁
      </button>

      {isConfirmingReset && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setIsConfirmingReset(false)
          }}
        >
          <div
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reset-dialog-title"
            aria-describedby="reset-dialog-description"
          >
            <h2 id="reset-dialog-title">要結束這次救援流程嗎？</h2>
            <p id="reset-dialog-description">返回首頁後，將準備開始新的救援流程。</p>
            <div className="modal-actions">
              <button className="modal-cancel" type="button" onClick={() => setIsConfirmingReset(false)}>
                取消
              </button>
              <button className="modal-confirm" type="button" onClick={resetIncident} ref={confirmButtonRef}>
                結束並返回首頁
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
