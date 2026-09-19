import { useState } from "react";
import { Button, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { CheckCircle2, Clock3, MapPin, ShieldCheck } from "lucide-react";
import { useNavigate, useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { routes } from "../../app/routes";

export function JoinPage() {
  const { inviteId } = useParams();
  const navigate = useNavigate();
  const [declined, setDeclined] = useState(false);
  const isExpired = inviteId === "expired";
  const isInvalid = !inviteId || inviteId === "invalid";

  const acceptDemoTask = () => {
    navigate(routes.helperTask("demo-incident", "demo-helper"));
  };

  if (isExpired || isInvalid || declined) {
    return (
      <Stack spacing={3} className="helper-page-enter">
        <div className="helper-kicker">協助連結</div>
        <Typography component="h1" variant="h3">
          {declined ? "已回報無法協助" : isExpired ? "這個任務已過期" : "連結無效"}
        </Typography>
        <StatusBanner title={declined ? "已通知現場重新派遣" : "無法加入任務"} severity="warning">
          {declined
            ? "謝謝你的回覆，系統會尋找其他協助者。"
            : "任務可能已結束或連結不完整，請向現場人員確認最新 QR code。"}
        </StatusBanner>
        <Button variant="outlined" onClick={() => navigate(routes.home)}>
          回到首頁
        </Button>
      </Stack>
    );
  }

  return (
    <Stack spacing={3}>
      <div className="helper-page-enter">
        <div className="helper-kicker">任務邀請 · AED 取件</div>
        <Typography component="h1" variant="h3">
          現場需要你協助取 AED
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>
          任務代碼 {inviteId}
        </Typography>
      </div>
      <Card className="mission-card helper-page-enter">
        <CardContent>
          <Chip label="約 8 分鐘" color="secondary" size="small" />
          <Typography component="h2" variant="h5" sx={{ mt: 2 }}>
            到警衛室取 AED，再送往中正堂
          </Typography>
          <Stack className="mission-facts" spacing={1.5} sx={{ mt: 2.5 }}>
            <span><MapPin size={20} />距離約 320 公尺</span>
            <span><Clock3 size={20} />步行約 4 分鐘抵達 AED</span>
            <span><ShieldCheck size={20} />接受後才會要求位置權限</span>
          </Stack>
        </CardContent>
      </Card>
      <StatusBanner title="先確認自身安全" severity="warning">
        請勿奔跑、闖越車道或進入受管制區域；無法安全完成時請立即回報。
      </StatusBanner>
      <Button variant="contained" color="secondary" size="large" onClick={acceptDemoTask} startIcon={<CheckCircle2 />}>
        接受任務
      </Button>
      <Button variant="outlined" size="large" onClick={() => setDeclined(true)}>
        我無法協助
      </Button>
    </Stack>
  );
}
