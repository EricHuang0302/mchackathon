import { Wifi, WifiOff } from 'lucide-react'
import { useRescueStore } from '../store/rescueStore'

export function ConnectivityBanner() {
  const browserIsOnline = useRescueStore((state) => state.isOnline)
  const demoNetworkOverride = useRescueStore((state) => state.demoNetworkOverride)
  const isOnline = demoNetworkOverride ?? browserIsOnline
  return (
    <div className={`connectivity-banner ${isOnline ? 'online' : 'offline'}`} role="status">
      {isOnline ? <Wifi size={15} /> : <WifiOff size={15} />}
      <span>{isOnline ? '目前已連線・紀錄可正常同步' : '目前離線・操作會保留在此裝置'}</span>
    </div>
  )
}
