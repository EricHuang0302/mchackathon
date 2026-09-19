import { Navigate, Route, Routes } from "react-router";

import { AppFrame } from "../components/ui/AppFrame";
import { CallModePage } from "../features/call-mode/CallModePage";
import { HandoffPage } from "../features/handoff/HandoffPage";
import { HelperTaskPage } from "../features/helpers/HelperTaskPage";
import { JoinPage } from "../features/helpers/JoinPage";
import { RescuePage } from "../features/rescue/RescuePage";
import { NotFoundPage } from "./NotFoundPage";
import { routePatterns, routes } from "./routes";

export function App() {
  return (
    <Routes>
      <Route index element={<RescuePage />} />
      <Route element={<AppFrame />}>
        <Route path={routePatterns.callMode} element={<CallModePage />} />
        <Route path={routePatterns.join} element={<JoinPage />} />
        <Route
          path={routePatterns.helperTask}
          element={<HelperTaskPage />}
        />
        <Route path={routePatterns.handoff} element={<HandoffPage />} />
        <Route path="demo/helper" element={<Navigate replace to={routes.join("demo-aed-runner")} />} />
        <Route
          path="demo/ambulance"
          element={<Navigate replace to={routes.helperTask("demo-incident", "demo-greeter")} />}
        />
        <Route
          path="demo/handoff"
          element={<Navigate replace to={routes.handoff("demo-incident")} />}
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
