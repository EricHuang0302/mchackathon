import { Button, Card, CardContent, Stack, Typography } from "@mui/material";
import { ClockAlert, QrCode, ShieldX } from "lucide-react";
import { Link as RouterLink } from "react-router";

import { routes } from "../../app/routes";
import type { InviteUnavailableReason } from "./helperPresentation";

const copy = {
  expired_or_used: {
    eyebrow: "邀請已失效",
    title: "這個 QR Code 已過期或使用過",
    body: "任務邀請只能兌換一次，並會在五分鐘後自動失效。請回到現場，請邀請者重新產生 QR Code。",
    icon: ClockAlert,
  },
  missing_secret: {
    eyebrow: "連結不完整",
    title: "找不到邀請授權資訊",
    body: "可能是連結被截斷，或網址片段沒有完整傳送。請直接重新掃描現場顯示的 QR Code。",
    icon: ShieldX,
  },
} satisfies Record<InviteUnavailableReason, { eyebrow: string; title: string; body: string; icon: typeof ClockAlert }>;

export function InviteUnavailablePage({ reason }: { reason: InviteUnavailableReason }) {
  const state = copy[reason];
  const Icon = state.icon;

  return (
    <Stack spacing={3} className="helper-page-enter" sx={{ maxWidth: 560, mx: "auto", py: { xs: 2, sm: 6 } }}>
      <Card sx={{ overflow: "hidden", borderTop: "6px solid", borderTopColor: "warning.main" }}>
        <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
          <Stack spacing={2.5} sx={{ alignItems: "flex-start" }}>
            <Stack
              sx={{
                width: 64,
                height: 64,
                borderRadius: "18px",
                alignItems: "center",
                justifyContent: "center",
                color: "warning.dark",
                bgcolor: "#fff3e0",
              }}
            >
              <Icon size={34} strokeWidth={2.2} />
            </Stack>
            <div>
              <Typography variant="overline" color="warning.dark">{state.eyebrow}</Typography>
              <Typography component="h1" variant="h3" sx={{ mt: .5 }}>{state.title}</Typography>
            </div>
            <Typography color="text.secondary" sx={{ fontSize: "1.05rem", lineHeight: 1.8 }}>{state.body}</Typography>
          </Stack>
        </CardContent>
      </Card>

      <Stack spacing={1.25}>
        <Button component={RouterLink} to={routes.home} variant="contained" size="large" startIcon={<QrCode size={20} />}>
          回到救援首頁
        </Button>
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: "center" }}>
          請勿請他人轉傳已失效的網址；新的邀請會產生不同授權。
        </Typography>
      </Stack>
    </Stack>
  );
}
