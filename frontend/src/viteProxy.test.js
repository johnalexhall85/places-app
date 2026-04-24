import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("vite proxy wiring", () => {
  it("proxies /api requests to the backend in dev and preview", () => {
    const currentDir = dirname(fileURLToPath(import.meta.url));
    const configPath = resolve(currentDir, "../vite.config.js");
    const configSource = readFileSync(configPath, "utf8");

    expect(configSource).toContain('"/api"');
    expect(configSource).toContain('target: backendTarget');
    expect(configSource).toContain("server:");
    expect(configSource).toContain("preview:");
  });

  it("preserves the CDC funding /api prefix in the demo nginx proxy", () => {
    const currentDir = dirname(fileURLToPath(import.meta.url));
    const nginxConfigPath = resolve(currentDir, "../../infra/nginx/places-demo.conf");
    const nginxConfigSource = readFileSync(nginxConfigPath, "utf8");

    expect(nginxConfigSource).toContain("location /api/cdc/funding/");
    expect(nginxConfigSource).toContain("proxy_pass http://127.0.0.1:8000;");
  });
});
