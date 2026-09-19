import { ArrowRight, ShieldCheck, Speaker, UserRoundCheck, Phone } from 'lucide-react'
import { StaleDataWarning } from '../../components/StaleDataWarning'
import { EMERGENCY_DIAL_HREF, EMERGENCY_DIAL_NUMBER } from '../../config/emergencyDial'
import { useRescueStore } from '../../store/rescueStore'

export function Call119Screen({ demoMode = false }: { demoMode?: boolean }) {
  const startCall = useRescueStore((state) => state.startCall)
  const dialAttempted = useRescueStore((state) => state.dialAttempted)
  const confirmCallConnected = useRescueStore((state) => state.confirmCallConnected)
  const reportCallFailed = useRescueStore((state) => state.reportCallFailed)
  return (
    <section className="screen" aria-labelledby="call-title">
      <div>
        <p className="eyebrow">緊急救援</p>
        <h1 className="screen-title" id="call-title">先確保安全，再撥打 119</h1>
        <p className="screen-subtitle">清楚報案能讓救援更快抵達。保持冷靜，我們會陪你完成每一步。</p>
      </div>

      <StaleDataWarning />

      <div className="muted-notice" role="note">
        <Phone size={22} /><span>原型測試僅撥打 {EMERGENCY_DIAL_NUMBER}，不會撥打真實 119。</span>
      </div>

      <div className="card">
        <h2 className="card-title"><ShieldCheck size={23} />撥號前快速確認</h2>
        <ul className="safety-list">
          <li><ShieldCheck size={21} /><span>先確認現場安全，遠離車流、火源、電線或其他危險。</span></li>
          <li><Speaker size={21} /><span>接通後開啟手機擴音，雙手可以繼續協助患者。</span></li>
          <li><UserRoundCheck size={21} /><span>若旁邊有人，明確指定一人負責報案：「請你撥 119」。</span></li>
        </ul>
      </div>

      <div className="sticky-action">
        {dialAttempted ? (
          <div className="action-stack">
            <button className="primary-action" type="button" onClick={confirmCallConnected}>已接通派遣員</button>
            <button className="secondary-action" type="button" onClick={reportCallFailed}>無法接通，啟用語音指引</button>
          </div>
        ) : demoMode ? (
          <button className="danger-action" type="button" onClick={startCall}>
            <Phone size={28} fill="currentColor" />模擬撥打 119<ArrowRight size={25} />
          </button>
        ) : (
          <a className="danger-action" href={EMERGENCY_DIAL_HREF} onClick={startCall}>
            <Phone size={28} fill="currentColor" />撥打 119<ArrowRight size={25} />
          </a>
        )}
      </div>
    </section>
  )
}
