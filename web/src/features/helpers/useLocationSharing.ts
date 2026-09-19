import { useCallback, useEffect, useRef, useState } from "react";

import type { Coordinates } from "../../types/domain";

export type LocationPermissionState = "idle" | "requesting" | "sharing" | "denied" | "unavailable";

export function useLocationSharing() {
  const [state, setState] = useState<LocationPermissionState>("idle");
  const [position, setPosition] = useState<Coordinates>();
  const watchId = useRef<number | undefined>(undefined);

  const stop = useCallback(() => {
    if (watchId.current !== undefined) {
      navigator.geolocation.clearWatch(watchId.current);
      watchId.current = undefined;
    }
    setState((current) => (current === "sharing" ? "idle" : current));
  }, []);

  const start = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setState("unavailable");
      return;
    }

    setState("requesting");
    watchId.current = navigator.geolocation.watchPosition(
      ({ coords, timestamp }) => {
        setPosition({
          lat: coords.latitude,
          lng: coords.longitude,
          accuracyMeters: coords.accuracy,
          observedAt: new Date(timestamp).toISOString(),
        });
        setState("sharing");
      },
      (error) => {
        setState(error.code === error.PERMISSION_DENIED ? "denied" : "unavailable");
      },
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 12_000 },
    );
  }, []);

  useEffect(() => stop, [stop]);

  return { position, start, state, stop };
}
