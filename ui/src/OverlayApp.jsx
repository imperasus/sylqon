import { useEffect } from "react";
import OverlayView from "./components/overlay/OverlayView.jsx";

/* Bare overlay shell — no StatusBar / navigation. Forces a transparent page
   background so it composites cleanly as an OBS browser source or a corner
   widget over the game. */
export default function OverlayApp() {
  useEffect(() => {
    const prevHtml = document.documentElement.style.background;
    const prevBody = document.body.style.background;
    document.documentElement.style.background = "transparent";
    document.body.style.background = "transparent";
    return () => {
      document.documentElement.style.background = prevHtml;
      document.body.style.background = prevBody;
    };
  }, []);

  return (
    <div className="min-h-screen w-full bg-transparent">
      <OverlayView />
    </div>
  );
}
