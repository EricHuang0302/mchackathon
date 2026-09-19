import { useEffect } from "react";

import { AppHeader } from "../../components/AppHeader";
import { ConnectivityBanner } from "../../components/ConnectivityBanner";
import { DemoControlPanel } from "../../components/DemoControlPanel";
import { useRescueStore } from "../../store/rescueStore";
import { Call119Screen } from "../call-mode/Call119Screen";
import { OnCallScreen } from "../call-mode/OnCallScreen";
import { HandoverScreen } from "./HandoverScreen";
import { VoiceGuidanceScreen } from "./VoiceGuidanceScreen";
import "./rescue.css";

export function RescuePage() {
  const mode = useRescueStore((state) => state.mode);
  const setOnline = useRescueStore((state) => state.setOnline);
  const isDemoMode = new URLSearchParams(window.location.search).get("demo") === "1";

  useEffect(() => {
    const updateConnection = () => setOnline(navigator.onLine);
    updateConnection();
    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);

    return () => {
      window.removeEventListener("online", updateConnection);
      window.removeEventListener("offline", updateConnection);
    };
  }, [setOnline]);

  return (
    <div className="rescue-app">
      <ConnectivityBanner />
      <AppHeader />
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
