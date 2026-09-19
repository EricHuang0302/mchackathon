import { useEffect } from 'react'
import { ConnectivityBanner } from './components/ConnectivityBanner'
import { AppHeader } from './components/AppHeader'
import { DemoControlPanel } from './components/DemoControlPanel'
import { Call119Screen } from './features/call-mode/Call119Screen'
import { OnCallScreen } from './features/call-mode/OnCallScreen'
import { HandoverScreen } from './features/rescue/HandoverScreen'
import { VoiceGuidanceScreen } from './features/rescue/VoiceGuidanceScreen'
import { useRescueStore } from './store/rescueStore'
import './App.css'

function App() {
  const mode = useRescueStore((state) => state.mode)
  const setOnline = useRescueStore((state) => state.setOnline)
  const isDemoMode = new URLSearchParams(window.location.search).get('demo') === '1'

  useEffect(() => {
    const updateConnection = () => setOnline(navigator.onLine)
    updateConnection()
    window.addEventListener('online', updateConnection)
    window.addEventListener('offline', updateConnection)

    return () => {
      window.removeEventListener('online', updateConnection)
      window.removeEventListener('offline', updateConnection)
    }
  }, [setOnline])

  return (
    <div className="app-shell">
      <ConnectivityBanner />
      <AppHeader />
      <main className="app-main" aria-live="polite">
        {mode === 'call_119' && <Call119Screen />}
        {mode === 'on_call' && <OnCallScreen />}
        {mode === 'voice_guidance' && <VoiceGuidanceScreen />}
        {mode === 'handover' && <HandoverScreen />}
      </main>
      {isDemoMode && <DemoControlPanel />}
    </div>
  )
}

export default App
