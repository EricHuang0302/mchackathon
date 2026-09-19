import { useState } from "react";
import { Alert, Button, Card, CardContent, CircularProgress, Stack, Typography } from "@mui/material";
import { useNavigate, useParams } from "react-router";

import { StatusBanner } from "../../components/ui/StatusBanner";
import { routes } from "../../app/routes";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import { getOrCreateSession, saveParticipantGrant } from "../../lib/connection/session";

export function JoinPage() {
  const { inviteId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const secret = window.location.hash.slice(1);

  const acceptTask = async () => {
    if (!secret) { setError("邀請連結缺少授權密鑰，無法存取事故資料。"); return; }
    setLoading(true); setError(null);
    try {
      history.replaceState(null, "", window.location.pathname + window.location.search);
      const session = await getOrCreateSession("participant");
      const grant = await new ApiClient(session.sessionToken).redeemShare(secret);
      saveParticipantGrant(grant);
      const demoQuery = new URLSearchParams(window.location.search).get("demo") === "1" ? "?demo=1" : "";
      if (grant.scope === "ems_viewer") navigate(routes.handoff(grant.incidentId) + demoQuery);
      else navigate(routes.helperTask(grant.incidentId, grant.helperId!) + demoQuery);
    } catch (reason) { setError(userMessageForApiError(reason)); setLoading(false); }
  };

  return (
    <Stack spacing={3}>
      <div>
        <Typography component="p" variant="overline" color="secondary">
          Invitation / {inviteId}
        </Typography>
        <Typography component="h1" variant="h3">
          現場需要你協助取 AED
        </Typography>
      </div>
      <Card>
        <CardContent>
          <Typography component="h2" variant="h5">
            任務內容
          </Typography>
          <Typography sx={{ mt: 1.5 }} color="text.secondary">
            前往光復校區警衛室取得 AED，再送回事故現場。接受後才會要求位置權限。
          </Typography>
        </CardContent>
      </Card>
      <StatusBanner title="限時授權" severity="warning">
        接受後會以獨立本機 session 兌換此邀請；密鑰不會寫入查詢參數或紀錄。
      </StatusBanner>
      {error && <Alert severity="error">{error}</Alert>}
      <Button variant="contained" color="secondary" size="large" onClick={acceptTask} disabled={loading || !secret}>
        {loading ? <CircularProgress size={24} /> : "接受任務"}
      </Button>
      <Button variant="outlined" size="large">
        我無法協助
      </Button>
    </Stack>
  );
}
