import "leaflet/dist/leaflet.css";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import CdcStateFundingProfile from "./pages/CdcStateFundingProfile";
import FundingModelBuilder from "./pages/FundingModelBuilder";
import ProfileCounty from "./pages/ProfileCounty";
import ProfileTract from "./pages/ProfileTract";
import "./index.css";
import { resolveRoute } from "./utils/routeResolver";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
          <h2>Something went wrong.</h2>
          <p style={{ color: "#666" }}>
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <button onClick={() => window.location.reload()}>Reload page</button>
        </div>
      );
    }
    return this.props.children;
  }
}

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
  if (route.type === "funding-model-builder") {
    return <FundingModelBuilder />;
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
    <ErrorBoundary>
      <Root />
    </ErrorBoundary>
  </React.StrictMode>
);
