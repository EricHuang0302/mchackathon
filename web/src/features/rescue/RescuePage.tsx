import { useEffect } from "react";

import { AppHeader } from "../../components/AppHeader";
import { ConnectivityBanner } from "../../components/ConnectivityBanner";
import { DemoControlPanel } from "../../components/DemoControlPanel";
import { incidentRuntime } from "../../lib/connection/incidentRuntime";
import { useRescueStore } from "../../store/rescueStore";
import { Call119Screen } from "../call-mode/Call119Screen";
import { OnCallScreen } from "../call-mode/OnCallScreen";
import { HandoverScreen } from "./HandoverScreen";
import { VoiceGuidanceScreen } from "./VoiceGuidanceScreen";
import "./rescue.css";

export function RescuePage() {
  const mode = useRescueStore((state) => state.mode);
  const setOnline = useRescueStore((state) => state.setOnline);
  const integration = useRescueStore((state) => state.integration);
  const setIntegrationStatus = useRescueStore((state) => state.setIntegrationStatus);
  const isDemoMode = new URLSearchParams(window.location.search).get("demo") === "1";

  useEffect(() => {
    incidentRuntime.configure(setIntegrationStatus);
    void incidentRuntime.start();
    const updateConnection = () => {
      setOnline(navigator.onLine);
      if (navigator.onLine) incidentRuntime.onOnline();
    };
    const handleVisibility = () => { if (document.hidden) incidentRuntime.onHidden(); };
    updateConnection();
    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      window.removeEventListener("online", updateConnection);
      window.removeEventListener("offline", updateConnection);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [setIntegrationStatus, setOnline]);

  return (
    <div className="rescue-app">
      <ConnectivityBanner />
      <AppHeader />
      <div className={`integration-banner integration-${integration.phase}`} role="status">
        {integration.message}
        {integration.stateRevision !== undefined && <small>r{integration.stateRevision} · mode r{integration.modeRevision}</small>}
      </div>
      <main className="app-main" aria-live="polite">
        {mode === "call_119" && <Call119Screen />}
        {mode === "on_call" && <OnCallScreen />}
        {mode === "voice_guidance" && <VoiceGuidanceScreen />}
        {mode === "handover" && <HandoverScreen />}
      </main>
      {isDemoMode && <DemoControlPanel />}
    </div>
  );
}
