import { Button, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router";

export function NotFoundPage() {
  return (
    <Stack spacing={3} className="content-panel">
      <Typography component="p" variant="overline">
        404 / Route not found
      </Typography>
      <Typography component="h1" variant="h3">
        找不到這個頁面
      </Typography>
      <Typography color="text.secondary">
        連結可能已失效，或目前前端尚未建立這條流程。
      </Typography>
      <Button component={RouterLink} to="/" variant="contained" size="large">
        回到救援首頁
      </Button>
    </Stack>
  );
}
