import { useEffect } from "react";
import { APIProvider, AdvancedMarker, Map, Pin, useMap, useMapsLibrary } from "@vis.gl/react-google-maps";
import { Box, Button, Stack, Typography } from "@mui/material";
import { Navigation } from "lucide-react";

import type { Coordinates } from "../../types/domain";
import { MapPlaceholder } from "./MapPlaceholder";

interface TaskMapProps {
  destination: Coordinates;
  destinationLabel: string;
  estimateSource: "route" | "straight_line" | "none";
  markerLabel?: string;
  origin?: Coordinates;
}

function Directions({ destination, origin }: Pick<TaskMapProps, "destination" | "origin">) {
  const map = useMap();
  const routesLibrary = useMapsLibrary("routes");

  useEffect(() => {
    if (!map || !routesLibrary || !origin) return;

    const service = new routesLibrary.DirectionsService();
    const renderer = new routesLibrary.DirectionsRenderer({
      map,
      preserveViewport: false,
      suppressMarkers: true,
      polylineOptions: { strokeColor: "#155eef", strokeOpacity: 0.9, strokeWeight: 6 },
    });

    void service
      .route({
        origin,
        destination,
        travelMode: google.maps.TravelMode.WALKING,
      })
      .then((result) => renderer.setDirections(result))
      .catch(() => renderer.setMap(null));

    return () => renderer.setMap(null);
  }, [destination, map, origin, routesLibrary]);

  return null;
}

function GoogleTaskMap({ destination, destinationLabel, estimateSource, markerLabel = "目標", origin }: TaskMapProps) {
  return (
    <Box className="task-map" aria-label={`前往${destinationLabel}的地圖`}>
      <Map
        defaultCenter={destination}
        defaultZoom={17}
        gestureHandling="greedy"
        disableDefaultUI
        mapId={import.meta.env.VITE_GOOGLE_MAPS_MAP_ID || "DEMO_MAP_ID"}
      >
        <AdvancedMarker position={destination} title={destinationLabel}>
          <Pin background="#b42318" borderColor="#7a1710" glyphColor="#ffffff" glyph={markerLabel} />
        </AdvancedMarker>
        {origin ? (
          <AdvancedMarker position={origin} title="你的位置">
            <span className="live-location-dot" />
          </AdvancedMarker>
        ) : null}
        {estimateSource === "route" ? <Directions destination={destination} origin={origin} /> : null}
      </Map>
    </Box>
  );
}

export function TaskMap(props: TaskMapProps) {
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;
  const mapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${props.destination.lat},${props.destination.lng}&travelmode=walking`;

  return (
    <Stack spacing={1.25}>
      {apiKey ? (
        <APIProvider apiKey={apiKey} libraries={["routes"]}>
          <GoogleTaskMap {...props} />
        </APIProvider>
      ) : (
        <MapPlaceholder destination={props.destinationLabel} markerLabel={props.markerLabel} />
      )}
      <Button
        component="a"
        href={mapsUrl}
        target="_blank"
        rel="noreferrer"
        variant="outlined"
        startIcon={<Navigation size={19} />}
      >
        使用 Google Maps 導航
      </Button>
      {!apiKey ? (
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: "center" }}>
          尚未設定 Maps API key，目前顯示離線示意圖；外部導航仍可使用。
        </Typography>
      ) : null}
      {props.estimateSource === "straight_line" ? (
        <Typography variant="caption" color="text.secondary" sx={{ textAlign: "center" }}>
          此距離為直線參考，地圖不會將它畫成步行路線或 ETA。
        </Typography>
      ) : null}
    </Stack>
  );
}
