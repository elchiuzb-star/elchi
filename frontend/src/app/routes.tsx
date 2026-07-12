// Route configuration is defined and exported from App.tsx (co-located with page
// components to avoid circular imports in this single-bundle architecture).
//
// URL structure:
//   /          → Auth flow (splash → onboarding → role select → phone → OTP)
//   /driver    → Driver mobile app
//   /client    → Client mobile app
//   /admin     → Admin desktop panel
//
// All shared state (role, phone, themeMode, lang) lives in RootLayout and is
// distributed via AppCtx so pages stay in sync without prop-drilling.

export {} from "./App";
