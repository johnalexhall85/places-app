# Figma Handoff from Frontend Code

This project includes an automated exporter that captures the current UI as high-resolution screens.

## Generate assets

From `frontend/`:

```bash
npm run figma:export
```

The command:

- starts Vite on `http://127.0.0.1:4173`
- mocks backend/geocoder responses for deterministic UI state
- captures desktop and mobile screens
- writes output to `frontend/figma-export/`

Files created:

- `01-overview-desktop.png`
- `02-search-desktop.png`
- `03-selected-desktop.png`
- `01-overview-mobile.png`
- `02-search-mobile.png`
- `03-selected-mobile.png`
- `manifest.json`

## Create the Figma file

1. Create a new Figma Design file.
2. Drag the PNGs from `frontend/figma-export/` onto the canvas.
3. Use each image as a base frame for redlining and component rebuild.

## Optional editable import (plugin workflow)

If you want editable layers generated from code:

1. Run your frontend normally (`npm run dev`) and open the app URL.
2. In Figma, run the `html.to.design` plugin.
3. Import the running URL (for example `http://localhost:5173`).

The plugin route gives editable layers, while PNGs are a stable visual baseline.
