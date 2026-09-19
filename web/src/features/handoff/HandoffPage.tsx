import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, CircularProgress, Stack, Typography } from "@mui/material";
import { Clock3, RefreshCw } from "lucide-react";
import { useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import { getOrCreateSession, getParticipantGrant } from "../../lib/connection/session";
import type { HandoffReadResponse, MistEntry, SceneSnapshotResponse } from "../../types/api";
import { CanonicalSnapshotCard } from "../rescue/CanonicalSnapshotCard";
import { formatObservationValue, observationLabels, type ObservationKey } from "../rescue/snapshotFields";
import { DemoHandoffPage } from "./DemoHandoffPage";

const eventLabels: Record<string, string> = {
  "mode.changed": "救援模式已切換",
  "call.reported": "119 通話狀態已更新",
  "action.reported": "現場回報一項操作",
  "event.corrected": "現場紀錄已更正",
  "observation.proposed": "系統提出一項待確認觀察",
  "observation.confirmed": "現場觀察已確認",
  "helper.updated": "協助者進度已更新",
};

const mistSections: Array<[string, string, keyof Pick<HandoffReadResponse["mist"], "mechanism" | "injuries" | "signs">]> = [
  ["M", "發生機轉", "mechanism"],
  ["I", "傷勢", "injuries"],
  ["S", "徵象", "signs"],
];

const formatTime = (value: string) => new Intl.DateTimeFormat("zh-TW", {
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
}).format(new Date(value));

export function HandoffPage() {
  const { incidentId = "" } = useParams();
  if (incidentId === "demo-incident") return <DemoHandoffPage incidentId={incidentId} />;
  return <ConnectedHandoffPage incidentId={incidentId} />;
}

function ConnectedHandoffPage({ incidentId }: { incidentId: string }) {
  const [handoff, setHandoff] = useState<HandoffReadResponse>();
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
      setHandoff(await new ApiClient(session.sessionToken).getHandoff(incidentId, undefined, 100));
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

  useEffect(() => { void load(); }, [load]);

  const events = handoff?.timeline.entries ?? [];
  const latestEventAt = useMemo(() => events.reduce<string | undefined>(
    (latest, event) => !latest || Date.parse(event.serverTime) > Date.parse(latest) ? event.serverTime : latest,
    undefined,
  ), [events]);
  const stale = latestEventAt ? checkedAt - Date.parse(latestEventAt) > 120_000 : false;
  const snapshot = handoff ? { ...handoff.snapshot, observations: [] } satisfies SceneSnapshotResponse : undefined;

  if (loading) return <Stack sx={{ py: 8, alignItems: "center" }}><CircularProgress /><Typography sx={{ mt: 2 }}>正在讀取交接資料…</Typography></Stack>;
  if (!handoff || !snapshot) return <Stack spacing={2}><Alert severity="error">{error ?? "目前無法讀取交接資料。"}</Alert><Button variant="outlined" onClick={() => load()}>重新讀取</Button></Stack>;

  return <Stack spacing={3} className="helper-page-enter">
    <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between" }}>
      <div><div className="helper-kicker helper-kicker--red">EMS HANDOFF · 限時檢視</div><Typography component="h1" variant="h3">現場資訊交接</Typography></div>
      <Chip icon={<Clock3 size={16} />} label={`快照 r${snapshot.snapshotRevision}`} color={stale ? "warning" : "success"} variant="outlined" />
    </Stack>

    {stale && <StatusBanner title="資料可能已過時" severity="warning">最後一筆事件已超過兩分鐘，請向現場人員重新確認。</StatusBanner>}
    {error && <Alert severity="warning">{error}</Alert>}

    <Card className="snapshot-card"><CardContent>
      <Typography component="h2" variant="h5">現場快照</Typography>
      <CanonicalSnapshotCard snapshot={snapshot} />
    </CardContent></Card>

    <Card><CardContent>
      <Typography component="h2" variant="h5">MIST</Typography>
      <Stack sx={{ mt: 2 }}>
        {mistSections.map(([letter, label, key]) => <MistSection key={key} letter={letter} label={label} entries={handoff.mist[key]} />)}
        <div className="mist-row">
          <span className="mist-letter" aria-hidden="true">T</span>
          <div>
            <Typography component="h3" variant="overline">T · 已回報處置</Typography>
            {handoff.mist.treatment.reportedActions.length === 0
              ? <Typography color="text.secondary">不明／尚未回報</Typography>
              : handoff.mist.treatment.reportedActions.map((action) => <Typography key={action.eventId}>{action.action}</Typography>)}
          </div>
        </div>
      </Stack>
    </CardContent></Card>

    <Card><CardContent>
      <Typography component="h2" variant="h5">完整事件時間軸</Typography>
      {events.length === 0 ? <Typography sx={{ mt: 2 }} color="text.secondary">目前沒有可讀取的事件。</Typography> : <ol className="handoff-timeline">{events.map((event) => <li key={event.eventId}><time dateTime={event.serverTime}>{formatTime(event.clientTime)}</time><span>{eventLabels[event.type] ?? event.type}<small>{event.source} · {event.actorRole}</small></span></li>)}</ol>}
      {handoff.timeline.hasMore && <Alert severity="info" sx={{ mt: 2 }}>時間軸超過 100 筆；本頁顯示此次交接回應提供的最新一頁。</Alert>}
    </CardContent></Card>

    <Button variant="outlined" startIcon={<RefreshCw size={18} />} disabled={refreshing} onClick={() => { setRefreshing(true); void load(); }}>{refreshing ? "正在更新…" : "更新交接資料"}</Button>
    <Typography variant="caption" color="text.secondary">Incident {incidentId} · EMS scoped access</Typography>
  </Stack>;
}

function MistSection({ letter, label, entries }: { letter: string; label: string; entries: MistEntry[] }) {
  return <div className="mist-row">
    <span className="mist-letter" aria-hidden="true">{letter}</span>
    <div>
      <Typography component="h3" variant="overline">{letter} · {label}</Typography>
      {entries.length === 0
        ? <Typography color="text.secondary">不明／尚未回報</Typography>
        : entries.map((entry) => <div key={entry.key}>
          <Typography>{observationLabels[entry.key as ObservationKey] ?? entry.key}: {formatObservationValue(entry.value)}</Typography>
          <Typography variant="caption" color="text.secondary">
            {entry.confirmation} · {entry.observedAt ? formatTime(entry.observedAt) : "未觀察"}
          </Typography>
        </div>)}
    </div>
  </div>;
}
