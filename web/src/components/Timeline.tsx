import { useRescueStore } from '../store/rescueStore'

type TimelineProps = {
  limit?: number
  compact?: boolean
}

const eventLabels: Record<string, string> = {
  CPR_STARTED: '開始 CPR',
  AED_ASSIGNED: '有人去拿 AED',
  AED_REASSIGNED: '重新指派 AED',
  AED_ARRIVED: 'AED 抵達',
  PATIENT_STATUS_CHANGED: '患者狀態改變',
}

const formatTime = (timestamp: string) => new Intl.DateTimeFormat('zh-TW', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
}).format(new Date(timestamp))

export function Timeline({ limit, compact = false }: TimelineProps) {
  const timeline = useRescueStore((state) => state.timeline)
  const visibleEvents = limit === undefined ? timeline : timeline.slice(-limit)

  if (visibleEvents.length === 0) {
    return <p className="timeline-empty">尚無事件紀錄</p>
  }

  return (
    <ol className={`timeline${compact ? ' timeline-compact' : ''}`}>
      {visibleEvents.map((event) => (
        <li className="timeline-item" key={event.id}>
          <time dateTime={event.timestamp}>{formatTime(event.timestamp)}</time>
          <span className="timeline-marker" aria-hidden="true" />
          <div className="timeline-content">
            <strong>{eventLabels[event.type] ?? event.type}</strong>
            {event.note && <p>{event.note}</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
