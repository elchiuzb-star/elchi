import React from "react";
import ReactDOM from "react-dom/client";

import AdminApp from "./app/AdminApp";
import { AuthProvider } from "./auth/AuthContext";
import App from "./app/App";
import { PublicSharePage } from "./app/v2/PublicSharePage";
import { PublicTrackingPage } from "./app/v2/PublicTrackingPage";
import { PrivacyPolicy } from "./pages/PrivacyPolicy";
import { startTheme } from "./app/ui/theme";
import { codeFromPath, rememberCode } from "./app/promo";
import "./styles/index.css";

// Before the first render, so a person who chose dark never gets a white flash on launch.
startTheme();

const path = window.location.pathname;
const isAdminPanel = path.startsWith("/admin");
/** Public share page of a listing (O3, §20.2): opened by outsiders, no session required. */
const shareToken = path.startsWith("/e/") ? decodeURIComponent(path.slice(3)) : null;
/** K7 recipient tracking page `/t/<token>`: opened by the person the sender shared it with, no session required. */
const trackingToken = path.startsWith("/t/") ? decodeURIComponent(path.slice(3)) : null;
/** Reachable without a session, because a store listing and the settings screen both link straight to it. */
const isPrivacy = path.startsWith("/privacy");
/**
 * Referral link `/r/<code>` (Q107): the code is kept through login and the person confirms it on the bonus screen.
 * An existing attribution is never replaced (the server keeps the first one). The address bar goes back to `/`.
 */
const referralCode = codeFromPath(path);
if (referralCode) {
  rememberCode(referralCode);
  window.history.replaceState(null, "", "/");
}

function Root() {
  if (isPrivacy) return <PrivacyPolicy />;
  if (shareToken) return <PublicSharePage token={shareToken} onOpenApp={() => window.location.assign("/")} />;
  if (trackingToken) return <PublicTrackingPage token={trackingToken} />;
  if (isAdminPanel) return <AdminApp />;
  // One client app, one screen stack. The stage-2 engine drives the v1 screens themselves - there is no
  // second application at /v2 and no marketplace "section" to route to.
  return (
    <AuthProvider>
      <App />
    </AuthProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
