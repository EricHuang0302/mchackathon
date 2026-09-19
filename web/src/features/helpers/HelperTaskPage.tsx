import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, CardContent, Chip, CircularProgress, LinearProgress, Stack, Typography } from "@mui/material";
import { CheckCircle2, MapPin, Radio } from "lucide-react";
import { useParams } from "react-router";

import { TaskMap } from "../../components/maps/TaskMap";
import { StatusBanner } from "../../components/ui/StatusBanner";
import { ApiClient, ApiClientError, userMessageForApiError } from "../../lib/connection/apiClient";
import {
  getOrCreateSession,
  getParticipantGrant,
  getParticipantTaskProgress,
  saveParticipantTaskProgress,
} from "../../lib/connection/session";
import type { AedAssignmentReadResponse, AedAssignmentResponse, AedListResponse, SceneSnapshotResponse } from "../../types/api";
import type { Coordinates } from "../../types/domain";
import { AedCandidatePanel } from "./AedCandidatePanel";
import { DemoHelperTask } from "./DemoHelperTask";
import { formatSyncTime, isTimestampStale } from "./helperPresentation";
import { useLocationSharing } from "./useLocationSharing";
import { CanonicalSnapshotCard } from "../rescue/CanonicalSnapshotCard";

type ApiHelperStatus = "accepted" | "en_route" | "arrived" | "obtained" | "delivered" | "unavailable";

const statusLabels: Record<ApiHelperStatus, string> = {
  accepted: "已接受",
  en_route: "前往目的地",
  arrived: "已抵達",
  obtained: "已取得 AED",
  delivered: "已送達現場",
  unavailable: "無法完成",
};

const progressValues: Record<ApiHelperStatus, number> = {
  accepted: 15,
  en_route: 40,
  arrived: 70,
  obtained: 100,
  delivered: 100,
  unavailable: 100,
};

