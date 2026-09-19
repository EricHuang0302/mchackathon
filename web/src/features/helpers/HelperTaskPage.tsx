import { useMemo, useState } from "react";
import { Button, Card, CardContent, Chip, LinearProgress, Stack, Typography } from "@mui/material";
import { CheckCircle2, MapPin, Radio, RefreshCw, Route, WifiOff } from "lucide-react";
import { useParams } from "react-router";

import { TaskMap } from "../../components/maps/TaskMap";
import { StatusBanner } from "../../components/ui/StatusBanner";
import type { HelperTaskStatus } from "../../types/domain";
import { demoAedTask, demoGreeterTask, reassignedAed } from "./demoData";
import type { HelperTask } from "./types";
import { useLocationSharing } from "./useLocationSharing";

const statusLabels: Partial<Record<HelperTaskStatus, string>> = {
  en_route: "前往目的地",
  arrived: "已抵達",
  collected: "已取得 AED",
  returning: "送回現場",
  delivered: "任務完成",
  unavailable: "無法完成",
};

function nextAedStatus(status: HelperTaskStatus): HelperTaskStatus {
  if (status === "en_route") return "arrived";
  if (status === "arrived") return "collected";
  if (status === "collected") return "returning";
  if (status === "returning") return "delivered";
  return status;
}

function getActionLabel(task: HelperTask) {
  if (task.role === "ambulance_greeter") return "我已抵達接應點";
  if (task.status === "en_route") return "我已抵達 AED 位置";
  if (task.status === "arrived") return "我已取得 AED";
  if (task.status === "collected") return "開始送回事故現場";
  if (task.status === "returning") return "AED 已送達現場";
  return "任務已完成";
}

