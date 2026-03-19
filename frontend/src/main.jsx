import "leaflet/dist/leaflet.css";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import CdcStateFundingProfile from "./pages/CdcStateFundingProfile";
import ProfileCounty from "./pages/ProfileCounty";
import ProfileTract from "./pages/ProfileTract";
import "./index.css";
import { resolveRoute } from "./utils/routeResolver";

function Root() {
  const pathname = window.location.pathname;
  if (/^\/taggs\/funding-profile\/?$/i.test(pathname)) {
    const params = new URLSearchParams(window.location.search);
    return <CdcStateFundingProfile stateCode={params.get("state") ?? ""} />;
  }
  const route = resolveRoute(window.location.pathname);
  if (route.type === "cdc-state-funding-profile") {
    return <CdcStateFundingProfile stateCode={route.id} />;
  }
  if (route.type === "profile-county") {
    return <ProfileCounty countyFips={route.id} />;
  }
  if (route.type === "profile-tract") {
    return <ProfileTract tractGeoid={route.id} />;
  }
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
