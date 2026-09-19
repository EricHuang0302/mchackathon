import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, CircularProgress, Stack, Typography } from "@mui/material";
import { Check, CircleHelp, Clock3, RefreshCw } from "lucide-react";
import { useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import { getOrCreateSession, getParticipantGrant } from "../../lib/connection/session";
import type { HandoffEventsResponse, SceneSnapshotResponse } from "../../types/api";
import { DemoHandoffPage } from "./DemoHandoffPage";

const observationLabels: Record<string, string> = {
  breathing_reported: "呼吸狀態",
  responsiveness_reported: "意識反應",
  bleeding_reported: "出血狀況",
  location_reported: "事故位置",
};

const eventLabels: Record<string, string> = {
  "mode.changed": "救援模式已切換",
  "call.reported": "119 通話狀態已更新",
  "action.reported": "現場回報一項操作",
  "event.corrected": "現場紀錄已更正",
  "observation.proposed": "系統提出一項待確認觀察",
  "observation.confirmed": "現場觀察已確認",
  "helper.updated": "協助者進度已更新",
};

const formatTime = (value: string) => new Intl.DateTimeFormat("zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value));

export function HandoffPage() {
  const { incidentId = "" } = useParams();
  if (incidentId === "demo-incident") return <DemoHandoffPage incidentId={incidentId} />;
  return <ConnectedHandoffPage incidentId={incidentId} />;
}

function ConnectedHandoffPage({ incidentId }: { incidentId: string }) {
  const [snapshot, setSnapshot] = useState<SceneSnapshotResponse>();
  const [events, setEvents] = useState<HandoffEventsResponse["events"]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string>();
  const [checkedAt, setCheckedAt] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const grant = getParticipantGrant();
      if (!grant || grant.incidentId !== incidentId || grant.scope !== "ems_viewer") {
        throw new Error("missing-ems-grant");
      }
      const session = await getOrCreateSession("participant");
      const api = new ApiClient(session.sessionToken);
      const currentSnapshot = await api.getSnapshot(incidentId);
      const allEvents: HandoffEventsResponse["events"] = [];
      let cursor: string | undefined;
      do {
        const page = await api.getHandoffEvents(incidentId, cursor);
        allEvents.push(...page.events);
        cursor = page.nextCursor ?? undefined;
      } while (cursor);
      setSnapshot(currentSnapshot);
      setEvents(allEvents);
      setCheckedAt(Date.now());
      setError(undefined);
    } catch (reason) {
      setError(reason instanceof Error && reason.message === "missing-ems-grant"
        ? "找不到有效的 EMS 交接授權，請重新掃描現場提供的 QR Code。"
        : userMessageForApiError(reason));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [incidentId]);

  // External API state is intentionally synchronized when this scoped view mounts.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { void load(); }, [load]);

  const latestEventAt = useMemo(() => events.reduce<string | undefined>((latest, event) => !latest || new Date(event.serverTime).getTime() > new Date(latest).getTime() ? event.serverTime : latest, undefined), [events]);
  const stale = latestEventAt ? checkedAt - new Date(latestEventAt).getTime() > 120_000 : false;
  const refresh = () => {
    setRefreshing(true);
    void load();
  };

  if (loading) return <Stack sx={{ py: 8, alignItems: "center" }}><CircularProgress /><Typography sx={{ mt: 2 }}>正在讀取交接資料…</Typography></Stack>;
  if (!snapshot) return <Stack spacing={2}><Alert severity="error">{error ?? "目前無法讀取交接資料。"}</Alert><Button variant="outlined" onClick={() => load()}>重新讀取</Button></Stack>;

  return (
    <Stack spacing={3} className="helper-page-enter">
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between" }}>
        <div><div className="helper-kicker helper-kicker--red">EMS HANDOFF · 限時檢視</div><Typography component="h1" variant="h3">現場資訊交接</Typography></div>
        <Chip icon={<Clock3 size={16} />} label={`快照 r${snapshot.snapshotRevision}`} color={stale ? "warning" : "success"} variant="outlined" />
      </Stack>

      {stale ? <StatusBanner title="資料可能已過時" severity="warning">最後一筆事件已超過兩分鐘，請向現場人員重新確認。</StatusBanner> : null}
      {error ? <Alert severity="warning">{error}</Alert> : null}

      <Card className="snapshot-card"><CardContent>
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}><Typography component="h2" variant="h5">現場觀察</Typography><Typography variant="caption">Generated through r{snapshot.generatedThroughRevision}</Typography></Stack>
        {snapshot.observations.length === 0 ? <Typography sx={{ mt: 2 }} color="text.secondary">目前尚無已同步的現場觀察資料。請以現場評估與派遣資訊為準。</Typography> : <div className="handoff-observations">{snapshot.observations.map((observation) => <div key={observation.observationId}><Stack direction="row" spacing={.75} sx={{ alignItems: "center" }}><Typography variant="overline">{observationLabels[observation.key] ?? observation.key}</Typography>{observation.confirmation === "confirmed" ? <Check size={16} aria-label="已確認" /> : <CircleHelp size={16} aria-label="未確認" />}</Stack><Typography>{String(observation.value)}</Typography><Typography variant="caption" color="text.secondary">{formatTime(observation.observedAt)} · {observation.confirmation}</Typography></div>)}</div>}
      </CardContent></Card>

      <StatusBanner title="MIST 尚未由後端產生" severity="warning">本頁不會用 Demo 內容冒充正式摘要；救護人員到場後仍須自行評估並口頭確認。</StatusBanner>

      <Card><CardContent>
        <Typography component="h2" variant="h5">完整事件時間軸</Typography>
        {events.length === 0 ? <Typography sx={{ mt: 2 }} color="text.secondary">目前沒有可讀取的事件。</Typography> : <ol className="handoff-timeline">{events.map((event) => <li key={event.eventId}><time dateTime={event.serverTime}>{formatTime(event.clientTime)}</time><span>{eventLabels[event.type] ?? event.type}<small>{event.serverTime === event.clientTime ? "現場時間" : `伺服器收到 ${formatTime(event.serverTime)}`}</small></span></li>)}</ol>}
      </CardContent></Card>

      <Button variant="outlined" startIcon={<RefreshCw size={18} />} disabled={refreshing} onClick={refresh}>{refreshing ? "正在更新…" : "更新交接資料"}</Button>
      <Typography variant="caption" color="text.secondary">Incident {incidentId} · EMS scoped access</Typography>
    </Stack>
  );
}
