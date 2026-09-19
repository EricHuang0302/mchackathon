import { Button, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { useParams } from "react-router";

import { MapPlaceholder } from "../../components/maps/MapPlaceholder";
import { StatusBanner } from "../../components/ui/StatusBanner";

export function HelperTaskPage() {
  const { helperId, incidentId } = useParams();

  return (
    <Stack spacing={3}>
      <Stack
        direction="row"
        spacing={2}
        sx={{ alignItems: "flex-start", justifyContent: "space-between" }}
      >
        <div>
          <Typography component="p" variant="overline" color="secondary">
            AED runner
          </Typography>
          <Typography component="h1" variant="h3">
            前往警衛室取得 AED
          </Typography>
        </div>
        <Chip label="路程中" color="secondary" />
      </Stack>

      <MapPlaceholder destination="光復校區警衛室" />

      <Card>
        <CardContent>
          <Typography component="h2" variant="h5">
            光復校區警衛室
          </Typography>
          <Typography sx={{ mt: 1 }}>約 320 公尺 · 步行估計 4 分鐘</Typography>
          <Typography color="text.secondary" sx={{ mt: 0.5 }}>
            入口說明：面向大學路，進門後詢問值班人員。
          </Typography>
        </CardContent>
      </Card>

      <StatusBanner title="位置資料為示範內容">最後更新：剛剛 · 精確度：未提供</StatusBanner>

      <Stack spacing={1.5}>
        <Button variant="contained" color="secondary" size="large">
          我已抵達 AED 位置
        </Button>
        <Button variant="outlined" color="error" size="large">
          無法取得 AED
        </Button>
      </Stack>

      <Typography variant="caption" color="text.secondary">
        Demo IDs: incident={incidentId}, helper={helperId}
      </Typography>
    </Stack>
  );
}
