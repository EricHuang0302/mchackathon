import { useLayoutEffect, useState } from "react";
import { Alert, Button, Card, CardContent, CircularProgress, Stack, Typography } from "@mui/material";
import { useNavigate, useParams } from "react-router";

import { routes } from "../../app/routes";
import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import { getOrCreateSession, saveParticipantGrant } from "../../lib/connection/session";
import { FAILURES, inviteFailureFor, parseInviteScope, taskForScope } from "./invitationCopy";
import type { InviteFailure } from "./invitationCopy";

export function JoinPage() {
  const { inviteId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secret] = useState(() => window.location.hash.slice(1));
  const [failure, setFailure] = useState<InviteFailure | null>(secret ? null : "permission_denied");
  const scope = parseInviteScope(window.location.search);
  const task = taskForScope(scope);

  useLayoutEffect(() => {
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }, []);

  const acceptTask = async () => {
    if (!secret) { setError("邀請連結缺少授權密鑰，無法存取事故資料。"); return; }
    setLoading(true); setError(null);
    try {
      const session = await getOrCreateSession("participant");
      const grant = await new ApiClient(session.sessionToken).redeemShare(secret);
      saveParticipantGrant(grant);
      const demoQuery = new URLSearchParams(window.location.search).get("demo") === "1" ? "?demo=1" : "";
      if (grant.scope === "ems_viewer") navigate(routes.handoff(grant.incidentId) + demoQuery);
      else navigate(routes.helperTask(grant.incidentId, grant.helperId!) + demoQuery);
    } catch (reason) {
      const inviteFailure = inviteFailureFor(reason);
      if (inviteFailure) setFailure(inviteFailure);
      else setError(userMessageForApiError(reason));
      setLoading(false);
    }
  };

  const decline = () => navigate(routes.home, { replace: true });

  if (failure) {
    const copy = FAILURES[failure];
    return <Stack spacing={3}>
      <Alert severity="error">
        <Typography component="h1" variant="h5">{copy.title}</Typography>
        <Typography sx={{ mt: 1 }}>{copy.description}</Typography>
      </Alert>
      <Button variant="contained" size="large" onClick={decline}>回到首頁</Button>
    </Stack>;
  }

  return <Stack spacing={3} className="helper-page-enter">
    <div>
      <Typography component="p" variant="overline" color="secondary">{task.overline} / {inviteId}</Typography>
      <Typography component="h1" variant="h3">{task.title}</Typography>
    </div>
    <Card className="mission-card"><CardContent>
      <Typography component="h2" variant="h5">任務內容</Typography>
      <Typography sx={{ mt: 1.5 }} color="text.secondary">{task.description}</Typography>
    </CardContent></Card>
    <StatusBanner title="先確認自身安全" severity="warning">
      請勿奔跑、闖越車道或進入受管制區域；接受後才會依任務需要要求位置權限。
    </StatusBanner>
    {error && <Alert severity="error">{error}</Alert>}
    <Button variant="contained" color="secondary" size="large" onClick={acceptTask} disabled={loading || !secret}>
      {loading ? <CircularProgress size={24} /> : "接受任務"}
    </Button>
    <Button variant="outlined" size="large" onClick={decline}>我無法協助</Button>
  </Stack>;
}
