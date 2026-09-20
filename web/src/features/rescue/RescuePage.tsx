import { useEffect } from "react";

import { AppHeader } from "../../components/AppHeader";
import { ConnectivityBanner } from "../../components/ConnectivityBanner";
import { DemoControlPanel } from "../../components/DemoControlPanel";
import { incidentRuntime } from "../../lib/connection/incidentRuntime";
import { loadDemoTimeline, saveDemoTimeline } from "../../lib/demo/demoTimeline";
import { isDemoMode } from "../../lib/demoMode";
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
  const setObservationProposal = useRescueStore((state) => state.setObservationProposal);
  const setAgentPlan = useRescueStore((state) => state.setAgentPlan);
  const addAgentToolResult = useRescueStore((state) => state.addAgentToolResult);
  const demoMode = isDemoMode();
  const refreshSnapshot = useRescueStore((state) => state.refreshSnapshot);
  const setVoicePhase = useRescueStore((state) => state.setVoicePhase);

  useEffect(() => {
    let stopDemoTimelineSync: () => void = () => undefined;
    if (demoMode) {
      const storedTimeline = loadDemoTimeline();
      if (storedTimeline) useRescueStore.setState({ timeline: storedTimeline });
      saveDemoTimeline(useRescueStore.getState().timeline);
      stopDemoTimelineSync = useRescueStore.subscribe((state) => {
        saveDemoTimeline(state.timeline);
      });
    }
    incidentRuntime.configure(setIntegrationStatus, {
      demoMode,
      onObservationProposal: setObservationProposal,
      onAgentPlan: setAgentPlan,
      onAgentToolResult: addAgentToolResult,
    });
    void incidentRuntime.initialize().then(refreshSnapshot).catch(() => undefined);
    const approvedAssets = [
      "/", "/index.html", "/favicon.svg",
      ...performance.getEntriesByType("resource")
        .map((entry) => new URL(entry.name).pathname)
        .filter((path) => path.startsWith("/assets/")),
    ];
    void registerOfflineWorker({
      scriptUrl: "/runtime-service-worker.js",
      approvedAssets: [...new Set(approvedAssets)],
      incidentActive: () => useRescueStore.getState().mode !== "handover",
    }).catch(() => setIntegrationStatus({ phase: "degraded", message: "離線快取目前無法啟用" }));
    const stopVoiceStatusSync = incidentRuntime.subscribeVoiceStatus(setVoicePhase);
    const updateConnection = () => setOnline(navigator.onLine);
    updateConnection();
    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);
    return () => {
      stopVoiceStatusSync();
      stopDemoTimelineSync();
      window.removeEventListener("online", updateConnection);
      window.removeEventListener("offline", updateConnection);
    };
  }, [addAgentToolResult, demoMode, refreshSnapshot, setAgentPlan, setIntegrationStatus, setObservationProposal, setOnline, setVoicePhase]);

  return <div className="rescue-app">
    <ConnectivityBanner />
    <AppHeader />
    <div className={`integration-banner integration-${integration.phase}`} role="status">
      {integration.message}
      {integration.stateRevision !== undefined && <small>r{integration.stateRevision} · mode r{integration.modeRevision}</small>}
    </div>
    <main className="app-main" aria-live="polite">
      {mode === "call_119" && <Call119Screen demoMode={demoMode} />}
      {mode === "on_call" && <OnCallScreen />}
      {mode === "voice_guidance" && <VoiceGuidanceScreen demoMode={demoMode} />}
      {mode === "handover" && <HandoverScreen />}
    </main>
    {demoMode && <DemoControlPanel />}
  </div>;
}
