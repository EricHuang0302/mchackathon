import { ArrowRight, ShieldCheck, Speaker, UserRoundCheck, Phone } from 'lucide-react'
import { StaleDataWarning } from '../../components/StaleDataWarning'
import { useRescueStore } from '../../store/rescueStore'

export function Call119Screen() {
  const startCall = useRescueStore((state) => state.startCall)
  return (
    <section className="screen" aria-labelledby="call-title">
      <div>
        <p className="eyebrow">緊急救援</p>
        <h1 className="screen-title" id="call-title">先確保安全，再撥打 119</h1>
        <p className="screen-subtitle">清楚報案能讓救援更快抵達。保持冷靜，我們會陪你完成每一步。</p>
      </div>

      <StaleDataWarning />

      <div className="card">
        <h2 className="card-title"><ShieldCheck size={23} />撥號前快速確認</h2>
        <ul className="safety-list">
          <li><ShieldCheck size={21} /><span>先確認現場安全，遠離車流、火源、電線或其他危險。</span></li>
          <li><Speaker size={21} /><span>接通後開啟手機擴音，雙手可以繼續協助患者。</span></li>
          <li><UserRoundCheck size={21} /><span>若旁邊有人，明確指定一人負責報案：「請你撥 119」。</span></li>
        </ul>
      </div>

      <div className="sticky-action">
        <a className="danger-action" href="tel:119" onClick={startCall}>
          <Phone size={28} fill="currentColor" />撥打 119<ArrowRight size={25} />
        </a>
      </div>
    </section>
  )
}
