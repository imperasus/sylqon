import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import OverlayApp from "./OverlayApp.jsx";
import "./index.css";

// Lightweight routing (the project has no react-router): the /overlay path
// renders only the minimal in-game overlay; everything else is the dashboard.
const isOverlay = window.location.pathname.startsWith("/overlay");

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {isOverlay ? <OverlayApp /> : <App />}
  </React.StrictMode>
);
