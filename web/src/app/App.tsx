import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";

import { AppFrame } from "../components/ui/AppFrame";
import { HandoffPage } from "../features/handoff/HandoffPage";
import { HelperTaskPage } from "../features/helpers/HelperTaskPage";
import { JoinPage } from "../features/helpers/JoinPage";
import { RescuePage } from "../features/rescue/RescuePage";
import { NotFoundPage } from "./NotFoundPage";
import { routePatterns, routes } from "./routes";

export function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
      <Route index element={<RescuePage />} />
      <Route element={<AppFrame />}>
        <Route path="/call-mode" element={<Navigate replace to="/" />} />
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
    </>
  );
}

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}
