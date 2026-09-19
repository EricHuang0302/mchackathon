import { createTheme } from "@mui/material/styles";

export const appTheme = createTheme({
  palette: {
    mode: "light",
    primary: {
      main: "#b42318",
      dark: "#7a1710",
      light: "#f97066",
      contrastText: "#ffffff",
    },
    secondary: {
      main: "#155eef",
      dark: "#1849a9",
      contrastText: "#ffffff",
    },
    success: {
      main: "#067647",
    },
    warning: {
      main: "#b54708",
    },
    error: {
      main: "#b42318",
    },
    background: {
      default: "#f4f1ea",
      paper: "#fffdf7",
    },
    text: {
      primary: "#1d2939",
      secondary: "#475467",
    },
    divider: "#d0d5dd",
  },
  typography: {
    fontFamily: '"Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif',
    h1: {
      fontWeight: 900,
      letterSpacing: "-0.04em",
    },
    h2: {
      fontWeight: 850,
      letterSpacing: "-0.03em",
    },
    h3: {
      fontWeight: 800,
      letterSpacing: "-0.025em",
    },
    button: {
      fontWeight: 800,
      letterSpacing: "0.01em",
    },
    overline: {
      fontWeight: 900,
      letterSpacing: "0.14em",
    },
  },
  shape: {
    borderRadius: 14,
  },
  components: {
    MuiButton: {
      defaultProps: {
        disableElevation: true,
      },
      styleOverrides: {
        root: {
          minHeight: 52,
          borderRadius: 12,
          textTransform: "none",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          border: "1px solid #d0d5dd",
          boxShadow: "0 12px 34px rgba(29, 41, 57, 0.08)",
        },
      },
    },
  },
});
