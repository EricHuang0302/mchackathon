import { useEffect } from "react";

import { AppHeader } from "../../components/AppHeader";
import { ConnectivityBanner } from "../../components/ConnectivityBanner";
import { DemoControlPanel } from "../../components/DemoControlPanel";
import { incidentRuntime } from "../../lib/connection/incidentRuntime";
import { registerOfflineWorker } from "../../lib/offline/serviceWorkerRegistration";
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
    incidentRuntime.configure(setIntegrationStatus, { demoMode: isDemoMode });
    if (!isDemoMode) {
      void incidentRuntime.initialize();
      const approvedAssets = [
        "/",
        "/index.html",
        "/favicon.svg",
        ...performance
          .getEntriesByType("resource")
          .map((entry) => new URL(entry.name).pathname)
          .filter((path) => path.startsWith("/assets/")),
      ];
      void registerOfflineWorker({
        scriptUrl: "/runtime-service-worker.js",
        approvedAssets: [...new Set(approvedAssets)],
        incidentActive: () => useRescueStore.getState().mode !== "handover",
      }).catch(() => setIntegrationStatus({
        phase: "degraded",
        message: "離線快取目前無法啟用",
      }));
    }
    const updateConnection = () => {
      setOnline(navigator.onLine);
    };
    updateConnection();
    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);

    return () => {
      window.removeEventListener("online", updateConnection);
      window.removeEventListener("offline", updateConnection);
    };
  }, [isDemoMode, setIntegrationStatus, setOnline]);

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
