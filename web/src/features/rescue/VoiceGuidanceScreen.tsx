import { Phone, VolumeX } from 'lucide-react'
import { Timeline } from '../../components/Timeline'
import { useRescueStore } from '../../store/rescueStore'

export function VoiceGuidanceScreen() {
  const redial = useRescueStore((state) => state.redial)
  const beginHandover = useRescueStore((state) => state.beginHandover)

  return (
    <section className="screen" aria-labelledby="guidance-title">
      <div>
        <p className="eyebrow">目前急救指引</p>
        <h1 className="screen-title" id="guidance-title">持續胸外按壓</h1>
        <p className="screen-subtitle">若現場狀況改變，請立即重新撥打 119，並依派遣員指示操作。</p>
      </div>

      <div className="card">
        <div className="guidance-step">
          <span className="step-number">1</span>
          <div><strong>雙手放在胸口中央</strong><p>一手掌根疊在另一手上，手臂伸直。</p></div>
        </div>
        <div className="guidance-step">
          <span className="step-number">2</span>
          <div><strong>跟著節奏持續按壓</strong><p>每次按壓後讓胸口完全回彈，盡量不要中斷。</p></div>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title"><VolumeX size={22} />視覺 CPR 節拍器・無聲</h2>
        <div className="metronome" aria-label="每分鐘 110 下的無聲視覺節拍器">
          <div className="pulse-ring"><div><strong>按</strong><span>110 次／分鐘</span></div></div>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">處置紀錄</h2>
        <Timeline limit={4} compact />
      </div>

      <div className="action-stack">
        <a className="secondary-action" href="tel:119" onClick={redial}><Phone size={21} />重新撥打 119</a>
        <button className="primary-action" type="button" onClick={beginHandover}>救護人員已到場</button>
      </div>
    </section>
  )
}
