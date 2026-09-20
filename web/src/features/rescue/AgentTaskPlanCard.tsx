import QRCode from "react-qr-code";

import { buildShareUrl } from "../helpers/shareLinks";
import type { AgentTaskPlan, AgentToolResult, ShareScope } from "../../types/api";

export function AgentTaskPlanCard({
  plan,
  tools,
}: {
  plan: AgentTaskPlan | null;
  tools: AgentToolResult[];
}) {
  if (!plan && tools.length === 0) return null;
  const inviteTool = [...tools].reverse().find((item) => item.name === "dispatch_helper");
  const invite = inviteTool?.status === "completed" ? inviteTool.result : undefined;
  const inviteScope = invite?.scope === "aed_runner" || invite?.scope === "ambulance_greeter"
    ? invite.scope as ShareScope
    : null;
  const inviteUrl = invite &&
    typeof invite.inviteId === "string" &&
    typeof invite.secret === "string" &&
    inviteScope
    ? buildShareUrl(location.origin, invite.inviteId, invite.secret, inviteScope)
    : null;
  const helperLabel = inviteScope === "ambulance_greeter" ? "救護車引導協助者" : "AED 協助者";
  const aedTool = [...tools].reverse().find((item) => item.name === "find_nearest_aeds");
  const candidates = Array.isArray(aedTool?.result?.candidates) ? aedTool.result.candidates.length : null;

  return <section className="card agent-plan" aria-labelledby="agent-plan-title">
    <p className="eyebrow">Gemini 任務計畫</p>
    <h2 className="card-title" id="agent-plan-title">{plan?.summary ?? "正在協調現場任務"}</h2>
    {plan && <ol>{plan.steps.map((step) => <li key={step.id}>{step.label}</li>)}</ol>}
    <div className="agent-tool-statuses">
      {aedTool && <p>{aedTool.status === "completed" ? `AED 搜尋完成${candidates === null ? "" : `：${candidates} 個候選`}` : "AED 搜尋目前無法使用"}</p>}
      {inviteTool && <p>{inviteTool.status === "completed" ? `${helperLabel}邀請已建立` : "協助者邀請建立失敗"}</p>}
    </div>
    {inviteUrl && <div className="agent-invite">
      <div className="share-qr" aria-label={`Gemini 建立的${helperLabel} QR Code`}><QRCode value={inviteUrl} size={196} title={`${helperLabel}邀請`} /></div>
      <p>請協助者掃描並接受任務；{inviteScope === "aed_runner" ? "系統會在取得位置與授權後建立 AED 指派。" : "協助者只會看到接應救護車所需資訊。"}</p>
      <a href={inviteUrl} target="_blank" rel="noreferrer">開啟協助者任務</a>
    </div>}
  </section>;
}
