import { VolumeX } from 'lucide-react'

export function CprVisualMetronome() {
  return (
    <div className="card">
      <h2 className="card-title"><VolumeX size={22} />視覺 CPR 節拍器・無聲</h2>
      <div className="metronome" aria-label="每分鐘 110 下的無聲視覺節拍器">
        <div className="pulse-ring"><div><strong>按</strong><span>110 次／分鐘</span></div></div>
      </div>
    </div>
  )
}
