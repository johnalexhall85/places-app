import "leaflet/dist/leaflet.css";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { applyDocumentBranding } from "./branding/pdoBrand";
import { API_BASE } from "./config/apiBase";
import DemoAccessGate from "./demoAccess/DemoAccessGate";
import { installDemoAccessFetchCredentials } from "./demoAccess/api";
import CdcStateFundingProfile from "./pages/CdcStateFundingProfile";
import DemoAccessAdmin from "./pages/DemoAccessAdmin";
import FundingModelBuilder from "./pages/FundingModelBuilder";
import ProfileCounty from "./pages/ProfileCounty";
import ProfileTract from "./pages/ProfileTract";
import "./index.css";
import { resolveRoute } from "./utils/routeResolver";

installDemoAccessFetchCredentials(API_BASE);

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
  applyDocumentBranding();
  const pathname = window.location.pathname;
  if (/^\/demo-access-admin\/?$/i.test(pathname)) {
    return <DemoAccessAdmin />;
  }
  let routedPage = null;
  if (/^\/taggs\/funding-profile\/?$/i.test(pathname)) {
    const params = new URLSearchParams(window.location.search);
    routedPage = <CdcStateFundingProfile stateCode={params.get("state") ?? ""} />;
    return <DemoAccessGate>{routedPage}</DemoAccessGate>;
  }
  const route = resolveRoute(window.location.pathname);
  if (route.type === "cdc-state-funding-profile") {
    routedPage = <CdcStateFundingProfile stateCode={route.id} />;
  } else if (route.type === "funding-model-builder") {
    routedPage = <FundingModelBuilder />;
  } else if (route.type === "profile-county") {
    routedPage = <ProfileCounty countyFips={route.id} />;
  } else if (route.type === "profile-tract") {
    routedPage = <ProfileTract tractGeoid={route.id} />;
  } else {
    routedPage = <App />;
  }
  return <DemoAccessGate>{routedPage}</DemoAccessGate>;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <Root />
    </ErrorBoundary>
  </React.StrictMode>
);
