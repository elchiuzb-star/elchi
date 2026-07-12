import { useEffect, useRef } from "react";
import { useGoogleMap } from "@react-google-maps/api";

type AdvancedMapMarkerProps = {
  position: google.maps.LatLngLiteral;
  label?: string;
  title?: string;
  draggable?: boolean;
  onDragEnd?: (position: google.maps.LatLngLiteral) => void;
};

function readPosition(position: google.maps.marker.AdvancedMarkerElement["position"]) {
  if (!position) return null;
  if (position instanceof google.maps.LatLng) {
    return { lat: position.lat(), lng: position.lng() };
  }
  return { lat: Number(position.lat), lng: Number(position.lng) };
}

export function AdvancedMapMarker({ position, label, title, draggable, onDragEnd }: AdvancedMapMarkerProps) {
  const map = useGoogleMap();
  const markerRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
  const listenerRef = useRef<google.maps.MapsEventListener | null>(null);

  useEffect(() => {
    if (!map || !window.google?.maps?.marker?.AdvancedMarkerElement) return;

    const pin = new window.google.maps.marker.PinElement({
      glyphText: label,
      background: "#1B4FD8",
      borderColor: "#1E40AF",
      glyphColor: "#FFFFFF",
    } as google.maps.marker.PinElementOptions & { glyphText?: string });
    const marker = new window.google.maps.marker.AdvancedMarkerElement({
      map,
      position,
      title,
      content: pin.element,
      gmpDraggable: draggable,
    });
    markerRef.current = marker;

    return () => {
      listenerRef.current?.remove();
      listenerRef.current = null;
      marker.map = null;
      markerRef.current = null;
    };
  }, [map, label]);

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
