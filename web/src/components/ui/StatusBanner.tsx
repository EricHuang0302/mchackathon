import type { ReactNode } from "react";
import { Alert, AlertTitle } from "@mui/material";

interface StatusBannerProps {
  title: string;
  children: ReactNode;
  severity?: "error" | "info" | "success" | "warning";
}
export function StatusBanner({ title, children, severity = "info" }: StatusBannerProps) {
  return (
    <Alert severity={severity} variant="outlined">
      <AlertTitle>{title}</AlertTitle>
      {children}
    </Alert>
  );
}
