import { Button, Card, CardContent, Stack, Typography } from "@mui/material";

import { StatusBanner } from "../../components/ui/StatusBanner";

export function CallModePage() {
  return (
    <Stack spacing={3}>
      <div>
        <Typography component="p" variant="overline" color="primary">
          On call
        </Typography>
        <Typography component="h1" variant="h3">
          正在與 119 通話
        </Typography>
      </div>
      <StatusBanner title="Agent 已保持安靜" severity="success">
        前端必須停止語音播放、清空待播內容，並停止麥克風上傳。
      </StatusBanner>
      <Card>
        <CardContent>
          <Typography component="h2" variant="h5">
            報案小抄
          </Typography>
          <Typography sx={{ mt: 2 }}>位置：尚未確認</Typography>
          <Typography>發生經過：尚未確認</Typography>
          <Typography>患者狀態：尚未確認</Typography>
        </CardContent>
      </Card>
      <Button variant="contained" size="large">
        通話結束，恢復指引
      </Button>
    </Stack>
  );
}
