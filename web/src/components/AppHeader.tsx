import { HeartPulse } from 'lucide-react'
import { DEMO_WARNING, isDemoMode } from '../lib/demoMode'
import { useRescueStore } from '../store/rescueStore'
import type { RescueMode } from '../types/rescue'

const modeLabels: Record<RescueMode, string> = {
  call_119: '準備報案',
  on_call: '119 通話中',
  voice_guidance: '急救指引',
  handover: '現場交接',
}

export function AppHeader() {
  const mode = useRescueStore((state) => state.mode)
  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true"><HeartPulse size={22} strokeWidth={2.8} /></span>
        安心救援
      </div>
      <div className="header-status">
        {isDemoMode() && <span className="demo-warning">{DEMO_WARNING}</span>}
        <span className="mode-label">{modeLabels[mode]}</span>
      </div>
    </header>
  )
}
