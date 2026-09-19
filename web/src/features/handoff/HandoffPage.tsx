import { Card, CardContent, Chip, Divider, Stack, Typography } from "@mui/material";
import { useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";

const mistRows = [
  ["M", "主要狀況", "校園內有人突然倒地；原因未確認"],
  ["I", "傷勢", "未觀察到明顯外傷"],
  ["S", "徵象", "意識與呼吸狀態尚未確認"],
  ["T", "已做處置", "有人前往取得 AED"],
] as const;

export function HandoffPage() {
  const { incidentId } = useParams();

  return (
    <Stack spacing={3}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={2}
        sx={{ justifyContent: "space-between" }}
      >
        <div>
          <Typography component="p" variant="overline" color="primary">
            EMS handoff
          </Typography>
          <Typography component="h1" variant="h3">
            現場交接
          </Typography>
        </div>
        <Chip label="快照 r12 · 20 秒前" color="success" variant="outlined" />
      </Stack>

      <Card className="snapshot-card">
        <CardContent>
          <Typography component="h2" variant="h5">
            現場快照
          </Typography>
          <div className="handoff-snapshot-grid">
            <div>
              <Typography variant="overline">位置</Typography>
              <Typography>成功大學光復校區，中正堂東側入口</Typography>
            </div>
            <div>
              <Typography variant="overline">現場狀況</Typography>
              <Typography>1 名患者倒地；周圍目前無回報危險</Typography>
            </div>
            <div>
              <Typography variant="overline">已做處置</Typography>
              <Typography>已通報 119；AED 取件中</Typography>
            </div>
            <div>
              <Typography variant="overline">入口資訊</Typography>
              <Typography>由大學路入口進入，有人於路口接應</Typography>
            </div>
          </div>
        </CardContent>
      </Card>

      <StatusBanner title="系統整理草稿" severity="warning">
        未確認欄位維持未知；建議動作不會顯示成已完成處置。
      </StatusBanner>

      <Card>
        <CardContent>
          <Typography variant="h5" sx={{ mb: 2 }}>
            MIST
          </Typography>
          <Stack divider={<Divider flexItem />}>
            {mistRows.map(([letter, label, value]) => (
              <div className="mist-row" key={letter}>
                <span className="mist-letter">{letter}</span>
                <div>
                  <Typography variant="overline">{label}</Typography>
                  <Typography>{value}</Typography>
                </div>
              </div>
            ))}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography component="h2" variant="h5">
            時間軸
          </Typography>
          <ol className="handoff-timeline">
            <li>
              <time>14:02</time>
              <span>事件建立，位置等待確認</span>
            </li>
            <li>
              <time>14:03</time>
              <span>使用者回報已撥打 119</span>
            </li>
            <li>
              <time>14:04</time>
              <span>AED 取件任務已接受</span>
            </li>
          </ol>
        </CardContent>
      </Card>

      <Typography variant="caption" color="text.secondary">
        Demo incident: {incidentId}
      </Typography>
    </Stack>
  );
}
