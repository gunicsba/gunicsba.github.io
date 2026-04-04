// ==UserScript==
// @name         OENY HRSZ shape-zip downloader (compact)
// @namespace    https://gunicsba.github.io/
// @version      0.4
// @description  Compact downloader for hrsz:foldreszlet using the latest captured BBOX from OENY.
// @match        https://www.oeny.hu/oeny/hrsz-kereso/*
// @grant        none
// ==/UserScript==

(function () {
  'use strict';

  const WFS_BASE = 'https://www.oeny.hu/hk-geoserver/hrsz/wfs';
  const TYPE_NAME = 'hrsz:foldreszlet';
  const CONVERTER_URL = 'https://gunicsba.github.io/shape_kml.html';

  let lastBbox = '';
  let statusEl;

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

  function decodeSafe(v) {
    try {
      return decodeURIComponent(v);
    } catch {
      return v;
    }
  }

  function normalizeBbox(input) {
    const parts = String(input).split(',').map(x => x.trim()).filter(Boolean);
    if (parts.length !== 4 && parts.length !== 5) {
      throw new Error('Invalid BBOX');
    }

    const nums = parts.slice(0, 4).map(Number);
    if (nums.some(n => !Number.isFinite(n))) {
      throw new Error('Invalid BBOX numbers');
    }

    const tail = parts[4] || 'EPSG:23700';
    return `${nums[0]},${nums[1]},${nums[2]},${nums[3]},${tail}`;
  }

  function buildWfsUrl(bbox) {
    const params = new URLSearchParams({
      SERVICE: 'WFS',
      VERSION: '1.1.0',
      REQUEST: 'GetFeature',
      TYPENAME: TYPE_NAME,
      OUTPUTFORMAT: 'shape-zip',
      SRSNAME: 'EPSG:23700',
      BBOX: bbox
    });
    return `${WFS_BASE}?${params.toString()}`;
  }

  function captureFromText(raw) {
    try {
      const text = String(raw || '');
      if (!text || !/BBOX=/i.test(text)) return false;

      const bboxMatch = text.match(/[?&]BBOX=([^&]+)/i);
      if (!bboxMatch) return false;

      const bbox = decodeSafe(bboxMatch[1]);
      if (!bbox || bbox === lastBbox) return false;

      lastBbox = bbox;
      setStatus('BBOX captured');
      return true;
    } catch {
      return false;
    }
  }

  function downloadShape() {
    try {
      if (!lastBbox) {
        setStatus('No BBOX captured yet. Move or zoom the map first.', true);
        return;
      }

      const bbox = normalizeBbox(lastBbox);
      const url = buildWfsUrl(bbox);
      setStatus('Opening shape-zip...');
      window.open(url, '_blank', 'noopener');
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  function hookFetch() {
    const origFetch = window.fetch;
    if (!origFetch) return;

    window.fetch = function (...args) {
      try {
        const input = args[0];
        const rawUrl = typeof input === 'string' ? input : input?.url;
        if (rawUrl) captureFromText(rawUrl);
      } catch {}
      return origFetch.apply(this, args);
    };
  }

  function hookXhr() {
    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      try {
        if (url) captureFromText(url);
      } catch {}
      return origOpen.call(this, method, url, ...rest);
    };
  }

  function hookImgSrc() {
    const origSetAttribute = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function (name, value) {
      try {
        if (this instanceof HTMLImageElement && String(name).toLowerCase() === 'src' && value) {
          captureFromText(value);
        }
      } catch {}
      return origSetAttribute.apply(this, arguments);
    };

    const desc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
    if (desc && desc.set) {
      Object.defineProperty(HTMLImageElement.prototype, 'src', {
        configurable: true,
        enumerable: desc.enumerable,
        get: desc.get,
        set(value) {
          try {
            if (value) captureFromText(value);
          } catch {}
          return desc.set.call(this, value);
        }
      });
    }
  }

  function scanExistingDom() {
    document.querySelectorAll('img[src], iframe[src], source[src]').forEach(el => {
      const src = el.getAttribute('src');
      if (src) captureFromText(src);
    });
  }

  function observeDom() {
    const mo = new MutationObserver(mutations => {
      for (const m of mutations) {
        if (m.type === 'attributes') {
          const val = m.target.getAttribute(m.attributeName);
          if (val) captureFromText(val);
        }

        if (m.type === 'childList') {
          m.addedNodes.forEach(node => {
            if (!(node instanceof Element)) return;

            node.querySelectorAll?.('[src],[href]').forEach(el => {
              const src = el.getAttribute('src');
              const href = el.getAttribute('href');
              if (src) captureFromText(src);
              if (href) captureFromText(href);
            });
          });
        }
      }
    });

    mo.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['src', 'href', 'data-src', 'style']
    });
  }

  function observePerformance() {
    if (!('PerformanceObserver' in window)) return;
    try {
      const po = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.name) captureFromText(entry.name);
        }
      });
      po.observe({ entryTypes: ['resource'] });
    } catch {}
  }

  function addPanel() {
    const host = createEl('div', {}, {
      position: 'fixed',
      right: '12px',
      bottom: '12px',
      zIndex: '999999',
      width: '260px',
      background: '#111827',
      color: '#e5e7eb',
      border: '1px solid #374151',
      borderRadius: '12px',
      boxShadow: '0 10px 24px rgba(0,0,0,0.35)',
      padding: '12px',
      fontFamily: 'system-ui, sans-serif',
      fontSize: '14px'
    });

    const title = createEl('div', {
      textContent: 'HRSZ shape-zip'
    }, {
      fontWeight: '700',
      marginBottom: '10px'
    });

    const layerInfo = createEl('div', {
      textContent: 'Layer: hrsz:foldreszlet'
    }, {
      fontSize: '12px',
      color: '#9ca3af',
      marginBottom: '10px'
    });

    const btnDownload = createEl('button', {
      textContent: 'Download shape-zip'
    }, {
      width: '100%',
      background: '#7c3aed',
      color: '#fff',
      border: 'none',
      borderRadius: '10px',
      padding: '10px 12px',
      cursor: 'pointer',
      fontWeight: '700',
      marginBottom: '8px'
    });
    btnDownload.addEventListener('click', downloadShape);

    const btnConverter = createEl('button', {
      textContent: 'Open EOV converter'
    }, {
      width: '100%',
      background: '#334155',
      color: '#fff',
      border: 'none',
      borderRadius: '10px',
      padding: '10px 12px',
      cursor: 'pointer',
      fontWeight: '700'
    });
    btnConverter.addEventListener('click', () => {
      window.open(CONVERTER_URL, '_blank', 'noopener');
    });

    statusEl = createEl('div', {
      textContent: 'Waiting for BBOX...'
    }, {
      marginTop: '10px',
      fontSize: '12px',
      color: '#86efac'
    });

    host.append(title, layerInfo, btnDownload, btnConverter, statusEl);
    document.body.appendChild(host);
  }

  function init() {
    addPanel();
    hookFetch();
    hookXhr();
    hookImgSrc();
    observeDom();
    observePerformance();
    scanExistingDom();
    setInterval(scanExistingDom, 2000);
    setStatus('Ready. Move or zoom the map.');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();