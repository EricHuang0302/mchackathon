import { useState } from 'react'
import { Bug, ChevronDown } from 'lucide-react'
import { useRescueStore } from '../store/rescueStore'
import type { AedStatus, RescueMode } from '../types/rescue'

const rescueModes: RescueMode[] = [
  'call_119',
  'on_call',
  'voice_guidance',
  'handover',
]

const aedStatuses: AedStatus[] = [
  'idle',
  'assigned',
  'en_route',
  'unavailable',
  'reassigned',
  'arrived',
]

const demoEvents = [
  'CPR_STARTED',
  'AED_ASSIGNED',
  'AED_UNAVAILABLE',
  'AED_REASSIGNED',
  'AED_ARRIVED',
  'PATIENT_STATUS_CHANGED',
] as const

export function DemoControlPanel() {
  const [isOpen, setIsOpen] = useState(false)
  const mode = useRescueStore((state) => state.mode)
  const aedStatus = useRescueStore((state) => state.aedStatus)
  const browserIsOnline = useRescueStore((state) => state.isOnline)
  const demoNetworkOverride = useRescueStore((state) => state.demoNetworkOverride)
  const isDataStale = useRescueStore((state) => state.isDataStale)
  const setMode = useRescueStore((state) => state.setMode)
  const setAedStatus = useRescueStore((state) => state.setAedStatus)
  const setDemoNetworkOverride = useRescueStore((state) => state.setDemoNetworkOverride)
  const setDataStale = useRescueStore((state) => state.setDataStale)
  const addTimelineEvent = useRescueStore((state) => state.addTimelineEvent)
  const resetIncident = useRescueStore((state) => state.resetIncident)

  return (
    <aside className="demo-tools" aria-label="Demo 工具">
      {isOpen && (
        <div className="demo-panel" id="demo-control-panel">
          <div className="demo-panel-header">
            <div>
              <span className="demo-kicker">僅供展示</span>
              <h2>Demo 控制台</h2>
            </div>
            <button className="demo-close" type="button" onClick={() => setIsOpen(false)} aria-label="收合 Demo 控制台">
              <ChevronDown size={20} />
            </button>
          </div>

          <fieldset className="demo-group">
            <legend>救援模式</legend>
            <div className="demo-grid demo-grid-two">
              {rescueModes.map((value) => (
                <button type="button" key={value} aria-pressed={mode === value} onClick={() => setMode(value)}>{value}</button>
              ))}
            </div>
          </fieldset>

          <fieldset className="demo-group">
            <legend>AED 狀態</legend>
            <div className="demo-grid demo-grid-three">
              {aedStatuses.map((value) => (
                <button type="button" key={value} aria-pressed={aedStatus === value} onClick={() => setAedStatus(value)}>{value}</button>
              ))}
            </div>
          </fieldset>

          <fieldset className="demo-group">
            <legend>網路狀態</legend>
            <div className="demo-grid demo-grid-two">
              <button type="button" aria-pressed={demoNetworkOverride === true} onClick={() => setDemoNetworkOverride(true)}>online</button>
              <button type="button" aria-pressed={demoNetworkOverride === false} onClick={() => setDemoNetworkOverride(false)}>offline</button>
            </div>
            <button className="demo-wide-button" type="button" onClick={() => setDemoNetworkOverride(null)}>
              使用真實網路狀態（目前 {browserIsOnline ? 'online' : 'offline'}）
            </button>
          </fieldset>

          <fieldset className="demo-group">
            <legend>資料新鮮度</legend>
            <div className="demo-grid demo-grid-two">
              <button type="button" aria-pressed={!isDataStale} onClick={() => setDataStale(false)}>Fresh</button>
              <button type="button" aria-pressed={isDataStale} onClick={() => setDataStale(true)}>Stale</button>
            </div>
          </fieldset>

          <fieldset className="demo-group">
            <legend>Timeline 測試事件</legend>
            <div className="demo-grid demo-grid-two">
              {demoEvents.map((eventType) => (
                <button
                  type="button"
                  key={eventType}
                  onClick={() => addTimelineEvent(eventType, '由 Demo 控制台新增')}
                >
                  {eventType}
                </button>
              ))}
            </div>
          </fieldset>

          <button className="demo-reset" type="button" onClick={resetIncident}>重設 Demo</button>
        </div>
      )}

      <button
        className="demo-fab"
        type="button"
        aria-expanded={isOpen}
        aria-controls="demo-control-panel"
        onClick={() => setIsOpen((open) => !open)}
      >
        <Bug size={18} />Demo
      </button>
    </aside>
  )
}
