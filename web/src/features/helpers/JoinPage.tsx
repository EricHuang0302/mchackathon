import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, CircularProgress, Stack, Typography } from "@mui/material";
import { CheckCircle2, Clock3, MapPin, ShieldCheck } from "lucide-react";
import { useNavigate, useParams } from "react-router";

import { routes } from "../../app/routes";
import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, userMessageForApiError } from "../../lib/connection/apiClient";
import {
  getOrCreateSession,
  saveParticipantGrant,
  saveParticipantTaskProgress,
} from "../../lib/connection/session";
import type { ShareScope, ShareSessionResponse } from "../../types/api";
import { InviteUnavailablePage } from "./InviteUnavailablePage";
import { inviteUnavailableReason, type InviteUnavailableReason } from "./helperPresentation";
import { demoInviteScope, readInviteSecret, readScopeHint } from "./shareLinks";

const inviteCopy: Record<ShareScope, { kicker: string; title: string; summary: string; facts: string[] }> = {
  aed_runner: {
    kicker: "任務邀請 · AED 取件",
    title: "現場需要你協助取得 AED",
    summary: "接受後將顯示 AED 資料與現場指示，並可回報取件進度。",
    facts: ["接受後才會要求位置權限", "無法取得時可立即回報", "完成任務後授權會失效"],
  },
  ambulance_greeter: {
    kicker: "任務邀請 · 救護車接應",
    title: "現場需要你協助接應救護車",
    summary: "前往指定入口等待救護車，再協助引導救護人員到患者位置。",
    facts: ["接受後才會要求位置權限", "可查看集合點與入口資訊", "只顯示完成任務所需資料"],
  },
  ems_viewer: {
    kicker: "限時邀請 · 救護交接",
    title: "查看這次救援的交接資訊",
    summary: "授權後可查看現場觀察資料與事件時間軸，連結只能兌換一次。",
    facts: ["不會取得協助者定位", "內容可能包含未確認資訊", "到場後仍須自行評估"],
  },
};