export function HelperTaskPage() {
  const { helperId, incidentId } = useParams();
  const initialTask = useMemo(
    () => (helperId === "demo-greeter" ? demoGreeterTask : demoAedTask),
    [helperId],
  );
  const [task, setTask] = useState<HelperTask>(initialTask);
  const [notice, setNotice] = useState<string>();
  const [offline, setOffline] = useState(false);
  const location = useLocationSharing();

  const isGreeter = task.role === "ambulance_greeter";
  const isFinished = task.status === "delivered" || (isGreeter && task.status === "arrived");
  const shouldReturnToScene = !isGreeter && ["collected", "returning", "delivered"].includes(task.status);
  const activeDestination = shouldReturnToScene ? task.scene : task.destination;
  const progressByStatus: Partial<Record<HelperTaskStatus, number>> = {
    en_route: 20,
    arrived: 45,
    collected: 62,
    returning: 80,
    delivered: 100,
  };
  const progress = isGreeter
    ? isFinished ? 100 : 45
    : (progressByStatus[task.status] ?? 10);

  const advance = () => {
    setNotice(undefined);
    if (isGreeter) {
      setTask((current) => ({ ...current, status: "arrived" }));
      return;
    }
    setTask((current) => ({ ...current, status: nextAedStatus(current.status) }));
  };

  const reportUnavailable = () => {
    if (task.assignmentRevision === 1) {
      setTask((current) => ({
        ...current,
        assignmentRevision: 2,
        destination: reassignedAed,
        status: "en_route",
      }));
      setNotice("原 AED 無法取得，系統已改派至成功大學圖書館。路線已更新。");
      return;
    }
    setTask((current) => ({ ...current, status: "unavailable" }));
    setNotice("已回報無法完成，現場正在尋找其他協助者。");
  };

  return (
    <Stack spacing={2.5} className="helper-page-enter">
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <div>
          <div className="helper-kicker">{isGreeter ? "救護車接應" : "AED 取件任務"}</div>
          <Typography component="h1" variant="h3">
            {isFinished ? "任務完成" : shouldReturnToScene ? "將 AED 送回現場" : `前往${task.destination.name}`}
          </Typography>
        </div>
        <Chip
          label={statusLabels[task.status] ?? task.status}
          color={isFinished ? "success" : task.status === "unavailable" ? "error" : "secondary"}
        />
      </Stack>

      <div>
        <Stack direction="row" sx={{ justifyContent: "space-between", mb: 0.75 }}>
          <Typography variant="caption" sx={{ fontWeight: 800 }}>任務進度</Typography>
          <Typography variant="caption" color="text.secondary">{progress}%</Typography>
        </Stack>
        <LinearProgress variant="determinate" value={progress} color={isFinished ? "success" : "secondary"} />
      </div>

      {offline ? (
        <StatusBanner title="連線中斷，保留目前指引" severity="error">
          位置與進度會暫存在此裝置；恢復連線後再同步。
        </StatusBanner>
      ) : null}
      {notice ? <StatusBanner title="任務已更新" severity="warning">{notice}</StatusBanner> : null}
      {location.state === "denied" || location.state === "unavailable" ? (
        <StatusBanner title="無法取得定位" severity="warning">
          你仍可依地址完成任務，或使用下方按鈕開啟 Google Maps 導航。
        </StatusBanner>
      ) : null}

      {isFinished ? (
        <Card className="mission-complete-card">
          <CardContent>
            <CheckCircle2 size={42} />
            <Typography component="h2" variant="h5" sx={{ mt: 1 }}>現場已收到你的回報</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.75 }}>
              {isGreeter ? "請留在入口並依救護人員指示協助。" : "AED 已送達，請依 119 派遣員與現場人員指示行動。"}
            </Typography>
          </CardContent>
        </Card>
      ) : task.status === "unavailable" ? (
        <StatusBanner title="任務已交回現場" severity="warning">
          請勿繼續前往原目的地；如仍在附近，可留意是否需要其他安全協助。
        </StatusBanner>
      ) : (
        <>
          <TaskMap
            destination={activeDestination.coordinates}
            destinationLabel={activeDestination.name}
            markerLabel={isGreeter ? "集合" : shouldReturnToScene ? "現場" : "AED"}
            origin={location.position}
          />

          <Card className="destination-card">
            <CardContent>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <MapPin size={22} />
                <Typography component="h2" variant="h5">{activeDestination.name}</Typography>
              </Stack>
              <Typography sx={{ mt: 1.5 }}>{activeDestination.address}</Typography>
              <Typography color="text.secondary" sx={{ mt: 0.75 }}>{activeDestination.accessNote}</Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: "wrap", gap: 1 }}>
                <Chip icon={<Route size={16} />} label={`約 ${activeDestination.distanceMeters} 公尺`} />
                <Chip label={`步行約 ${activeDestination.walkingMinutes} 分鐘`} />
                {activeDestination.availability ? <Chip color="success" variant="outlined" label={activeDestination.availability} /> : null}
              </Stack>
            </CardContent>
          </Card>

          {location.state === "sharing" ? (
            <StatusBanner title="正在分享位置" severity="success">
              精確度約 {Math.round(location.position?.accuracyMeters ?? 0)} 公尺；只在本次任務期間使用。
            </StatusBanner>
          ) : (
            <Button variant="outlined" onClick={location.start} disabled={location.state === "requesting"} startIcon={<Radio size={20} />}>
              {location.state === "requesting" ? "正在取得定位…" : "開始分享我的位置"}
            </Button>
          )}

          <Stack spacing={1.25} className="task-actions">
            <Button variant="contained" color={isGreeter ? "primary" : "secondary"} size="large" onClick={advance}>
              {getActionLabel(task)}
            </Button>
            {!isGreeter && ["en_route", "arrived"].includes(task.status) ? (
              <Button variant="outlined" color="error" size="large" onClick={reportUnavailable}>無法取得 AED</Button>
            ) : null}
          </Stack>
        </>
      )}

      <Card variant="outlined" className="demo-switches">
        <CardContent>
          <Typography variant="overline">Demo controls</Typography>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 1 }}>
            <Button size="small" startIcon={offline ? <RefreshCw size={16} /> : <WifiOff size={16} />} onClick={() => setOffline((value) => !value)}>
              {offline ? "模擬恢復連線" : "模擬斷線"}
            </Button>
            {!isGreeter && !isFinished ? <Button size="small" onClick={reportUnavailable}>模擬 AED 改派</Button> : null}
          </Stack>
        </CardContent>
      </Card>

      <Typography variant="caption" color="text.secondary">
        Incident {incidentId} · Helper {helperId} · Assignment r{task.assignmentRevision}
      </Typography>
    </Stack>
  );
}
