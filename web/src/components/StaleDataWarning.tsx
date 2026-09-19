import { AlertTriangle } from 'lucide-react'
import { useRescueStore } from '../store/rescueStore'

export function StaleDataWarning() {
  const isDataStale = useRescueStore((state) => state.isDataStale)
  if (!isDataStale) return null

  return (
    <div className="stale-warning" role="alert">
      <AlertTriangle size={22} aria-hidden="true" />
      <span>資料可能已過期，最後更新於 7 分鐘前。請以現場狀況為準。</span>
    </div>
  )
}
