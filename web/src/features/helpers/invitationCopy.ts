import { ApiClientError } from "../../lib/connection/apiClient";
import type { ShareScope } from "../../types/api";

export type InviteFailure = "expired" | "redeemed" | "revoked" | "permission_denied";

export const FAILURES: Record<InviteFailure, { title: string; description: string }> = {
  expired: { title: "邀請已過期", description: "這個限時邀請已失效，請聯絡現場人員重新建立。" },
  redeemed: { title: "邀請已被兌換", description: "這個一次性邀請已由其他協助者使用。" },
  revoked: { title: "邀請已被撤銷", description: "現場人員已停止這個邀請，請不要再使用舊連結。" },
  permission_denied: { title: "無法取得權限", description: "邀請密鑰缺失，或目前的身分不能兌換這個邀請。" },
};

const TASKS: Record<ShareScope, { overline: string; title: string; description: string }> = {
  aed_runner: {
    overline: "AED runner",
    title: "協助取得並送達 AED",
    description: "前往指定位置取得 AED，再送回事故現場；接受後可回報取件進度。",
  },
  ambulance_greeter: {
    overline: "Ambulance greeter",
    title: "前往集合點接應救護車",
    description: "前往指定集合位置引導救護人員，並查看共用的現場快照。",
  },
  ems_viewer: {
    overline: "EMS viewer",
    title: "查看救護交接資料",
    description: "以唯讀權限查看現場快照、MIST 與完整時間軸，供救護人員交接使用。",
  },
};

export function parseInviteScope(search: string): ShareScope | null {
  const query = new URLSearchParams(search);
  const value = query.get("role") ?? query.get("scope");
  return value === "aed_runner" || value === "ambulance_greeter" || value === "ems_viewer" ? value : null;
}

export function taskForScope(scope: ShareScope | null) {
  return scope ? TASKS[scope] : {
    overline: "Invitation",
    title: "現場需要你協助",
    description: "這是一個限時救援邀請；接受後會依後端核發的角色顯示任務。",
  };
}

export function inviteFailureFor(error: unknown): InviteFailure | null {
  if (!(error instanceof ApiClientError)) return null;
  const reason = error.payload.error.details?.reason;
  if (reason === "invitation_redeemed") return "redeemed";
  if (reason === "invitation_revoked") return "revoked";
  if (reason === "permission_denied" || error.code === "unauthorized") return "permission_denied";
  if (reason === "invitation_expired" || error.code === "expired") return "expired";
  return null;
}
