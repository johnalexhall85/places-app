/*
 * Leaflet.heat, a tiny and fast heatmap plugin for Leaflet.
 * Source style: Leaflet.heat v0.2.x by Vladimir Agafonkin.
 * License: MIT
 * https://github.com/Leaflet/Leaflet.heat
 */

import L from "leaflet";

function simpleheat(canvas) {
  if (!(this instanceof simpleheat)) return new simpleheat(canvas);

  this._canvas = canvas = typeof canvas === "string" ? document.getElementById(canvas) : canvas;
  this._ctx = canvas.getContext("2d", { willReadFrequently: true });
  this._width = canvas.width;
  this._height = canvas.height;
  this._max = 1;
  this._data = [];
}

simpleheat.prototype = {
  defaultRadius: 25,
  defaultGradient: {
    0.4: "blue",
    0.6: "cyan",
    0.7: "lime",
    0.8: "yellow",
    1.0: "red",
  },

  data(data) {
    this._data = data;
    return this;
  },

  max(max) {
    this._max = max;
    return this;
  },

  add(point) {
    this._data.push(point);
    return this;
  },

  clear() {
    this._data = [];
    return this;
  },

  radius(radius, blur) {
    blur = blur === undefined ? 15 : blur;

    const circle = this._circle = document.createElement("canvas");
    const context = circle.getContext("2d");
    const r2 = this._r = radius + blur;

    circle.width = circle.height = r2 * 2;
    context.shadowOffsetX = context.shadowOffsetY = r2 * 2;
    context.shadowBlur = blur;
    context.shadowColor = "black";

    context.beginPath();
    context.arc(-r2, -r2, radius, 0, Math.PI * 2, true);
    context.closePath();
    context.fill();

    return this;
  },

  resize() {
    this._width = this._canvas.width;
    this._height = this._canvas.height;
  },

  gradient(gradient) {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    const linearGradient = context.createLinearGradient(0, 0, 0, 256);

    canvas.width = 1;
    canvas.height = 256;

    for (const key in gradient) {
      linearGradient.addColorStop(Number(key), gradient[key]);
    }

    context.fillStyle = linearGradient;
    context.fillRect(0, 0, 1, 256);

    this._grad = context.getImageData(0, 0, 1, 256).data;

    return this;
  },

  draw(minOpacity) {
    if (!this._circle) this.radius(this.defaultRadius);
    if (!this._grad) this.gradient(this.defaultGradient);

    const context = this._ctx;

    context.clearRect(0, 0, this._width, this._height);

    for (let index = 0, len = this._data.length; index < len; index += 1) {
      const point = this._data[index];
      context.globalAlpha = Math.max(point[2] / this._max, minOpacity || 0.05);
      context.drawImage(this._circle, point[0] - this._r, point[1] - this._r);
    }

    const colored = context.getImageData(0, 0, this._width, this._height);
    this._colorize(colored.data, this._grad);
    context.putImageData(colored, 0, 0);

    return this;
  },

  _colorize(pixels, gradient) {
    for (let index = 3, len = pixels.length; index < len; index += 4) {
      const gradientIndex = pixels[index] * 4;
      if (!gradientIndex) continue;
      pixels[index - 3] = gradient[gradientIndex];
      pixels[index - 2] = gradient[gradientIndex + 1];
      pixels[index - 1] = gradient[gradientIndex + 2];
    }
  },
};

