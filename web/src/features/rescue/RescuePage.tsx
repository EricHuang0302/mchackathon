import { Button, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { routes } from "../../app/routes";

export function RescuePage() {
  return (
    <Stack spacing={3}>
      <section className="hero-panel">
        <Typography component="p" variant="overline" color="primary">
          Dispatcher first / Agent assists
        </Typography>
        <Typography component="h1" variant="h2">
          現場越混亂，介面越要簡單。
        </Typography>
        <Typography className="hero-copy">
          這是共用前端骨架。主要救援、協助者與救護交接都從同一個 React PWA 提供。
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ mt: 3 }}>
          <Button variant="contained" size="large" component={RouterLink} to={routes.callMode}>
            查看通話模式
          </Button>
          <Button variant="outlined" size="large" component={RouterLink} to="/demo/helper">
            模擬協助者掃碼
          </Button>
        </Stack>
      </section>

      <StatusBanner title="目前是開發骨架" severity="warning">
        所有事件、位置與交接內容都是合成示範資料，尚未連接 119、Firebase 或醫療系統。
      </StatusBanner>

      <div className="feature-grid">
        <Card>
          <CardContent>
            <Chip label="Workstream 2" size="small" />
            <Typography variant="h5" sx={{ mt: 2 }}>
              主要救援流程
            </Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              119 入口、報案小抄、快速紀錄與手動模式切換。
            </Typography>
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            <Chip label="Workstream 4" size="small" color="secondary" />
            <Typography variant="h5" sx={{ mt: 2 }}>
              協助者與交接
            </Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              QR 任務、AED 路線、進度回報、現場快照與 MIST。
            </Typography>
          </CardContent>
        </Card>
      </div>

      <Button component={RouterLink} to="/demo/handoff" variant="text">
        開啟救護交接示範頁
      </Button>
    </Stack>
  );
}