export function JoinPage() {
  const { inviteId } = useParams();
  const navigate = useNavigate();
  const demoScope = demoInviteScope(inviteId);
  const isDemo = demoScope !== null;
  const [secret] = useState(() => readInviteSecret(window.location.hash));
  const [scopeHint] = useState(() => demoScope ?? readScopeHint(window.location.search) ?? "aed_runner");
  const [loading, setLoading] = useState<"accept" | "decline" | null>(null);
  const [error, setError] = useState<string>();
  const [declined, setDeclined] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<InviteUnavailableReason | null>(
    !isDemo && !secret ? "missing_secret" : null,
  );
  const copy = useMemo(() => inviteCopy[scopeHint], [scopeHint]);

  useEffect(() => {
    if (!window.location.hash) return;
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }, []);

  const redeem = async (): Promise<ShareSessionResponse> => {
    if (!secret) throw new Error("missing-secret");
    const session = await getOrCreateSession("participant");
    const api = new ApiClient(session.sessionToken);
    const grant = await api.redeemShare(secret);
    saveParticipantGrant(grant);
    if (grant.helperId) {
      const progress = await api.updateHelper(grant.incidentId, grant.helperId, {
        updateId: crypto.randomUUID(),
        expectedAssignmentRevision: 0,
        status: "accepted",
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
      else navigate(routes.helperTask("demo-incident", demoScope === "ambulance_greeter" ? "demo-greeter" : "demo-helper"));
      return;
    }
    if (!secret) {
      setError("邀請連結缺少授權密鑰，請重新掃描現場提供的 QR Code。");
      return;
    }
    setLoading("accept");
    setError(undefined);
    try {
      const grant = await redeem();
      if (grant.scope === "ems_viewer") navigate(routes.handoff(grant.incidentId));
      else navigate(routes.helperTask(grant.incidentId, grant.helperId!));
    } catch (reason) {
      const unavailable = inviteUnavailableReason(reason);
      if (unavailable) {
        setUnavailableReason(unavailable);
        setLoading(null);
        return;
      }
      setError(reason instanceof Error && reason.message === "missing-secret"
        ? "邀請連結缺少授權密鑰。"
        : userMessageForApiError(reason));
      setLoading(null);
    }
  };

  const declineTask = async () => {
    if (isDemo || !secret) {
      setDeclined(true);
      return;
    }
    setLoading("decline");
    setError(undefined);
    try {
      const grant = await redeem();
      if (grant.helperId) {
        const session = await getOrCreateSession("participant");
        const progress = await new ApiClient(session.sessionToken).updateHelper(grant.incidentId, grant.helperId, {
          updateId: crypto.randomUUID(),
          expectedAssignmentRevision: 1,
          status: "unavailable",
          reportedAt: new Date().toISOString(),
        });
        saveParticipantTaskProgress({
          incidentId: grant.incidentId,
          helperId: grant.helperId,
          assignmentRevision: progress.assignmentRevision,
          status: progress.status,
        });
      }
      setDeclined(true);
    } catch (reason) {
      const unavailable = inviteUnavailableReason(reason);
      if (unavailable) {
        setUnavailableReason(unavailable);
        setLoading(null);
        return;
      }
      setError(userMessageForApiError(reason));
    } finally {
      setLoading(null);
    }
  };

  if (unavailableReason) return <InviteUnavailablePage reason={unavailableReason} />;

  if (declined) {
    return (
      <Stack spacing={3} className="helper-page-enter">
        <div className="helper-kicker">協助邀請</div>
        <Typography component="h1" variant="h3">已回報無法協助</Typography>
        <StatusBanner title="現場已收到狀態" severity="warning">
          謝謝你的回覆。現場可以改請其他協助者，不需要繼續開啟此連結。
        </StatusBanner>
        <Button variant="outlined" onClick={() => navigate(routes.home)}>回到首頁</Button>
      </Stack>
    );
  }

  return (
    <Stack spacing={3} className="helper-page-enter">
      <div>
        <div className={`helper-kicker${scopeHint === "ems_viewer" ? " helper-kicker--red" : ""}`}>{copy.kicker}</div>
        <Typography component="h1" variant="h3">{copy.title}</Typography>
        <Typography color="text.secondary" sx={{ mt: 1 }}>邀請代碼 {inviteId}</Typography>
      </div>

      <Card className="mission-card">
        <CardContent>
          <Chip label={isDemo ? "Demo 任務" : "五分鐘限時邀請"} color="secondary" size="small" />
          <Typography component="h2" variant="h5" sx={{ mt: 2 }}>{copy.summary}</Typography>
          <Stack className="mission-facts" spacing={1.5} sx={{ mt: 2.5 }}>
            <span><MapPin size={20} />{copy.facts[0]}</span>
            <span><Clock3 size={20} />{copy.facts[1]}</span>
            <span><ShieldCheck size={20} />{copy.facts[2]}</span>
          </Stack>
        </CardContent>
      </Card>

      <StatusBanner title="先確認自身安全" severity="warning">
        請勿奔跑、闖越車道或進入受管制區域；緊急情況以 119 派遣員指示為準。
      </StatusBanner>
      {error ? <Alert severity="error">{error}</Alert> : null}
      <Button
        variant="contained"
        color="secondary"
        size="large"
        onClick={acceptTask}
        disabled={loading !== null || (!isDemo && !secret)}
        startIcon={loading === "accept" ? <CircularProgress size={22} color="inherit" /> : <CheckCircle2 />}
      >
        {loading === "accept" ? "正在驗證邀請…" : "接受任務"}
      </Button>
      <Button variant="outlined" size="large" onClick={declineTask} disabled={loading !== null}>
        {loading === "decline" ? "正在回報…" : "我無法協助"}
      </Button>
    </Stack>
  );
}
