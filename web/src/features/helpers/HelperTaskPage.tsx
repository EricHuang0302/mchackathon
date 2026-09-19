import { useEffect, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import { getOrCreateSession, getParticipantGrant } from "../../lib/connection/session";
import type { SceneSnapshotResponse, ShareScope } from "../../types/api";
import { CanonicalSnapshotCard } from "../rescue/CanonicalSnapshotCard";

export function HelperTaskPage() {
  const { helperId, incidentId } = useParams();
  const [revision, setRevision] = useState(0);
  const [status, setStatus] = useState("accepted");
  const [message, setMessage] = useState("正在讀取 AED 資料…");
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<ShareScope>("aed_runner");
  const [snapshot, setSnapshot] = useState<SceneSnapshotResponse | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const grant = getParticipantGrant();
        if (!grant || grant.incidentId !== incidentId || grant.helperId !== helperId) throw new Error("Missing scoped grant");
        if (active) setScope(grant.scope);
        const session = await getOrCreateSession("participant");
        const api = new ApiClient(session.sessionToken);
        if (grant.scope === "ambulance_greeter") {
          const current = await api.getSnapshot(incidentId!);
          if (active) { setSnapshot(current); setMessage(`現場快照 r${current.snapshotRevision}`); }
        } else {
          const result = await api.getAeds(incidentId!);
          if (active) setMessage(result.candidates.length ? `取得 ${result.candidates.length} 筆 AED 候選資料` : "後端目前沒有載入真實 AED 候選資料或路線，請依現場指示行動。");
        }
      } catch (reason) { if (active) setError(userMessageForApiError(reason)); }
    })();
    return () => { active = false; };
  }, [helperId, incidentId]);

  const report = async (nextStatus: "arrived" | "unavailable" | "obtained") => {
    try {
      const session = await getOrCreateSession("participant");
      const result = await new ApiClient(session.sessionToken).updateHelper(incidentId!, helperId!, { updateId: crypto.randomUUID(), expectedAssignmentRevision: revision, status: nextStatus, reportedAt: new Date().toISOString() });
      setRevision(result.assignmentRevision); setStatus(result.status); setError(null);
    } catch (reason) { setError(userMessageForApiError(reason)); }
  };

  return (
    <Stack spacing={3}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ alignItems: "flex-start", justifyContent: "space-between" }}
      >
        <div>
          <Typography component="p" variant="overline" color="secondary">
            {scope === "ambulance_greeter" ? "Ambulance greeter" : "AED runner"}
          </Typography>
          <Typography component="h1" variant="h3">
            {scope === "ambulance_greeter" ? `接應救護車 · 快照 r${snapshot?.snapshotRevision ?? 0}` : "前往警衛室取得 AED"}
          </Typography>
        </div>
        <Chip label={status} color="secondary" />
      </Stack>

      {scope === "ambulance_greeter" ? (
        <Card><CardContent><Typography component="h2" variant="h5">現場快照</Typography><CanonicalSnapshotCard snapshot={snapshot} /></CardContent></Card>
      ) : <Card>
        <CardContent>
          <Typography component="h2" variant="h5">
            AED 目的地尚未提供
          </Typography>
          <Typography sx={{ mt: 1 }}>目前 API 沒有候選位置、步行路線或 ETA。</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.5 }}>
            請依現場指派者提供的資訊行動；介面不會捏造導航資料。
          </Typography>
        </CardContent>
      </Card>}

      <StatusBanner title="AED 資料狀態" severity="warning">{message}</StatusBanner>
      {error && <Alert severity="error">{error}</Alert>}

      {scope === "aed_runner" && <Stack spacing={1.5}>
        <Button variant="contained" color="secondary" size="large" onClick={() => report("arrived")}>
          我已抵達 AED 位置
        </Button>
        <Button variant="outlined" color="error" size="large" onClick={() => report("unavailable")}>
          無法取得 AED
        </Button>
      </Stack>}

      <Typography variant="caption" color="text.secondary">
        Demo IDs: incident={incidentId}, helper={helperId}
      </Typography>
    </Stack>
  );
}
