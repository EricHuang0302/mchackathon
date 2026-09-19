import { Box, Stack, Typography } from "@mui/material";

interface MapPlaceholderProps {
  destination: string;
  helperLabel?: string;
  markerLabel?: string;
}
export function MapPlaceholder({ destination, helperLabel = "你的位置", markerLabel = "目標" }: MapPlaceholderProps) {
  return (
    <Box className="map-placeholder" role="img" aria-label={`示意地圖，目的地為${destination}`}>
      <span className="map-grid" aria-hidden="true" />
      <span className="map-route" aria-hidden="true" />
      <Stack className="map-origin" spacing={0.25}>
        <span className="map-dot map-dot--helper" aria-hidden="true" />
        <Typography variant="caption">{helperLabel}</Typography>
      </Stack>
      <Stack className="map-destination" spacing={0.25}>
        <span className="map-dot map-dot--target" aria-hidden="true">
          {markerLabel}
        </span>
        <Typography variant="caption">{destination}</Typography>
      </Stack>
      <Box className="mock-label">MAP MOCK</Box>
    </Box>
  );
}
