import { useMemo, useState } from "react";
import { Button, Card, CardContent, Chip, LinearProgress, Stack, Typography } from "@mui/material";
import { CheckCircle2, MapPin, Radio, RefreshCw, Route, WifiOff } from "lucide-react";

import { TaskMap } from "../../components/maps/TaskMap";
import { StatusBanner } from "../../components/ui/StatusBanner";
import type { HelperTaskStatus } from "../../types/domain";
import { demoAedTask, demoGreeterTask, reassignedAed } from "./demoData";
import type { HelperTask } from "./types";
import { useLocationSharing } from "./useLocationSharing";

const labels: Partial<Record<HelperTaskStatus, string>> = {
  en_route: "前往目的地", arrived: "已抵達", collected: "已取得 AED",
  returning: "送回現場", delivered: "任務完成", unavailable: "無法完成",
};

export function DemoHelperTask({ helperId, incidentId }: { helperId: string; incidentId: string }) {
  const initialTask = useMemo(() => helperId === "demo-greeter" ? demoGreeterTask : demoAedTask, [helperId]);
  const [task, setTask] = useState<HelperTask>(initialTask);
  const [notice, setNotice] = useState<string>();
  const [offline, setOffline] = useState(false);
  const location = useLocationSharing();
  const isGreeter = task.role === "ambulance_greeter";
  const isFinished = task.status === "delivered" || (isGreeter && task.status === "arrived");
  const returning = !isGreeter && ["collected", "returning", "delivered"].includes(task.status);
  const destination = returning ? task.scene : task.destination;
  const progress = isGreeter ? isFinished ? 100 : 45 : ({ en_route: 20, arrived: 45, collected: 62, returning: 80, delivered: 100 } as Partial<Record<HelperTaskStatus, number>>)[task.status] ?? 10;

  const advance = () => {
    setNotice(undefined);
    if (isGreeter) return setTask((current) => ({ ...current, status: "arrived" }));
    const next: Partial<Record<HelperTaskStatus, HelperTaskStatus>> = {
      en_route: "arrived", arrived: "collected", collected: "returning", returning: "delivered",
    };
    setTask((current) => ({ ...current, status: next[current.status] ?? current.status }));
  };

  const reportUnavailable = () => {
    if (task.assignmentRevision === 1) {
      setTask((current) => ({ ...current, assignmentRevision: 2, destination: reassignedAed, status: "en_route" }));
      setNotice("Demo：原 AED 無法取得，已改派至成功大學圖書館。");
    } else {
      setTask((current) => ({ ...current, status: "unavailable" }));
      setNotice("Demo：已回報無法完成，現場正在尋找其他協助者。");
    }
  };

  const actionLabel = isGreeter ? "我已抵達接應點" : task.status === "en_route" ? "我已抵達 AED 位置" : task.status === "arrived" ? "我已取得 AED" : task.status === "collected" ? "開始送回事故現場" : "AED 已送達現場";

  return (
    <Stack spacing={2.5} className="helper-page-enter">
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <div><div className="helper-kicker">Demo · {isGreeter ? "救護車接應" : "AED 取件"}</div><Typography component="h1" variant="h3">{isFinished ? "任務完成" : returning ? "將 AED 送回現場" : `前往${task.destination.name}`}</Typography></div>
        <Chip label={labels[task.status] ?? task.status} color={isFinished ? "success" : task.status === "unavailable" ? "error" : "secondary"} />
      </Stack>
      <div><Stack direction="row" sx={{ justifyContent: "space-between", mb: .75 }}><Typography variant="caption" sx={{ fontWeight: 800 }}>任務進度</Typography><Typography variant="caption">{progress}%</Typography></Stack><LinearProgress variant="determinate" value={progress} /></div>
      {offline ? <StatusBanner title="Demo：連線中斷" severity="error">目前操作會暫存在裝置上。</StatusBanner> : null}
      {notice ? <StatusBanner title="任務已更新" severity="warning">{notice}</StatusBanner> : null}
      {location.state === "denied" || location.state === "unavailable" ? <StatusBanner title="無法取得定位" severity="warning">仍可依地址與外部導航完成任務。</StatusBanner> : null}

      {isFinished ? <Card className="mission-complete-card"><CardContent><CheckCircle2 size={42} /><Typography variant="h5" sx={{ mt: 1 }}>現場已收到你的回報</Typography></CardContent></Card> : task.status === "unavailable" ? <StatusBanner title="任務已交回現場" severity="warning">請勿繼續前往原目的地。</StatusBanner> : <>
        <TaskMap destination={destination.coordinates} destinationLabel={destination.name} estimateSource="route" markerLabel={isGreeter ? "集合" : returning ? "現場" : "AED"} origin={location.position} />
        <Card className="destination-card"><CardContent><Stack direction="row" spacing={1} sx={{ alignItems: "center" }}><MapPin size={22} /><Typography variant="h5">{destination.name}</Typography></Stack><Typography sx={{ mt: 1.5 }}>{destination.address}</Typography><Typography color="text.secondary" sx={{ mt: .75 }}>{destination.accessNote}</Typography><Stack direction="row" sx={{ mt: 2, flexWrap: "wrap", gap: 1 }}><Chip icon={<Route size={16} />} label={`約 ${destination.distanceMeters} 公尺`} /><Chip label={`步行約 ${destination.walkingMinutes} 分鐘`} /></Stack></CardContent></Card>
        {location.state === "sharing" ? <StatusBanner title="正在分享位置" severity="success">精確度約 {Math.round(location.position?.accuracyMeters ?? 0)} 公尺。</StatusBanner> : <Button variant="outlined" onClick={location.start} disabled={location.state === "requesting"} startIcon={<Radio size={20} />}>{location.state === "requesting" ? "正在取得定位…" : "開始分享我的位置"}</Button>}
        <Stack spacing={1.25} className="task-actions"><Button variant="contained" color={isGreeter ? "primary" : "secondary"} size="large" onClick={advance}>{actionLabel}</Button>{!isGreeter && ["en_route", "arrived"].includes(task.status) ? <Button variant="outlined" color="error" onClick={reportUnavailable}>無法取得 AED</Button> : null}</Stack>
      </>}
      <Card variant="outlined" className="demo-switches"><CardContent><Typography variant="overline">Demo controls</Typography><Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}><Button size="small" startIcon={offline ? <RefreshCw size={16} /> : <WifiOff size={16} />} onClick={() => setOffline((value) => !value)}>{offline ? "模擬恢復連線" : "模擬斷線"}</Button>{!isGreeter && !isFinished ? <Button size="small" onClick={reportUnavailable}>模擬 AED 改派</Button> : null}</Stack></CardContent></Card>
      <Typography variant="caption">Incident {incidentId} · Helper {helperId} · Assignment r{task.assignmentRevision}</Typography>
    </Stack>
  );
}
