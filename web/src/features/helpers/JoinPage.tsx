import { useLayoutEffect, useState } from "react";
import { Alert, Button, Card, CardContent, CircularProgress, Stack, Typography } from "@mui/material";
import { useNavigate, useParams } from "react-router";

import { routes } from "../../app/routes";
import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import {
  getOrCreateSession,
  saveParticipantGrant,
  saveParticipantTaskProgress,
} from "../../lib/connection/session";
import type { ShareSessionResponse } from "../../types/api";
import { FAILURES, inviteFailureFor, parseInviteScope, taskForScope } from "./invitationCopy";
import type { InviteFailure } from "./invitationCopy";
import { demoInviteScope, readInviteSecret } from "./shareLinks";

export function JoinPage() {
  const { inviteId } = useParams();
  const navigate = useNavigate();
  const demoScope = demoInviteScope(inviteId);
  const isDemo = demoScope !== null;
  const [loading, setLoading] = useState<"accept" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [declined, setDeclined] = useState(false);
  const [secret] = useState(() => readInviteSecret(window.location.hash));
  const [failure, setFailure] = useState<InviteFailure | null>(
    !isDemo && !secret ? "permission_denied" : null,
  );
  const scope = demoScope ?? parseInviteScope(window.location.search);
  const task = taskForScope(scope);

  useLayoutEffect(() => {
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }, []);

  const redeem = async (
    status: "accepted" | "unavailable",
  ): Promise<ShareSessionResponse> => {
    if (!secret) throw new Error("missing-secret");
    const session = await getOrCreateSession("participant");
    const api = new ApiClient(session.sessionToken);
    const grant = await api.redeemShare(secret);
    saveParticipantGrant(grant);
    if (grant.helperId) {
      const progress = await api.updateHelper(grant.incidentId, grant.helperId, {
        updateId: crypto.randomUUID(),
        expectedAssignmentRevision: 0,
        status,
        reportedAt: new Date().toISOString(),
      });
      saveParticipantTaskProgress({
        incidentId: grant.incidentId,
        helperId: grant.helperId,
        assignmentRevision: progress.assignmentRevision,
        status: progress.status,
      });
    }
    return grant;
  };

  const acceptTask = async () => {
    if (isDemo) {
      if (demoScope === "ems_viewer") navigate(routes.handoff("demo-incident"));
      else navigate(routes.helperTask(
        "demo-incident",
        demoScope === "ambulance_greeter" ? "demo-greeter" : "demo-helper",
      ));
      return;
    }
    setLoading("accept");
    setError(null);
    try {
      const grant = await redeem("accepted");
      if (grant.scope === "ems_viewer") navigate(routes.handoff(grant.incidentId));
      else navigate(routes.helperTask(grant.incidentId, grant.helperId!));
    } catch (reason) {
      const inviteFailure = inviteFailureFor(reason);
      if (inviteFailure) setFailure(inviteFailure);
      else setError(userMessageForApiError(reason));
      setLoading(null);
    }
  };

  const declineTask = async () => {
    if (isDemo || !secret) {
      setDeclined(true);
      return;
    }
    setLoading("decline");
    setError(null);
    try {
      await redeem("unavailable");
      setDeclined(true);
    } catch (reason) {
      const inviteFailure = inviteFailureFor(reason);
      if (inviteFailure) setFailure(inviteFailure);
      else setError(userMessageForApiError(reason));
    } finally {
      setLoading(null);
    }
  };

  const returnHome = () => navigate(routes.home, { replace: true });

  if (failure) {
    const copy = FAILURES[failure];
    return <Stack spacing={3}>
      <Alert severity="error">
        <Typography component="h1" variant="h5">{copy.title}</Typography>
        <Typography sx={{ mt: 1 }}>{copy.description}</Typography>
      </Alert>
      <Button variant="contained" size="large" onClick={returnHome}>回到首頁</Button>
    </Stack>;
  }

  if (declined) {
    return <Stack spacing={3} className="helper-page-enter">
      <Typography component="h1" variant="h3">已回報無法協助</Typography>
      <StatusBanner title="現場已收到狀態" severity="warning">
        謝謝你的回覆。現場可以改請其他協助者，不需要繼續開啟此連結。
      </StatusBanner>
      <Button variant="outlined" onClick={returnHome}>回到首頁</Button>
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
    <Button
      variant="contained"
      color="secondary"
      size="large"
      onClick={acceptTask}
      disabled={loading !== null || (!isDemo && !secret)}
    >
      {loading === "accept" ? <CircularProgress size={24} /> : "接受任務"}
    </Button>
    <Button variant="outlined" size="large" onClick={declineTask} disabled={loading !== null}>
      {loading === "decline" ? "正在回報…" : "我無法協助"}
    </Button>
  </Stack>;
}
