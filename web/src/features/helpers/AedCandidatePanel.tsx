import { Alert, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { Clock3, Database, Footprints, Route, TriangleAlert } from "lucide-react";

import type { AedListResponse } from "../../types/api";
import { aedEstimate, formatSyncTime, isTimestampStale } from "./helperPresentation";

const availabilityCopy = {
  available: { label: "目前可用", color: "success" as const },
  unavailable: { label: "目前不可用", color: "error" as const },
  unknown: { label: "開放狀態待確認", color: "warning" as const },
};

export function AedCandidatePanel({ data, now }: { data?: AedListResponse; now: number }) {
  const dataStale = isTimestampStale(data?.dataUpdatedAt, now, 24 * 60 * 60 * 1_000);

  if (!data?.candidates.length) {
    return (
      <Card className="destination-card">
        <CardContent>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Route size={22} />
            <Typography component="h2" variant="h5">AED 資料</Typography>
          </Stack>
          <Alert severity="warning" variant="outlined" sx={{ mt: 2 }}>
            <strong>目前沒有可用的 AED 候選資料。</strong><br />
            請依現場指派者提供的位置行動；系統不會用 Demo 地點代替正式資料。
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="destination-card">
      <CardContent>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ justifyContent: "space-between", alignItems: { sm: "center" } }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Route size={22} />
            <Typography component="h2" variant="h5">AED 候選位置</Typography>
          </Stack>
          {data.dataUpdatedAt ? (
            <Chip
              size="small"
              color={dataStale ? "warning" : "default"}
              icon={<Database size={15} />}
              label={`資料 ${formatSyncTime(data.dataUpdatedAt)}`}
            />
          ) : <Chip size="small" color="warning" label="資料時間未知" />}
        </Stack>

        {dataStale ? <Alert severity="warning" sx={{ mt: 2 }}>AED 目錄已超過 24 小時未更新，出發前請再次確認。</Alert> : null}

        <Stack spacing={1.5} sx={{ mt: 2 }}>
          {data.candidates.map((candidate, index) => {
            const estimate = aedEstimate(candidate, now);
            const availability = availabilityCopy[candidate.availability];
            return (
              <Card key={candidate.aedId} variant="outlined" sx={{ boxShadow: "none", bgcolor: index === 0 ? "#f5f9ff" : "background.paper" }}>
                <CardContent sx={{ "&:last-child": { pb: 2.5 } }}>
                  <Stack direction="row" spacing={1.5} sx={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <Typography variant="overline" color="secondary.main">候選 {index + 1}</Typography>
                      <Typography component="h3" variant="h6" sx={{ fontWeight: 850 }}>{candidate.name}</Typography>
                      <Typography color="text.secondary" sx={{ mt: .5 }}>{candidate.address}</Typography>
                      {candidate.accessNotes ? <Typography variant="body2" sx={{ mt: .5 }}>放置位置：{candidate.accessNotes}</Typography> : null}
                    </div>
                    <Chip size="small" color={availability.color} label={availability.label} />
                  </Stack>

                  <Stack direction="row" sx={{ mt: 2, flexWrap: "wrap", gap: 1 }}>
                    <Chip icon={<Footprints size={16} />} label={estimate.distanceLabel} variant="outlined" />
                    {estimate.etaLabel ? <Chip icon={<Clock3 size={16} />} label={`約 ${estimate.etaLabel}`} variant="outlined" /> : null}
                    <Chip label={estimate.sourceLabel} variant="outlined" />
                  </Stack>

                  {estimate.stale ? (
                    <Stack direction="row" spacing={.75} sx={{ mt: 1.5, alignItems: "center", color: "warning.dark" }}>
                      <TriangleAlert size={17} />
                      <Typography variant="caption">路線估算已超過兩分鐘，時間可能不準確。</Typography>
                    </Stack>
                  ) : candidate.routeUpdatedAt ? (
                    <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1.5 }}>
                      路線更新於 {formatSyncTime(candidate.routeUpdatedAt)}
                    </Typography>
                  ) : null}
                </CardContent>
              </Card>
            );
          })}
        </Stack>
      </CardContent>
    </Card>
  );
}
