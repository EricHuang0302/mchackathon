import { useEffect, useMemo, useState } from "react";
import QRCode from "react-qr-code";

import { buildShareUrl, demoInviteId } from "../features/helpers/shareLinks";
import { userMessageForApiError } from "../lib/connection/apiClient";
import { incidentRuntime } from "../lib/connection/incidentRuntime";
import type { CreateShareResponse, ShareScope } from "../types/api";

const scopeNames: Record<ShareScope, string> = {
  aed_runner: "AED 取件者",
  ambulance_greeter: "救護車接應者",
  ems_viewer: "救護交接檢視",
};

interface ActiveInvite extends CreateShareResponse {
  url: string;
}

function remainingLabel(expiresAt: string, now: number) {
  const seconds = Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1_000));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function ShareInviteControl({ scope, label }: { scope: ShareScope; label: string }) {
  const [invite, setInvite] = useState<ActiveInvite>();
  const [error, setError] = useState<string>();
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const expired = Boolean(invite && new Date(invite.expiresAt).getTime() <= now);
  const timerLabel = useMemo(() => invite ? remainingLabel(invite.expiresAt, now) : "", [invite, now]);

  useEffect(() => {
    if (!invite || expired) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [expired, invite]);

  const create = async () => {
    setError(undefined);
    setCopied(false);
    try {
      const isDemo = new URLSearchParams(location.search).get("demo") === "1";
      const share = isDemo
        ? {
            inviteId: demoInviteId(scope), secret: "demo-only", scope,
            expiresAt: new Date(Date.now() + 5 * 60_000).toISOString(),
          }
        : await incidentRuntime.createShare(scope);
      setNow(Date.now());
      setInvite({ ...share, url: buildShareUrl(location.origin, share.inviteId, share.secret, share.scope) });
    } catch (reason) {
      setError(userMessageForApiError(reason));
    }
  };

  const copy = async () => {
    if (!invite || expired) return;
    try {
      await navigator.clipboard.writeText(invite.url);
      setCopied(true);
    } catch {
      setError("瀏覽器無法複製連結，請長按下方網址複製。");
    }
  };

  return <div className="share-control">
    <button className="secondary-action" type="button" onClick={create}>{invite ? "重新產生邀請" : label}</button>
    {invite && <div className={`share-result${expired ? " share-result--expired" : ""}`}>
      <div className="share-result-header">
        <span><strong>{scopeNames[scope]}</strong><small>一次性限時邀請</small></span>
        <b aria-label={`剩餘時間 ${timerLabel}`}>{expired ? "已過期" : timerLabel}</b>
      </div>
      {expired ? <p>這個 QR Code 已失效，請重新產生邀請。</p> : <>
        <div className="share-qr" aria-label={`${scopeNames[scope]}邀請 QR Code`}>
          <QRCode value={invite.url} size={196} title={`${scopeNames[scope]}邀請`} />
        </div>
        <p>請指定的協助者使用自己的手機掃描。連結成功兌換一次後即失效。</p>
        <a href={invite.url}>{invite.url}</a>
        <div className="share-actions">
          <button type="button" onClick={copy}>{copied ? "已複製" : "複製連結"}</button>
          <a href={invite.url} target="_blank" rel="noreferrer">本機測試</a>
        </div>
      </>}
    </div>}
    {error && <p className="share-error" role="alert">{error}</p>}
  </div>;
}
