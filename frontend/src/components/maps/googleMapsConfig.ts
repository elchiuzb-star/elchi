import type { Libraries } from "@react-google-maps/api";

export const googleMapsLibraries: Libraries = ["places", "marker"];
export const googleMapsMapId = (import.meta.env.VITE_GOOGLE_MAPS_MAP_ID as string | undefined) || "DEMO_MAP_ID";
