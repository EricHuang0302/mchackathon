import { useEffect, useState } from "react";
import { Alert, Card, CardContent, Chip, CircularProgress, Stack, Typography } from "@mui/material";
import { useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import { getOrCreateSession, getParticipantGrant } from "../../lib/connection/session";
import type { HandoffEventsResponse, SceneSnapshotResponse } from "../../types/api";

export function HandoffPage() {
  const { incidentId } = useParams();
  const [snapshot, setSnapshot] = useState<SceneSnapshotResponse | null>(null);
  const [events, setEvents] = useState<HandoffEventsResponse["events"]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const grant = getParticipantGrant();
        if (!grant || grant.incidentId !== incidentId || grant.scope !== "ems_viewer") throw new Error("Missing EMS grant");
        const session = await getOrCreateSession("participant");
        const api = new ApiClient(session.sessionToken);
        const currentSnapshot = await api.getSnapshot(incidentId!);
        const allEvents: HandoffEventsResponse["events"] = [];
        let cursor: string | undefined;
        do {
          const page = await api.getHandoffEvents(incidentId!, cursor);
          allEvents.push(...page.events); cursor = page.nextCursor ?? undefined;
        } while (cursor);
        if (active) { setSnapshot(currentSnapshot); setEvents(allEvents); }
      } catch (reason) { if (active) setError(userMessageForApiError(reason)); }
    })();
    return () => { active = false; };
  }, [incidentId]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (!snapshot) return <Stack sx={{ py: 8, alignItems: "center" }}><CircularProgress /><Typography sx={{ mt: 2 }}>正在讀取交接資料…</Typography></Stack>;

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between" }}>
        <div><Typography component="p" variant="overline" color="primary">EMS handoff</Typography><Typography component="h1" variant="h3">現場交接</Typography></div>
        <Chip label={`快照 r${snapshot.snapshotRevision}`} color="success" variant="outlined" />
      </Stack>

      <Card className="snapshot-card"><CardContent>
        <Typography component="h2" variant="h5">現場快照</Typography>
        {snapshot.observations.length === 0 ? <Typography sx={{ mt: 2 }} color="text.secondary">目前尚無已同步的現場觀察資料。</Typography> : snapshot.observations.map((observation) => (
          <div key={observation.observationId} className="mist-row"><div><Typography variant="overline">{observation.key}</Typography><Typography>{String(observation.value)} · {observation.confirmation}</Typography></div></div>
        ))}
      </CardContent></Card>

      <StatusBanner title="MIST 尚未接通" severity="warning">後端目前沒有 MIST projection；此頁不會用 mock 內容冒充正式摘要。</StatusBanner>

      <Card><CardContent>
        <Typography component="h2" variant="h5">完整事件時間軸</Typography>
        {events.length === 0 ? <Typography sx={{ mt: 2 }} color="text.secondary">尚無可讀取的事件。</Typography> : <ol className="handoff-timeline">{events.map((event) => <li key={event.eventId}><time>{new Date(event.clientTime).toLocaleTimeString("zh-TW", { hour12: false })}</time><span>{event.type}</span></li>)}</ol>}
      </CardContent></Card>
    </Stack>
  );
}
