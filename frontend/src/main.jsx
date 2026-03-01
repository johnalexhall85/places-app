import "leaflet/dist/leaflet.css";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import ProfileCounty from "./pages/ProfileCounty";
import ProfileTract from "./pages/ProfileTract";
import "./index.css";

function resolveRoute(pathname) {
  const countyMatch = pathname.match(/^\/profile\/county\/([^/]+)\/?$/i);
  if (countyMatch) {
    return { type: "profile-county", id: countyMatch[1] };
  }
  const tractMatch = pathname.match(/^\/profile\/tract\/([^/]+)\/?$/i);
  if (tractMatch) {
    return { type: "profile-tract", id: tractMatch[1] };
  }
  return { type: "map" };
}

function Root() {
  const route = resolveRoute(window.location.pathname);
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