L.HeatLayer = (L.Layer ? L.Layer : L.Class).extend({
  options: {
    minOpacity: 0.05,
    maxZoom: 18,
    radius: 25,
    blur: 15,
    max: 1.0,
    pane: "overlayPane",
  },

  initialize(latlngs, options) {
    this._latlngs = latlngs || [];
    L.setOptions(this, options);
  },

  setLatLngs(latlngs) {
    this._latlngs = latlngs || [];
    return this.redraw();
  },

  addLatLng(latlng) {
    this._latlngs.push(latlng);
    return this.redraw();
  },

  setOptions(options) {
    L.setOptions(this, options);
    if (this._heat) {
      this._updateOptions();
    }
    return this.redraw();
  },

  redraw() {
    if (!this._heat || this._frame || !this._map || !this._map._loaded) return this;
    this._frame = L.Util.requestAnimFrame(this._redraw, this);
    return this;
  },

  onAdd(map) {
    this._map = map;

    if (!this._canvas) {
      this._initCanvas();
    }

    const pane = this.getPane ? this.getPane() : map.getPane(this.options.pane);
    pane.appendChild(this._canvas);

    map.on("moveend", this._reset, this);
    if (map.options.zoomAnimation && L.Browser.any3d) {
      map.on("zoomanim", this._animateZoom, this);
    }

    this._reset();
  },

  onRemove(map) {
    const pane = this.getPane ? this.getPane() : map.getPane(this.options.pane);
    if (this._canvas && pane && this._canvas.parentNode === pane) {
      pane.removeChild(this._canvas);
    }

    map.off("moveend", this._reset, this);
    if (map.options.zoomAnimation && L.Browser.any3d) {
      map.off("zoomanim", this._animateZoom, this);
    }
  },

  addTo(map) {
    map.addLayer(this);
    return this;
  },

  _initCanvas() {
    const canvas = this._canvas = L.DomUtil.create("canvas", "leaflet-heatmap-layer leaflet-layer");
    const size = this._map.getSize();

    canvas.width = size.x;
    canvas.height = size.y;

    const animated = this._map.options.zoomAnimation && L.Browser.any3d;
    L.DomUtil.addClass(canvas, `leaflet-zoom-${animated ? "animated" : "hide"}`);

    this._heat = simpleheat(canvas);
    this._updateOptions();
  },

  _updateOptions() {
    this._heat.radius(this.options.radius || this._heat.defaultRadius, this.options.blur);
    if (this.options.gradient) {
      this._heat.gradient(this.options.gradient);
    }
    if (this.options.max) {
      this._heat.max(this.options.max);
    }
  },

  _reset() {
    const topLeft = this._map.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(this._canvas, topLeft);

    const size = this._map.getSize();
    if (this._heat._width !== size.x) {
      this._canvas.width = this._heat._width = size.x;
    }
    if (this._heat._height !== size.y) {
      this._canvas.height = this._heat._height = size.y;
    }

    this._redraw();
  },

  _redraw() {
    if (!this._map) return;

    const data = [];
    const radius = this._heat._r;
    const size = this._map.getSize();
    const bounds = new L.Bounds(
      L.point([-radius, -radius]),
      size.add([radius, radius])
    );
    const max = this.options.max === undefined ? 1 : this.options.max;
    const maxZoom = this.options.maxZoom === undefined
      ? this._map.getMaxZoom()
      : this.options.maxZoom;
    const zoom = this._map.getZoom();
    const scale = 1 / Math.pow(2, Math.max(0, Math.min(maxZoom - zoom, 12)));
    const cellSize = radius / 2;
    const grid = [];
    const mapPanePos = this._map._getMapPanePos();
    const offsetX = mapPanePos.x % cellSize;
    const offsetY = mapPanePos.y % cellSize;

    for (let index = 0, len = this._latlngs.length; index < len; index += 1) {
      const input = this._latlngs[index];
      const lat = Array.isArray(input) ? Number(input[0]) : Number(input?.lat);
      const lng = Array.isArray(input) ? Number(input[1]) : Number(input?.lng ?? input?.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        continue;
      }

      const point = this._map.latLngToContainerPoint([lat, lng]);
      if (!bounds.contains(point)) {
        continue;
      }

      const x = Math.floor((point.x - offsetX) / cellSize) + 2;
      const y = Math.floor((point.y - offsetY) / cellSize) + 2;
      const intensity = Array.isArray(input)
        ? Number(input[2])
        : Number(input?.alt);
      const value = (Number.isFinite(intensity) ? intensity : 1) * scale;

      let row = grid[y];
      if (!row) {
        row = grid[y] = [];
      }

      const cell = row[x];
      if (!cell) {
        row[x] = [point.x, point.y, value];
      } else {
        cell[0] = ((cell[0] * cell[2]) + (point.x * value)) / (cell[2] + value);
        cell[1] = ((cell[1] * cell[2]) + (point.y * value)) / (cell[2] + value);
        cell[2] += value;
      }
    }

    for (let y = 0, yLen = grid.length; y < yLen; y += 1) {
      const row = grid[y];
      if (!row) continue;
      for (let x = 0, xLen = row.length; x < xLen; x += 1) {
        const cell = row[x];
        if (!cell) continue;
        data.push([
          Math.round(cell[0]),
          Math.round(cell[1]),
          Math.min(cell[2], max),
        ]);
      }
    }

    this._heat.data(data).draw(this.options.minOpacity);
    this._frame = null;
  },

  _animateZoom(event) {
    const scale = this._map.getZoomScale(event.zoom);
    const offset = this._map
      ._latLngBoundsToNewLayerBounds(this._map.getBounds(), event.zoom, event.center)
      .min;
    L.DomUtil.setTransform(this._canvas, offset, scale);
  },
});

L.heatLayer = function heatLayer(latlngs, options) {
  return new L.HeatLayer(latlngs, options);
};

export default L.heatLayer;
