// ==UserScript==
// @name         Geoshop shape-zip downloader
// @namespace    https://gunicsba.github.io/
// @version      0.2
// @description  Elkapja a geoshop.hu lefedettségi válaszát, és a földrészleteket EOV shape-zip fájlba menti.
// @match        https://geoshop.hu/*
// @match        https://www.geoshop.hu/*
// @match        https://map.geoshop.hu/*
// @run-at       document-start
// @grant        none
// @license      WTFPL
// ==/UserScript==

(function () {
  'use strict';

  const COVERAGE_PATH = '/api/coverage/';
  const CONVERTER_URL = 'https://gunicsba.github.io/shape_kml.html';

  const PRJ_EOV = 'PROJCS["HD72_EOV",GEOGCS["GCS_HD72",DATUM["D_Hungarian_1972",SPHEROID["GRS_1967",6378160,298.247167427]],PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]],PROJECTION["Hotine_Oblique_Mercator_Azimuth_Center"],PARAMETER["latitude_of_center",47.14439372222222],PARAMETER["longitude_of_center",19.04857177777778],PARAMETER["azimuth",90],PARAMETER["scale_factor",0.99993],PARAMETER["false_easting",650000],PARAMETER["false_northing",200000],UNIT["Meter",1]]';

  const PRODUCT_NAMES = {
    62: 'foldreszlet'
  };

  // Collected parcels, keyed by geoshop id, so repeated queries don't duplicate.
  const collected = new Map();

  let statusEl;
  let countEl;
  let keepInput;
  let downloadButton;
  let host;

  function createEl(tag, props = {}, style = {}) {
    const el = document.createElement(tag);
    Object.assign(el, props);
    Object.assign(el.style, style);
    return el;
  }

  function setStatus(msg, isError = false) {
    if (!statusEl) return;

    statusEl.textContent = msg;
    statusEl.style.color = isError ? '#fca5a5' : '#86efac';
  }

  function isCoverageUrl(url) {
    return String(url || '').includes(COVERAGE_PATH);
  }

  // ----------------------------------------------------
  // Response parsing
  // ----------------------------------------------------

  function splitGroup(group) {
    // "Törtel - belterület" -> settlement + location type
    const text = String(group || '').trim();
    const idx = text.lastIndexOf(' - ');

    if (idx < 0) {
      return { telepules: text, fekves: '' };
    }

    return {
      telepules: text.slice(0, idx).trim(),
      fekves: text.slice(idx + 3).trim()
    };
  }

  function toPolygons(geometry) {
    if (!geometry) return [];

    if (geometry.type === 'Polygon') return [geometry.coordinates];
    if (geometry.type === 'MultiPolygon') return geometry.coordinates;

    return [];
  }

  function parseCoverage(data) {
    if (!Array.isArray(data)) return [];

    const parcels = [];

    for (const product of data) {
      for (const item of product?.discreteProducts || []) {
        const feature = item?.coveredItem;
        const polygons = toPolygons(feature?.geometry);

        if (!polygons.length) continue;

        const props = feature.properties || {};
        const desc = props.description || {};
        const group = splitGroup(desc.itemGroupValue);

        parcels.push({
          id: String(props.id ?? `${desc.itemGroupValue}#${desc.itemDescription}`),
          productID: item.productID ?? props.productID ?? product.productID,
          hrsz: String(desc.itemDescription ?? ''),
          telepules: group.telepules,
          fekves: group.fekves,
          csoport: String(desc.itemGroupValue ?? ''),
          extra: String(desc.itemDescriptionExtra ?? ''),
          polygons
        });
      }
    }

    return parcels;
  }

  function handleCoverage(data) {
    const parcels = parseCoverage(data);

    if (!parcels.length) return;

    if (!keepInput || !keepInput.checked) {
      collected.clear();
    }

    for (const parcel of parcels) {
      collected.set(parcel.id, parcel);
    }

    const generalized = Array.isArray(data) && data.some(p => p?.generalized);
    const groups = [...new Set(parcels.map(p => p.csoport))].join(', ');

    ensurePanel();
    updateCount();
    setStatus(
      `${parcels.length} földrészlet elkapva (${groups})` +
      (generalized ? ' – a geoshop egyszerűsített geometriát küldött' : '')
    );
  }

  // ----------------------------------------------------
  // Network hooks (read-only, the site does the requests)
  // ----------------------------------------------------

  function hookFetch() {
    const originalFetch = window.fetch;

    if (!originalFetch) return;

    window.fetch = function (...args) {
      const promise = originalFetch.apply(this, args);

      try {
        const input = args[0];
        const url = typeof input === 'string' ? input : input?.url;

        if (isCoverageUrl(url)) {
          promise
            .then(res => res.clone().json())
            .then(handleCoverage)
            .catch(() => {});
        }
      } catch {}

      return promise;
    };
  }

  function hookXhr() {
    const originalOpen = XMLHttpRequest.prototype.open;

    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      try {
        if (isCoverageUrl(url)) {
          this.addEventListener('load', () => {
            try {
              const data =
                this.responseType === 'json'
                  ? this.response
                  : JSON.parse(this.responseText);

              handleCoverage(data);
            } catch {}
          });
        }
      } catch {}

      return originalOpen.call(this, method, url, ...rest);
    };
  }

  // ----------------------------------------------------
  // Geometry helpers
  // ----------------------------------------------------

  function signedArea(ring) {
    let sum = 0;

    for (let i = 0; i < ring.length - 1; i++) {
      sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    }

    return sum / 2;
  }

  function closeRing(ring) {
    const first = ring[0];
    const last = ring[ring.length - 1];

    if (first[0] === last[0] && first[1] === last[1]) return ring;

    return [...ring, first];
  }

  // Shapefile wants outer rings clockwise, holes counter-clockwise.
  function orientRing(ring, outer) {
    const closed = closeRing(ring);
    const clockwise = signedArea(closed) < 0;

    return clockwise === outer ? closed : closed.slice().reverse();
  }

  function parcelRings(parcel) {
    const rings = [];

    for (const polygon of parcel.polygons) {
      polygon.forEach((ring, i) => {
        if (ring.length >= 3) rings.push(orientRing(ring, i === 0));
      });
    }

    return rings;
  }

  function parcelArea(parcel) {
    let area = 0;

    for (const polygon of parcel.polygons) {
      polygon.forEach((ring, i) => {
        const a = Math.abs(signedArea(closeRing(ring)));
        area += i === 0 ? a : -a;
      });
    }

    return area;
  }

  function ringsBbox(rings) {
    const box = [Infinity, Infinity, -Infinity, -Infinity];

    for (const ring of rings) {
      for (const [x, y] of ring) {
        box[0] = Math.min(box[0], x);
        box[1] = Math.min(box[1], y);
        box[2] = Math.max(box[2], x);
        box[3] = Math.max(box[3], y);
      }
    }

    return box;
  }

  // ----------------------------------------------------
  // Shapefile writer (Polygon, type 5)
  // ----------------------------------------------------

  function buildShpShx(parcels) {
    const records = parcels.map(parcelRings);

    const contentBytes = records.map(rings => {
      const points = rings.reduce((n, r) => n + r.length, 0);
      return 44 + 4 * rings.length + 16 * points;
    });

    const shpLength = 100 + contentBytes.reduce((n, b) => n + 8 + b, 0);
    const shxLength = 100 + 8 * records.length;

    const shp = new DataView(new ArrayBuffer(shpLength));
    const shx = new DataView(new ArrayBuffer(shxLength));

    const allBox = ringsBbox(records.flat());

    for (const [view, length] of [[shp, shpLength], [shx, shxLength]]) {
      view.setInt32(0, 9994, false);
      view.setInt32(24, length / 2, false);
      view.setInt32(28, 1000, true);
      view.setInt32(32, 5, true);
      allBox.forEach((v, i) => view.setFloat64(36 + i * 8, v, true));
    }

    let offset = 100;

    records.forEach((rings, i) => {
      const box = ringsBbox(rings);
      const points = rings.reduce((n, r) => n + r.length, 0);

      shx.setInt32(100 + i * 8, offset / 2, false);
      shx.setInt32(104 + i * 8, contentBytes[i] / 2, false);

      shp.setInt32(offset, i + 1, false);
      shp.setInt32(offset + 4, contentBytes[i] / 2, false);
      offset += 8;

      shp.setInt32(offset, 5, true);
      box.forEach((v, j) => shp.setFloat64(offset + 4 + j * 8, v, true));
      shp.setInt32(offset + 36, rings.length, true);
      shp.setInt32(offset + 40, points, true);
      offset += 44;

      let start = 0;
      for (const ring of rings) {
        shp.setInt32(offset, start, true);
        offset += 4;
        start += ring.length;
      }

      for (const ring of rings) {
        for (const [x, y] of ring) {
          shp.setFloat64(offset, x, true);
          shp.setFloat64(offset + 8, y, true);
          offset += 16;
        }
      }
    });

    return {
      shp: new Uint8Array(shp.buffer),
      shx: new Uint8Array(shx.buffer)
    };
  }

  // ----------------------------------------------------
  // DBF writer (dBase III, UTF-8 text + .cpg)
  // ----------------------------------------------------

  const DBF_FIELDS = [
    { name: 'hrsz', type: 'C', length: 30, value: p => p.hrsz },
    { name: 'telepules', type: 'C', length: 60, value: p => p.telepules },
    { name: 'fekves', type: 'C', length: 30, value: p => p.fekves },
    { name: 'terulet_m2', type: 'N', length: 14, decimals: 1, value: p => parcelArea(p) },
    { name: 'csoport', type: 'C', length: 100, value: p => p.csoport },
    { name: 'extra', type: 'C', length: 100, value: p => p.extra },
    { name: 'geoshop_id', type: 'C', length: 40, value: p => p.id },
    { name: 'product_id', type: 'N', length: 6, decimals: 0, value: p => p.productID }
  ];

  const encoder = new TextEncoder();

  // Truncate to a byte length without cutting a UTF-8 sequence in half.
  function utf8Fit(text, maxBytes) {
    let bytes = encoder.encode(text);

    if (bytes.length <= maxBytes) return bytes;

    let end = maxBytes;
    while (end > 0 && (bytes[end] & 0xc0) === 0x80) end--;

    return bytes.slice(0, end);
  }

  function buildDbf(parcels) {
    const headerSize = 32 + 32 * DBF_FIELDS.length + 1;
    const recordSize = 1 + DBF_FIELDS.reduce((n, f) => n + f.length, 0);
    const out = new Uint8Array(headerSize + recordSize * parcels.length + 1);
    const view = new DataView(out.buffer);
    const now = new Date();

    out[0] = 0x03;
    out[1] = now.getFullYear() - 1900;
    out[2] = now.getMonth() + 1;
    out[3] = now.getDate();
    view.setUint32(4, parcels.length, true);
    view.setUint16(8, headerSize, true);
    view.setUint16(10, recordSize, true);

    DBF_FIELDS.forEach((field, i) => {
      const base = 32 + i * 32;
      out.set(encoder.encode(field.name), base);
      out[base + 11] = field.type.charCodeAt(0);
      out[base + 16] = field.length;
      out[base + 17] = field.decimals || 0;
    });

    out[headerSize - 1] = 0x0d;

    let offset = headerSize;

    for (const parcel of parcels) {
      out.fill(0x20, offset, offset + recordSize);
      offset += 1;

      for (const field of DBF_FIELDS) {
        const raw = field.value(parcel);
        let bytes;

        if (field.type === 'N') {
          const num = Number(raw);
          const text = Number.isFinite(num) ? num.toFixed(field.decimals || 0) : '';
          bytes = encoder.encode(text.padStart(field.length).slice(-field.length));
        } else {
          bytes = utf8Fit(String(raw ?? ''), field.length);
        }

        out.set(bytes, offset);
        offset += field.length;
      }
    }

    out[offset] = 0x1a;

    return out;
  }

  // ----------------------------------------------------
  // Minimal ZIP writer (stored, no compression)
  // ----------------------------------------------------

  const CRC_TABLE = (() => {
    const table = new Uint32Array(256);

    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      table[n] = c >>> 0;
    }

    return table;
  })();

  function crc32(bytes) {
    let crc = 0xffffffff;

    for (let i = 0; i < bytes.length; i++) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    }

    return (crc ^ 0xffffffff) >>> 0;
  }

  function buildZip(files) {
    const now = new Date();
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();

    const chunks = [];
    const central = [];
    let offset = 0;

    for (const file of files) {
      const name = encoder.encode(file.name);
      const data = file.data;
      const crc = crc32(data);

      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(10, dosTime, true);
      local.setUint16(12, dosDate, true);
      local.setUint32(14, crc, true);
      local.setUint32(18, data.length, true);
      local.setUint32(22, data.length, true);
      local.setUint16(26, name.length, true);

      const entry = new DataView(new ArrayBuffer(46));
      entry.setUint32(0, 0x02014b50, true);
      entry.setUint16(4, 20, true);
      entry.setUint16(6, 20, true);
      entry.setUint16(12, dosTime, true);
      entry.setUint16(14, dosDate, true);
      entry.setUint32(16, crc, true);
      entry.setUint32(20, data.length, true);
      entry.setUint32(24, data.length, true);
      entry.setUint16(28, name.length, true);
      entry.setUint32(42, offset, true);

      chunks.push(new Uint8Array(local.buffer), name, data);
      central.push(new Uint8Array(entry.buffer), name);

      offset += 30 + name.length + data.length;
    }

    const centralSize = central.reduce((n, c) => n + c.length, 0);

    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, files.length, true);
    end.setUint16(10, files.length, true);
    end.setUint32(12, centralSize, true);
    end.setUint32(16, offset, true);

    return new Blob(
      [...chunks, ...central, new Uint8Array(end.buffer)],
      { type: 'application/zip' }
    );
  }

  // ----------------------------------------------------
  // Shape download
  // ----------------------------------------------------

  function asciiName(text) {
    return String(text || '')
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^A-Za-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
  }

  function timestamp() {
    const d = new Date();
    const pad = n => String(n).padStart(2, '0');

    return (
      `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-` +
      `${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
    );
  }

  function downloadShape() {
    try {
      if (!collected.size) {
        setStatus('Még nincs földrészlet. Előbb rajzolj egy poligont a geoshop térképen.', true);
        return;
      }

      const parcels = [...collected.values()];
      const byProduct = new Map();

      for (const parcel of parcels) {
        const key = parcel.productID ?? 'x';
        if (!byProduct.has(key)) byProduct.set(key, []);
        byProduct.get(key).push(parcel);
      }

      const files = [];

      for (const [productID, list] of byProduct) {
        const base = PRODUCT_NAMES[productID] || `product_${productID}`;
        const { shp, shx } = buildShpShx(list);

        files.push(
          { name: `${base}.shp`, data: shp },
          { name: `${base}.shx`, data: shx },
          { name: `${base}.dbf`, data: buildDbf(list) },
          { name: `${base}.prj`, data: encoder.encode(PRJ_EOV) },
          { name: `${base}.cpg`, data: encoder.encode('UTF-8') }
        );
      }

      const settlements = [...new Set(parcels.map(p => asciiName(p.telepules)).filter(Boolean))];
      const place = settlements.length === 1 ? settlements[0] : settlements.length ? 'multi' : 'parcels';
      const fileName = `geoshop_${place}_${timestamp()}.zip`;

      const url = URL.createObjectURL(buildZip(files));
      const a = createEl('a', { href: url, download: fileName });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);

      setStatus(`${parcels.length} földrészlet mentve: ${fileName}`);

    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  // ----------------------------------------------------
  // UI
  // ----------------------------------------------------

  function updateCount() {
    if (!countEl) return;

    countEl.textContent = `Összegyűjtött földrészletek: ${collected.size}`;
    downloadButton.textContent = `Shape-zip letöltése (${collected.size})`;
  }

  function button(text, background, onClick) {
    const el = createEl(
      'button',
      { textContent: text },
      {
        width: '100%',
        background,
        color: '#fff',
        border: 'none',
        borderRadius: '9px',
        padding: '10px',
        cursor: 'pointer',
        fontWeight: '700',
        marginBottom: '8px'
      }
    );

    el.addEventListener('click', onClick);

    return el;
  }

  function addPanel() {
    host = createEl('div', {}, {
      position: 'fixed',
      right: '12px',
      bottom: '12px',
      zIndex: '999999',
      width: '270px',
      background: '#111827',
      color: '#e5e7eb',
      border: '1px solid #374151',
      borderRadius: '12px',
      boxShadow: '0 10px 24px rgba(0,0,0,0.35)',
      padding: '12px',
      fontFamily: 'system-ui, sans-serif',
      fontSize: '14px'
    });

    const title = createEl(
      'div',
      { textContent: 'Geoshop shape-zip' },
      { fontWeight: '700', marginBottom: '8px' }
    );

    countEl = createEl(
      'div',
      {},
      { fontSize: '12px', color: '#9ca3af', marginBottom: '8px' }
    );

    const keepLabel = createEl(
      'label',
      {},
      {
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '12px',
        color: '#9ca3af',
        marginBottom: '10px',
        cursor: 'pointer'
      }
    );

    keepInput = createEl('input', { type: 'checkbox', checked: true });
    keepLabel.append(keepInput, 'Gyűjtés több lekérdezésen át');

    downloadButton = button('Shape-zip letöltése', '#7c3aed', downloadShape);

    const clearButton = button('Törlés', '#475569', () => {
      collected.clear();
      updateCount();
      setStatus('Lista törölve.');
    });

    const converterButton = button('EOV konverter megnyitása', '#334155', () => {
      window.open(CONVERTER_URL, '_blank', 'noopener');
    });
    converterButton.style.marginBottom = '0';

    statusEl = createEl(
      'div',
      { textContent: 'Rajzolj egy poligont a geoshop térképen.' },
      { marginTop: '9px', fontSize: '11px', color: '#86efac' }
    );

    host.append(
      title,
      countEl,
      keepLabel,
      downloadButton,
      clearButton,
      converterButton,
      statusEl
    );

    document.body.appendChild(host);
    updateCount();
  }

  // The map may live in an iframe: there the panel only shows up once a response is caught.
  function ensurePanel() {
    if (host || !document.body) return;

    addPanel();
  }

  // ----------------------------------------------------
  // Startup
  // ----------------------------------------------------

  hookFetch();
  hookXhr();

  function init() {
    if (window.top === window.self || collected.size) {
      ensurePanel();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
