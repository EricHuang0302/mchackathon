import { useEffect, useMemo, useState } from "react";
import { Button, Card, CardContent, Chip, Divider, Stack, Typography } from "@mui/material";
import { Check, CircleHelp, Clock3, MapPin, RefreshCw } from "lucide-react";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { DEMO_TIMELINE_STORAGE_KEY, loadDemoTimeline } from "../../lib/demo/demoTimeline";
import type { TimelineEvent } from "../../types/rescue";
import { demoAedTask, demoMist, demoTimeline } from "../helpers/demoData";

const formatTime = (value: string) => new Intl.DateTimeFormat("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));

const eventLabels: Record<string, string> = {
  CPR_STARTED: "開始 CPR",
  AED_ASSIGNED: "已指派 AED 取件者",
  AED_UNAVAILABLE: "AED 無法取得",
  AED_REASSIGNED: "已重新指派 AED",
  AED_ARRIVED: "AED 已抵達",
  PATIENT_STATUS_CHANGED: "患者狀態改變",
};

function timelineLabel(event: TimelineEvent) {
  const label = eventLabels[event.type] ?? event.type;
  return event.note ? `${label}：${event.note}` : label;
}

export function DemoHandoffPage({ incidentId }: { incidentId: string }) {
  const [stale, setStale] = useState(false);
  const [sharedTimeline, setSharedTimeline] = useState<TimelineEvent[] | null>(() => loadDemoTimeline());
  const snapshot = demoAedTask.snapshot;
  const timeline = useMemo(() => sharedTimeline === null
    ? demoTimeline
    : sharedTimeline.map((event) => ({
        id: event.id,
        occurredAt: event.timestamp,
        label: timelineLabel(event),
        confirmation: "reported" as const,
      })), [sharedTimeline]);

  useEffect(() => {
    const update = (event: StorageEvent) => {
      if (event.key === DEMO_TIMELINE_STORAGE_KEY) setSharedTimeline(loadDemoTimeline());
    };
    window.addEventListener("storage", update);
    return () => window.removeEventListener("storage", update);
  }, []);

  return <Stack spacing={3} className="helper-page-enter">
    <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between" }}><div><div className="helper-kicker helper-kicker--red">Demo · EMS HANDOFF</div><Typography component="h1" variant="h3">一頁掌握現場狀況</Typography></div><Chip icon={<Clock3 size={16} />} label={stale ? "資料可能已過時" : "快照 r12 · 20 秒前"} color={stale ? "warning" : "success"} variant="outlined" /></Stack>
    {stale ? <StatusBanner title="超過 2 分鐘未收到更新" severity="warning">請向現場人員口頭確認患者狀況與已完成處置。</StatusBanner> : null}
    <Card className="snapshot-card"><CardContent><Stack direction="row" spacing={1} sx={{ alignItems: "center" }}><MapPin size={22} /><Typography variant="h5">現場快照</Typography></Stack><div className="handoff-snapshot-grid"><div><Typography variant="overline">位置</Typography><Typography>{snapshot.location}</Typography></div><div><Typography variant="overline">現場狀況</Typography><Typography>{snapshot.situation}</Typography></div><div><Typography variant="overline">已做處置</Typography><Typography>{snapshot.treatment}</Typography></div><div><Typography variant="overline">入口資訊</Typography><Typography>{snapshot.entrance}</Typography></div></div></CardContent></Card>
    <StatusBanner title="Demo 合成摘要" severity="warning">此頁為展示資料，不代表正式事故或臨床判斷。</StatusBanner>
    <Card><CardContent><Typography variant="h5">MIST</Typography><Stack divider={<Divider flexItem />}>{demoMist.map((item) => <div className="mist-row" key={item.letter}><span className="mist-letter">{item.letter}</span><div><Stack direction="row" spacing={.75} sx={{ alignItems: "center" }}><Typography variant="overline">{item.label}</Typography>{item.confirmed ? <Check size={16} /> : <CircleHelp size={16} />}</Stack><Typography>{item.value}</Typography></div></div>)}</Stack></CardContent></Card>
    <Card><CardContent><Typography variant="h5">完整時間軸</Typography>{timeline.length === 0 ? <Typography sx={{ mt: 2 }} color="text.secondary">目前尚無 Demo 事件。</Typography> : <ol className="handoff-timeline">{timeline.map((event) => <li key={event.id}><time>{formatTime(event.occurredAt)}</time><span>{event.label}<small>{event.confirmation === "confirmed" ? "已確認" : "現場回報"}</small></span></li>)}</ol>}</CardContent></Card>
    <Card variant="outlined" className="demo-switches"><CardContent><Typography variant="overline">Demo controls</Typography><Button size="small" startIcon={<RefreshCw size={16} />} onClick={() => setStale((value) => !value)} sx={{ ml: 1 }}>{stale ? "模擬收到更新" : "模擬資料過時"}</Button></CardContent></Card>
    <Typography variant="caption">Demo incident: {incidentId}</Typography>
  </Stack>;
}
