// ==UserScript==
// @name         OENY HRSZ shape-zip downloader
// @namespace    https://gunicsba.github.io/
// @version      0.8
// @description  Downloads hrsz:foldreszlet around the current OENY map center.
// @match        https://www.oeny.hu/oeny/hrsz-kereso/*
// @grant        none
// @license      WTFPL
// ==/UserScript==

(function () {
  'use strict';

  const WFS_BASE = 'https://www.oeny.hu/hk-geoserver/hrsz/wfs';
  const TYPE_NAME = 'hrsz:foldreszlet';
  const CONVERTER_URL = 'https://gunicsba.github.io/shape_kml.html';

  const DEFAULT_SIZE_KM = 2;
  const MAX_CENTER_JITTER_M = 250;

  let lastCenter = null;
  let statusEl;
  let sizeKmInput;

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

  function parseBbox(input) {
    const parts = String(input)
      .split(',')
      .map(x => x.trim())
      .filter(Boolean);

    if (parts.length < 4) {
      throw new Error('Invalid BBOX');
    }

    const nums = parts.slice(0, 4).map(Number);

    if (nums.some(n => !Number.isFinite(n))) {
      throw new Error('Invalid BBOX numbers');
    }

    return {
      minx: nums[0],
      miny: nums[1],
      maxx: nums[2],
      maxy: nums[3]
    };
  }

  function randomOffset(maxMeters) {
    return (Math.random() * 2 - 1) * maxMeters;
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

  function getSizeKm() {
    const value = Number(sizeKmInput?.value);

    if (!Number.isFinite(value) || value <= 0) {
      return DEFAULT_SIZE_KM;
    }

    return value;
  }

  // ----------------------------------------------------
  // BBOX capture
  // ----------------------------------------------------

  function captureFromText(raw) {
    try {
      const text = String(raw || '');

      if (!text || !/BBOX=/i.test(text)) {
        return false;
      }

      const bboxMatch = text.match(/[?&]BBOX=([^&]+)/i);

      if (!bboxMatch) {
        return false;
      }

      const bboxText = decodeSafe(bboxMatch[1]);
      const box = parseBbox(bboxText);

      const cx = (box.minx + box.maxx) / 2;
      const cy = (box.miny + box.maxy) / 2;

      lastCenter = {
        x: cx,
        y: cy
      };

      setStatus(
        `Center: ${cx.toFixed(1)}, ${cy.toFixed(1)}`
      );

      return true;

    } catch {
      return false;
    }
  }

  // ----------------------------------------------------
  // Shape download
  // ----------------------------------------------------

  function downloadShape() {
    try {

      if (!lastCenter) {
        setStatus(
          'No map center yet. Move or zoom the map first.',
          true
        );
        return;
      }

      const sizeKm = getSizeKm();
      const sizeM = sizeKm * 1000;
      const half = sizeM / 2;

      // Small independent X/Y center offset.
      // The requested BBOX size itself remains unchanged.
      const offsetX = randomOffset(MAX_CENTER_JITTER_M);
      const offsetY = randomOffset(MAX_CENTER_JITTER_M);

      const centerX = lastCenter.x;
      const centerY = lastCenter.y;

      const minx = centerX - half + offsetX;
      const miny = centerY - half;
      const maxx = centerX + half + offsetY;
      const maxy = centerY + half;

      const bbox =
        `${minx.toFixed(3)},` +
        `${miny.toFixed(3)},` +
        `${maxx.toFixed(3)},` +
        `${maxy.toFixed(3)},` +
        `EPSG:23700`;

      const url = buildWfsUrl(bbox);

      setStatus(
        `${sizeKm} × ${sizeKm} km | offset X ${offsetX.toFixed(0)} m, Y ${offsetY.toFixed(0)} m`
      );

      window.open(url, '_blank', 'noopener');

    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  }

  // ----------------------------------------------------
  // Network/resource monitoring
  // ----------------------------------------------------

  function hookFetch() {
    const originalFetch = window.fetch;

    if (!originalFetch) return;

    window.fetch = function (...args) {
      try {
        const input = args[0];

        const url =
          typeof input === 'string'
            ? input
            : input?.url;

        if (url) {
          captureFromText(url);
        }

      } catch {}

      return originalFetch.apply(this, args);
    };
  }

  function hookXhr() {
    const originalOpen = XMLHttpRequest.prototype.open;

    XMLHttpRequest.prototype.open =
      function (method, url, ...rest) {

        try {
          if (url) {
            captureFromText(url);
          }
        } catch {}

        return originalOpen.call(
          this,
          method,
          url,
          ...rest
        );
      };
  }

  function hookImgSrc() {

    const originalSetAttribute =
      Element.prototype.setAttribute;

    Element.prototype.setAttribute =
      function (name, value) {

        try {

          if (
            this instanceof HTMLImageElement &&
            String(name).toLowerCase() === 'src' &&
            value
          ) {
            captureFromText(value);
          }

        } catch {}

        return originalSetAttribute.apply(
          this,
          arguments
        );
      };


    const descriptor =
      Object.getOwnPropertyDescriptor(
        HTMLImageElement.prototype,
        'src'
      );

    if (descriptor && descriptor.set) {

      Object.defineProperty(
        HTMLImageElement.prototype,
        'src',
        {
          configurable: true,
          enumerable: descriptor.enumerable,

          get: descriptor.get,

          set(value) {

            try {
              if (value) {
                captureFromText(value);
              }
            } catch {}

            return descriptor.set.call(
              this,
              value
            );
          }
        }
      );
    }
  }

  function scanExistingDom() {

    document
      .querySelectorAll(
        'img[src], iframe[src], source[src]'
      )
      .forEach(el => {

        const src =
          el.getAttribute('src');

        if (src) {
          captureFromText(src);
        }

      });
  }

  function observeDom() {

    const observer =
      new MutationObserver(mutations => {

        for (const mutation of mutations) {

          if (mutation.type === 'attributes') {

            const value =
              mutation.target.getAttribute(
                mutation.attributeName
              );

            if (value) {
              captureFromText(value);
            }
          }

          if (mutation.type === 'childList') {

            mutation.addedNodes.forEach(node => {

              if (!(node instanceof Element)) {
                return;
              }

              node
                .querySelectorAll?.('[src],[href]')
                .forEach(el => {

                  const src =
                    el.getAttribute('src');

                  const href =
                    el.getAttribute('href');

                  if (src) {
                    captureFromText(src);
                  }

                  if (href) {
                    captureFromText(href);
                  }

                });
            });
          }
        }
      });

    observer.observe(
      document.documentElement,
      {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: [
          'src',
          'href',
          'data-src',
          'style'
        ]
      }
    );
  }

  function observePerformance() {

    if (!('PerformanceObserver' in window)) {
      return;
    }

    try {

      const observer =
        new PerformanceObserver(list => {

          for (
            const entry
            of list.getEntries()
          ) {

            if (entry.name) {
              captureFromText(entry.name);
            }
          }

        });

      observer.observe({
        entryTypes: ['resource']
      });

    } catch {}
  }

  // ----------------------------------------------------
  // UI
  // ----------------------------------------------------

  function addPanel() {

    const host =
      createEl('div', {}, {

        position: 'fixed',
        right: '12px',
        bottom: '12px',
        zIndex: '999999',

        width: '270px',

        background: '#111827',
        color: '#e5e7eb',

        border: '1px solid #374151',
        borderRadius: '12px',

        boxShadow:
          '0 10px 24px rgba(0,0,0,0.35)',

        padding: '12px',

        fontFamily:
          'system-ui, sans-serif',

        fontSize: '14px'
      });


    const title =
      createEl(
        'div',
        {
          textContent:
            'HRSZ shape-zip'
        },
        {
          fontWeight: '700',
          marginBottom: '8px'
        }
      );


    const layerInfo =
      createEl(
        'div',
        {
          textContent:
            'hrsz:foldreszlet'
        },
        {
          fontSize: '12px',
          color: '#9ca3af',
          marginBottom: '10px'
        }
      );


    const sizeLabel =
      createEl(
        'label',
        {
          textContent:
            'BBOX edge size (km)'
        },
        {
          display: 'block',
          fontSize: '12px',
          color: '#9ca3af',
          marginBottom: '4px'
        }
      );


    sizeKmInput =
      createEl(
        'input',
        {
          type: 'number',
          min: '0.1',
          max: '20',
          step: '0.1',
          value: String(DEFAULT_SIZE_KM)
        },
        {
          width: '100%',
          boxSizing: 'border-box',

          background: '#0b1220',
          color: '#e5e7eb',

          border:
            '1px solid #4b5563',

          borderRadius: '8px',

          padding: '8px',

          marginBottom: '10px'
        }
      );


    const downloadButton =
      createEl(
        'button',
        {
          textContent:
            'Download shape-zip'
        },
        {
          width: '100%',

          background: '#7c3aed',
          color: '#fff',

          border: 'none',
          borderRadius: '9px',

          padding: '10px',

          cursor: 'pointer',
          fontWeight: '700',

          marginBottom: '8px'
        }
      );

    downloadButton.addEventListener(
      'click',
      downloadShape
    );


    const converterButton =
      createEl(
        'button',
        {
          textContent:
            'Open EOV converter'
        },
        {
          width: '100%',

          background: '#334155',
          color: '#fff',

          border: 'none',
          borderRadius: '9px',

          padding: '10px',

          cursor: 'pointer',
          fontWeight: '700'
        }
      );

    converterButton.addEventListener(
      'click',
      () => {

        window.open(
          CONVERTER_URL,
          '_blank',
          'noopener'
        );

      }
    );


    statusEl =
      createEl(
        'div',
        {
          textContent:
            'Waiting for map center...'
        },
        {
          marginTop: '9px',
          fontSize: '11px',
          color: '#86efac'
        }
      );


    host.append(
      title,
      layerInfo,
      sizeLabel,
      sizeKmInput,
      downloadButton,
      converterButton,
      statusEl
    );

    document.body.appendChild(host);
  }

  // ----------------------------------------------------
  // Startup
  // ----------------------------------------------------

  function init() {

    addPanel();

    hookFetch();
    hookXhr();
    hookImgSrc();

    observeDom();
    observePerformance();

    scanExistingDom();

    setInterval(
      scanExistingDom,
      2000
    );

    setStatus(
      'Ready. Move or zoom the map.'
    );
  }


  if (
    document.readyState === 'loading'
  ) {

    document.addEventListener(
      'DOMContentLoaded',
      init
    );

  } else {

    init();
  }

})();