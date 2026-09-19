import { useState } from "react";
import { Button, Card, CardContent, Chip, Divider, Stack, Typography } from "@mui/material";
import { Check, CircleHelp, Clock3, MapPin, RefreshCw } from "lucide-react";
import { useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { demoAedTask, demoMist, demoTimeline } from "../helpers/demoData";

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}

export function HandoffPage() {
  const { incidentId } = useParams();
  const [stale, setStale] = useState(false);
  const snapshot = demoAedTask.snapshot;

  return (
    <Stack spacing={3} className="helper-page-enter">
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ justifyContent: "space-between" }}>
        <div>
          <div className="helper-kicker helper-kicker--red">EMS HANDOFF · 現場交接</div>
          <Typography component="h1" variant="h3">一頁掌握現場狀況</Typography>
        </div>
        <Chip
          icon={<Clock3 size={16} />}
          label={stale ? "資料可能已過時" : "快照 r12 · 20 秒前"}
          color={stale ? "warning" : "success"}
          variant="outlined"
        />
      </Stack>

      {stale ? (
        <StatusBanner title="超過 2 分鐘未收到更新" severity="warning">
          請向現場人員口頭確認患者狀況與已完成處置，不要只依賴本頁資料。
        </StatusBanner>
      ) : null}

      <Card className="snapshot-card">
        <CardContent>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <MapPin size={22} />
            <Typography component="h2" variant="h5">現場快照</Typography>
          </Stack>
          <div className="handoff-snapshot-grid">
            <div><Typography variant="overline">位置</Typography><Typography>{snapshot.location}</Typography></div>
            <div><Typography variant="overline">現場狀況</Typography><Typography>{snapshot.situation}</Typography></div>
            <div><Typography variant="overline">已做處置</Typography><Typography>{snapshot.treatment}</Typography></div>
            <div><Typography variant="overline">入口資訊</Typography><Typography>{snapshot.entrance}</Typography></div>
          </div>
        </CardContent>
      </Card>

      <StatusBanner title="系統整理草稿" severity="warning">
        問號代表尚未確認；建議動作不會被列為已完成處置。到場後仍須自行評估。
      </StatusBanner>

      <Card>
        <CardContent>
          <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 1 }}>
            <Typography component="h2" variant="h5">MIST</Typography>
            <Typography variant="caption" color="text.secondary">確認狀態同步顯示</Typography>
          </Stack>
          <Stack divider={<Divider flexItem />}>
            {demoMist.map((item) => (
              <div className="mist-row" key={item.letter}>
                <span className="mist-letter">{item.letter}</span>
                <div>
                  <Stack direction="row" spacing={0.75} sx={{ alignItems: "center" }}>
                    <Typography variant="overline">{item.label}</Typography>
                    {item.confirmed ? <Check size={16} aria-label="已確認" /> : <CircleHelp size={16} aria-label="未確認" />}
                  </Stack>
                  <Typography>{item.value}</Typography>
                </div>
              </div>
            ))}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography component="h2" variant="h5">完整時間軸</Typography>
          <ol className="handoff-timeline">
            {demoTimeline.map((event) => (
              <li key={event.id}>
                <time dateTime={event.occurredAt}>{formatTime(event.occurredAt)}</time>
                <span>{event.label}<small>{event.confirmation === "confirmed" ? "已確認" : "現場回報"}</small></span>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      <Card variant="outlined" className="demo-switches">
        <CardContent>
          <Typography variant="overline">Demo controls</Typography>
          <Button size="small" startIcon={<RefreshCw size={16} />} onClick={() => setStale((value) => !value)} sx={{ ml: 1 }}>
            {stale ? "模擬收到更新" : "模擬資料過時"}
          </Button>
        </CardContent>
      </Card>

      <Typography variant="caption" color="text.secondary">Demo incident: {incidentId}</Typography>
    </Stack>
  );
}
