import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const backendTarget = process.env.VITE_BACKEND_ORIGIN || "http://localhost:8000";
const proxiedBackendPaths = [
  "/api",
  "/funding",
  "/states",
  "/measures",
  "/meta",
  "/counties",
  "/geojson",
  "/acs-nmf",
  "/svi",
  "/hpsa",
  "/history",
  "/assistant",
  "/profiles",
];

const backendProxy = proxiedBackendPaths.reduce((acc, path) => {
  acc[path] = {
    target: backendTarget,
    changeOrigin: true,
  };
  return acc;
}, {});

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: backendProxy,
  },
  preview: {
    proxy: backendProxy,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.{test,spec}.{js,jsx,ts,tsx}"],
    setupFiles: "./src/test/setup.js",
  },
});
