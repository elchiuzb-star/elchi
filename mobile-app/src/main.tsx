import React from "react";
import ReactDOM from "react-dom/client";

import AdminApp from "./app/AdminApp";
import { AuthProvider } from "./auth/AuthContext";
import App from "./app/App";
import "./styles/index.css";

const isAdminPanel = window.location.pathname.startsWith("/admin");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isAdminPanel ? (
      <AdminApp />
    ) : (
      <AuthProvider>
        <App />
      </AuthProvider>
    )}
  </React.StrictMode>,
);
