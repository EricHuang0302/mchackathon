import { Box, Chip, Container, Stack, Typography } from "@mui/material";
import { Link, Outlet, useLocation } from "react-router";
import { DEMO_WARNING, isDemoMode } from "../../lib/demoMode";

function getSection(pathname: string) {
  if (pathname.includes("handoff")) return "救護交接";
  if (pathname.includes("helper") || pathname.includes("join")) return "協助者任務";
  if (pathname.includes("call-mode")) return "通話模式";
  return "主要救援";
}

export function AppFrame() {
  const location = useLocation();
  const demoMode = isDemoMode();

  return (
    <Box className="foundation-shell">
      <Box component="header" className="foundation-header">
        <Container maxWidth="md">
          <Stack
            direction="row"
            spacing={2}
            sx={{ alignItems: "center", justifyContent: "space-between" }}
          >
            <Link to="/" className="brand-link" aria-label="回到急救副駕首頁">
              <span className="foundation-brand-mark" aria-hidden="true">
                +
              </span>
              <span>
                <Typography component="span" className="brand-title">
                  急救副駕
                </Typography>
                <Typography component="span" className="brand-subtitle">
                  First Aid Copilot
                </Typography>
              </span>
            </Link>
            <Stack spacing={0.75} sx={{ alignItems: "flex-end" }}>
              {demoMode && <Chip label={DEMO_WARNING} color="warning" size="small" />}
              <Chip label={getSection(location.pathname)} color="primary" variant="outlined" />
            </Stack>
          </Stack>
        </Container>
      </Box>

      <Container component="main" maxWidth="md" className="foundation-main">
        <Outlet />
      </Container>

      <Box component="footer" className="foundation-footer">
        <Container maxWidth="md">
          <Typography variant="caption">
            黑客松展示原型 · 緊急情況請優先聯絡 119，並遵循派遣員指示
          </Typography>
        </Container>
      </Box>
    </Box>
  );
}
