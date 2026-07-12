import { useEffect, useRef } from "react";
import { useGoogleMap } from "@react-google-maps/api";

type MarkerVariant = "pin" | "origin" | "destination";

type AdvancedMapMarkerProps = {
  position: google.maps.LatLngLiteral;
  label?: string;
  title?: string;
  draggable?: boolean;
  variant?: MarkerVariant;
  onDragEnd?: (position: google.maps.LatLngLiteral) => void;
};

const ACCENT = "#1B4FD8";
const ORIGIN_COLOR = "#3B82F6"; // blue, matches the route's starting colour

/** Build the DOM content shown at the marker position for each variant. */
function buildMarkerContent(variant: MarkerVariant, label?: string): HTMLElement {
  if (variant === "origin") {
    const el = document.createElement("div");
    el.style.cssText = `width:24px;height:24px;border-radius:50%;background:${ORIGIN_COLOR};border:3px solid #fff;box-shadow:0 0 0 6px ${ORIGIN_COLOR}33,0 3px 8px rgba(0,0,0,0.35);`;
    return el;
  }
  if (variant === "destination") {
    const el = document.createElement("div");
    el.style.cssText = "width:38px;height:38px;border-radius:50%;background:#0B1C63;border:2.5px solid #fff;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 12px rgba(0,0,0,0.4);";
    el.innerHTML = '<svg width="19" height="19" viewBox="0 0 24 24" fill="#fff" xmlns="http://www.w3.org/2000/svg"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z"/></svg>';
    return el;
  }
  const pin = new window.google.maps.marker.PinElement({
    glyphText: label,
    background: ACCENT,
    borderColor: "#1E40AF",
    glyphColor: "#FFFFFF",
  } as google.maps.marker.PinElementOptions & { glyphText?: string });
  return pin.element;
}

function readPosition(position: google.maps.marker.AdvancedMarkerElement["position"]) {
  if (!position) return null;
  if (position instanceof google.maps.LatLng) {
    return { lat: position.lat(), lng: position.lng() };
  }
  return { lat: Number(position.lat), lng: Number(position.lng) };
}

export function AdvancedMapMarker({ position, label, title, draggable, variant = "pin", onDragEnd }: AdvancedMapMarkerProps) {
  const map = useGoogleMap();
  const markerRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
  const listenerRef = useRef<google.maps.MapsEventListener | null>(null);

  useEffect(() => {
    if (!map || !window.google?.maps?.marker?.AdvancedMarkerElement) return;

    const marker = new window.google.maps.marker.AdvancedMarkerElement({
      map,
      position,
      title,
      content: buildMarkerContent(variant, label),
      gmpDraggable: draggable,
    });
    markerRef.current = marker;

    return () => {
      listenerRef.current?.remove();
      listenerRef.current = null;
      marker.map = null;
      markerRef.current = null;
    };
  }, [map, label, variant]);

  useEffect(() => {
    const marker = markerRef.current;
    if (!marker) return;
    marker.position = position;
    marker.title = title ?? "";
    marker.gmpDraggable = Boolean(draggable);
  }, [position, title, draggable]);

  useEffect(() => {
    const marker = markerRef.current;
    listenerRef.current?.remove();
    listenerRef.current = null;
    if (!marker || !draggable || !onDragEnd) return;

    listenerRef.current = marker.addListener("dragend", () => {
      const nextPosition = readPosition(marker.position);
      if (nextPosition) onDragEnd(nextPosition);
    });
  }, [draggable, onDragEnd]);

  return null;
}
