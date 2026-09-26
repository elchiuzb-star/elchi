import fs from "node:fs";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * Phone testing of the driver's GPS (Q148): browsers give location only to HTTPS pages (localhost excepted), so a
 * phone on the LAN needs the dev server on HTTPS. Point these at a certificate the phone trusts (e.g. made with
 * mkcert, see README "Telefonda GPS sinovi"); nothing is generated here and no plugin is added.
 */
const httpsCert = process.env.ELCHI_DEV_HTTPS_CERT;
const httpsKey = process.env.ELCHI_DEV_HTTPS_KEY;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    https: httpsCert && httpsKey ? { cert: fs.readFileSync(httpsCert), key: fs.readFileSync(httpsKey) } : undefined,
    // With `VITE_API_BASE_URL=/api/v1` the phone talks to the backend through this server: same origin, same TLS,
    // and the tracking WebSocket (`/api/v2/ws`) is proxied too - no mixed content, no CORS.
    proxy: {
      "/api": {
        target: process.env.ELCHI_DEV_API_PROXY || "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    // jsdom rather than node: the component tests render the real design-system components, so they need a
    // document. The pure rule tests do not care either way.
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