function distanceMeters(a: Coordinates, b: Coordinates) {
  const toRadians = (value: number) => value * Math.PI / 180;
  const earthRadius = 6_371_000;
  const dLat = toRadians(b.lat - a.lat);
  const dLng = toRadians(b.lng - a.lng);
  const lat1 = toRadians(a.lat);
  const lat2 = toRadians(b.lat);
  const value = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

export function HelperTaskPage() {
  const { helperId = "", incidentId = "" } = useParams();
  const isDemo = incidentId === "demo-incident";
  if (isDemo) return <DemoHelperTask helperId={helperId} incidentId={incidentId} />;
  return <ConnectedHelperTask helperId={helperId} incidentId={incidentId} />;
}

function ConnectedHelperTask({ helperId, incidentId }: { helperId: string; incidentId: string }) {
  const [grant] = useState(getParticipantGrant);
  const [storedProgress] = useState(getParticipantTaskProgress);
  const initialRevision = storedProgress?.incidentId === incidentId && storedProgress.helperId === helperId
    ? storedProgress.assignmentRevision : 0;
  const initialStatus = storedProgress?.incidentId === incidentId && storedProgress.helperId === helperId
    ? storedProgress.status as ApiHelperStatus : "accepted";
  const [revision, setRevision] = useState(initialRevision);
  const revisionRef = useRef(initialRevision);
  const [status, setStatus] = useState<ApiHelperStatus>(initialStatus);
  const [aeds, setAeds] = useState<AedListResponse>();
  const [assignment, setAssignment] = useState<AedAssignmentReadResponse>();
  const [assignmentOutcome, setAssignmentOutcome] = useState<AedAssignmentResponse["outcome"]>();
  const [snapshot, setSnapshot] = useState<SceneSnapshotResponse>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [lastLocationUpdatedAt, setLastLocationUpdatedAt] = useState<string>();
  const [clock, setClock] = useState(() => Date.now());
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  const lastLocation = useRef<Coordinates | undefined>(undefined);
  const location = useLocationSharing();
  const validGrant = grant?.incidentId === incidentId && grant.helperId === helperId && grant.scope !== "ems_viewer";
  const isGreeter = grant?.scope === "ambulance_greeter";

  const updateHelper = useCallback((payload: { status?: ApiHelperStatus; position?: Coordinates }) => {
    const operation = queueRef.current.then(async () => {
      if (!validGrant) throw new Error("missing-grant");
      const session = await getOrCreateSession("participant");
      const result = await new ApiClient(session.sessionToken).updateHelper(incidentId, helperId, {
        updateId: crypto.randomUUID(),
        expectedAssignmentRevision: revisionRef.current,
        status: payload.status,
        lat: payload.position?.lat,
        lng: payload.position?.lng,
        locationAccuracyMeters: payload.position?.accuracyMeters,
        reportedAt: payload.position?.observedAt ?? new Date().toISOString(),
      });
      revisionRef.current = result.assignmentRevision;
      setRevision(result.assignmentRevision);
      setStatus(result.status as ApiHelperStatus);
      if (result.locationUpdatedAt) setLastLocationUpdatedAt(result.locationUpdatedAt);
      saveParticipantTaskProgress({
        incidentId,
        helperId,
        assignmentRevision: result.assignmentRevision,
        status: result.status,
      });
    });
    queueRef.current = operation.then(() => undefined, () => undefined);
    return operation;
  }, [helperId, incidentId, validGrant]);

  const refreshAssignment = useCallback(async () => {
    const session = await getOrCreateSession("participant");
    const api = new ApiClient(session.sessionToken);
    try {
      const current = await api.getAedAssignment(incidentId, helperId);
      setAssignment(current);
      setAeds(current.destination
        ? { candidates: [current.destination], dataUpdatedAt: current.assignedAt }
        : { candidates: [], dataUpdatedAt: current.assignedAt });
      setError(undefined);
    } catch (reason) {
      if (reason instanceof ApiClientError && reason.status === 404) {
        setAssignment(undefined);
        setAeds((current) => current ?? { candidates: [], dataUpdatedAt: null });
        setError(undefined);
        return;
      }
      throw reason;
    }
  }, [helperId, incidentId]);

  useEffect(() => {
    if (!lastLocationUpdatedAt) return;
    const timer = window.setInterval(() => setClock(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [lastLocationUpdatedAt]);

  useEffect(() => {
    let active = true;
    void (async () => {
      if (!validGrant) {
        setError("找不到這次任務的有效授權，請重新掃描現場提供的 QR Code。");
        setLoading(false);
        return;
      }
      try {
        const session = await getOrCreateSession("participant");
        const api = new ApiClient(session.sessionToken);
        if (isGreeter) {
          setSnapshot(await api.getSnapshot(incidentId));
        } else {
          await refreshAssignment();
        }
      } catch (reason) {
        if (active) setError(userMessageForApiError(reason));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, [incidentId, isGreeter, refreshAssignment, validGrant]);

  useEffect(() => {
    if (!validGrant || isGreeter || status === "delivered" || status === "unavailable") return;
    const timer = window.setInterval(() => {
      void refreshAssignment().catch((reason) => setError(userMessageForApiError(reason)));
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [isGreeter, refreshAssignment, status, validGrant]);

  useEffect(() => {
    const position = location.position;
    if (!position || !validGrant) return;
    const previous = lastLocation.current;
    const oldEnough = !previous?.observedAt || Date.now() - new Date(previous.observedAt).getTime() >= 10_000;
    const movedEnough = !previous || distanceMeters(previous, position) >= 20;
    if (!oldEnough && !movedEnough) return;
    lastLocation.current = position;
    void updateHelper({ position }).catch((reason) => setError(userMessageForApiError(reason)));
  }, [location.position, updateHelper, validGrant]);

  useEffect(() => {
    const position = location.position;
    if (!position || !validGrant || isGreeter || assignment) return;
    let active = true;
    void (async () => {
      try {
        const session = await getOrCreateSession("participant");
        const nearby = await new ApiClient(session.sessionToken).getAeds(incidentId, 5, {
          lat: position.lat,
          lng: position.lng,
        });
        if (active) {
          setAeds(nearby);
          setError(undefined);
        }
      } catch (reason) {
        if (active) setError(userMessageForApiError(reason));
      }
    })();
    return () => { active = false; };
  }, [assignment, incidentId, isGreeter, location.position, validGrant]);

  const report = async (nextStatus: ApiHelperStatus) => {
    setBusy(true);
    setError(undefined);
    try {
      await updateHelper({ status: nextStatus, position: location.position });
    } catch (reason) {
      setError(reason instanceof Error && reason.message === "missing-grant"
        ? "任務授權不存在，請重新掃描 QR Code。"
        : userMessageForApiError(reason));
    } finally {
      setBusy(false);
    }
  };

  const reportUnavailable = async () => {
    if (!assignment?.aedId) {
      setError("目前沒有可回報無法取得的 AED 指派。");
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const session = await getOrCreateSession("participant");
      const api = new ApiClient(session.sessionToken);
      const result = await api.reportAedUnavailable(incidentId, helperId, {
        reportId: crypto.randomUUID(),
        aedId: assignment.aedId,
        reasonCode: "helper_reported_unavailable",
        expectedAssignmentRevision: assignment.assignmentRevision,
        reportedAt: new Date().toISOString(),
        helperLocation: location.position ? { latitude: location.position.lat, longitude: location.position.lng } : undefined,
      });
      setAssignmentOutcome(result.outcome);
      if (result.outcome === "reassigned" || result.outcome === "duplicate_report" || result.outcome === "no_candidate") {
        const current = await api.getAedAssignment(incidentId, helperId);
        setAssignment(current);
        setAeds(current.destination ? { candidates: [current.destination], dataUpdatedAt: current.assignedAt } : { candidates: [], dataUpdatedAt: current.assignedAt });
        if (result.outcome === "no_candidate") setStatus("unavailable");
      }
    } catch (reason) {
      if (reason instanceof ApiClientError && reason.code === "stale_revision") {
        setAssignmentOutcome("stale_revision");
        setError("AED 指派已更新，請重新整理後再回報。");
      } else {
        setError(userMessageForApiError(reason));
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Stack sx={{ py: 8, alignItems: "center" }}><CircularProgress /><Typography sx={{ mt: 2 }}>正在讀取協助任務…</Typography></Stack>;
  if (!validGrant) return <Alert severity="error">{error}</Alert>;

  const completed = status === "delivered" || (isGreeter && status === "arrived");
  const terminal = completed || status === "unavailable";
  const title = completed
    ? isGreeter ? "已抵達救護車接應點" : "已取得 AED"
    : isGreeter ? "前往救護車接應點" : "前往現場指定的 AED";
  const nextStatus: ApiHelperStatus = status === "accepted" ? "en_route" : status === "en_route" ? "arrived" : status === "arrived" ? "obtained" : "delivered";
  const actionLabel = status === "accepted" ? "開始前往" : status === "en_route" ? isGreeter ? "我已抵達接應點" : "我已抵達 AED 位置" : status === "arrived" ? "我已取得 AED" : "AED 已送達現場";
  const locationStale = isTimestampStale(lastLocationUpdatedAt, clock, 45_000);

  return (
    <Stack spacing={2.5} className="helper-page-enter">
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <div><div className="helper-kicker">{isGreeter ? "救護車接應" : "AED 取件任務"}</div><Typography component="h1" variant="h3">{title}</Typography></div>
        <Chip label={statusLabels[status]} color={completed ? "success" : status === "unavailable" ? "error" : "secondary"} />
      </Stack>

      <div><Stack direction="row" sx={{ justifyContent: "space-between", mb: .75 }}><Typography variant="caption" sx={{ fontWeight: 800 }}>任務進度</Typography><Typography variant="caption">{progressValues[status]}%</Typography></Stack><LinearProgress variant="determinate" value={progressValues[status]} color={completed ? "success" : "secondary"} /></div>
      {error ? <Alert severity="error">{error}</Alert> : null}
      {assignmentOutcome === "reassigned" && <StatusBanner title="已改派其他 AED" severity="warning">目的地與指派版本已更新，請依新位置行動。</StatusBanner>}
      {assignmentOutcome === "no_candidate" && <StatusBanner title="目前沒有其他候選 AED" severity="warning">請回報現場並依 119 派遣員指示行動。</StatusBanner>}
      {assignmentOutcome === "duplicate_report" && <StatusBanner title="這筆回報已處理">目前顯示的是最新 AED 指派。</StatusBanner>}
      {assignmentOutcome === "stale_revision" && <StatusBanner title="指派已更新" severity="warning">請重新整理此頁後再回報。</StatusBanner>}
      {location.state === "denied" || location.state === "unavailable" ? <StatusBanner title="定位權限不足" severity="warning">仍可依現場提供的地址完成任務；其他狀態回報不受影響。</StatusBanner> : null}

      {completed ? (
        <Card className="mission-complete-card"><CardContent><CheckCircle2 size={42} /><Typography component="h2" variant="h5" sx={{ mt: 1 }}>{isGreeter ? "請留在入口等候救護車" : "AED 已送達事故現場"}</Typography><Typography color="text.secondary" sx={{ mt: .75 }}>{isGreeter ? "救護車到達後，依現場人員提供的位置引導救護人員。" : "任務完成；請依現場救援者與 119 派遣員指示行動。"}</Typography></CardContent></Card>
      ) : status === "unavailable" ? (
        <StatusBanner title="已回報無法完成" severity="warning">現場可以改請其他協助者，請勿繼續前往原目的地。</StatusBanner>
      ) : (
        <>
          {isGreeter ? (
            <Card className="destination-card"><CardContent><Stack direction="row" spacing={1} sx={{ alignItems: "center" }}><MapPin size={22} /><Typography component="h2" variant="h5">現場快照</Typography></Stack><CanonicalSnapshotCard snapshot={snapshot ?? null} /></CardContent></Card>
          ) : (
            <>
              {!assignment ? (
                <StatusBanner title="已接受任務，等待 AED 指派">
                  現場建立指派後會自動更新目的地，不需要重新掃描 QR Code。
                </StatusBanner>
              ) : null}
              {!assignment && aeds?.candidates.length ? (
                <StatusBanner title="附近 AED 預覽" severity="warning">
                  以下是真實資料庫依你目前位置找到的候選地點；請等現場按下「派人拿 AED」並完成正式指派後再出發。
                </StatusBanner>
              ) : null}
              {aeds?.candidates[0] ? (
                <TaskMap
                  destination={{ lat: aeds.candidates[0].latitude, lng: aeds.candidates[0].longitude }}
                  destinationLabel={aeds.candidates[0].name}
                  markerLabel="AED"
                  origin={location.position}
                  estimateSource={aeds.candidates[0].estimateSource}
                />
              ) : null}
              <AedCandidatePanel data={aeds} now={clock} />
            </>
          )}

          {location.state === "sharing" ? (
            <StatusBanner title={locationStale ? "位置同步可能已過時" : lastLocationUpdatedAt ? "位置已同步" : "正在同步位置"} severity={locationStale ? "warning" : "success"}>
              {lastLocationUpdatedAt
                ? `最後同步 ${formatSyncTime(lastLocationUpdatedAt)}；精確度約 ${Math.round(location.position?.accuracyMeters ?? 0)} 公尺。`
                : "已取得定位，正在等待後端確認第一次位置更新。"}
              {locationStale ? " 請保持此頁開啟，或重新確認網路連線。" : ` 回報紀錄 r${revision}`}
            </StatusBanner>
          ) : <Button variant="outlined" onClick={location.start} disabled={location.state === "requesting"} startIcon={<Radio size={20} />}>{location.state === "requesting" ? "正在取得定位…" : "開始分享我的位置"}</Button>}
          <Stack spacing={1.25} className="task-actions">
            <Button variant="contained" color={isGreeter ? "primary" : "secondary"} size="large" disabled={busy || (!isGreeter && !assignment)} onClick={() => report(nextStatus)}>{busy ? <CircularProgress size={24} color="inherit" /> : !isGreeter && !assignment ? "等待現場正式指派" : actionLabel}</Button>
            {!isGreeter ? <Button variant="outlined" color="error" size="large" disabled={busy} onClick={reportUnavailable}>無法取得 AED</Button> : null}
          </Stack>
        </>
      )}
      {!terminal && <StatusBanner title="限時授權">這個頁面只能存取本次任務需要的資料；事故結束或授權到期後會失效。</StatusBanner>}
      <Typography variant="caption" color="text.secondary">Incident {incidentId} · Helper {helperId} · 回報紀錄 r{revision}</Typography>
    </Stack>
  );
}
