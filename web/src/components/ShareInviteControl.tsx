import { useState } from "react";
import QRCode from "react-qr-code";
import type { ShareScope } from "../types/api";
import { incidentRuntime } from "../lib/connection/incidentRuntime";

export function ShareInviteControl({ scope, label }: { scope: ShareScope; label: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    setError(null);
    try { setUrl(await incidentRuntime.createShare(scope)); }
    catch { setError("目前無法建立分享連結，請確認本機 API 已連線。"); }
  };
  return <div className="share-control">
    <button className="secondary-action" type="button" onClick={create}>{label}</button>
    {url && <div className="share-result">
      <strong>限時分享連結</strong>
      <div className="share-qr"><QRCode value={url} size={192} title={`${label}分享 QR Code`} /></div>
      <a href={url}>{url}</a>
      <small>連結與 QR Code 含一次性密鑰，請只傳給指定協助者。</small>
    </div>}
    {error && <p className="share-error" role="alert">{error}</p>}
  </div>;
}
