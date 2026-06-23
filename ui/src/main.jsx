import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import OverlayApp from "./OverlayApp.jsx";
import "./index.css";

// Lightweight routing (the project has no react-router): the /overlay path
// renders only the minimal in-game overlay; everything else is the dashboard.
const isOverlay = window.location.pathname.startsWith("/overlay");

// The dashboard rides a fluid root font-size (index.css) so the whole cockpit
// scales to fit any window. The overlay is a fixed-size widget and must keep a
// stable 16px base, so the class is added only for the dashboard. Set before
// first paint to avoid a scale flash.
if (!isOverlay) document.documentElement.classList.add("app-fluid-root");

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {isOverlay ? <OverlayApp /> : <App />}
  </React.StrictMode>
);
