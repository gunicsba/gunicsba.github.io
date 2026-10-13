/* GitHub release downloads, read live from the GitHub API (no build step).
 *
 * Drop-in button:  <div class="gh-dl" data-repo="owner/repo" data-asset="\.exe$"></div>
 *   data-asset  regex for the file to offer (default: .exe or .zip)
 *   data-label  button text (default: "Download")
 * Shows the newest stable release that has a matching file, plus a "beta" link
 * when a newer pre-release has one. Falls back to the repo's releases page.
 *
 * Also exposes window.GH for pages that render their own layout (see /AOG/).
 */
(function () {
  const TTL = 10 * 60 * 1000; // sessionStorage cache, keeps us well under the 60 req/h anonymous API limit
  const inflight = {};

  function releases(repo) {
    if (inflight[repo]) return inflight[repo];
    const key = 'gh-releases:' + repo;
    try {
      const c = JSON.parse(sessionStorage.getItem(key));
      if (c && Date.now() - c.t < TTL) return (inflight[repo] = Promise.resolve(c.d));
    } catch (e) {}
    return (inflight[repo] = fetch(`https://api.github.com/repos/${repo}/releases?per_page=30`, {
      headers: { Accept: 'application/vnd.github+json' }
    })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('GitHub API ' + r.status)))
      .then(list => {
        const d = list.filter(r => !r.draft).map(r => ({
          tag: r.tag_name, pre: r.prerelease, date: r.published_at, url: r.html_url,
          assets: r.assets.map(a => ({ name: a.name, size: a.size, url: a.browser_download_url }))
        }));
        try { sessionStorage.setItem(key, JSON.stringify({ t: Date.now(), d })); } catch (e) {}
        return d;
      })
      .catch(e => { delete inflight[repo]; throw e; }));
  }

  const find = (rel, re) => rel.assets.find(a => re.test(a.name));

  // Newest release that has a matching file; pre-releases only when allowed.
  function pick(list, re, allowPre) {
    for (const rel of list) {
      if (rel.pre && !allowPre) continue;
      const asset = find(rel, re);
      if (asset) return { rel, asset };
    }
    return null;
  }

  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const mb = b => (b / 1048576).toFixed(1) + ' MB';
  const day = d => String(d).slice(0, 10);
  const ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>';

  function hydrate(root) {
    (root || document).querySelectorAll('.gh-dl[data-repo]').forEach(el => {
      const repo = el.dataset.repo;
      const re = new RegExp(el.dataset.asset || '\\.(exe|zip)$', 'i');
      const label = el.dataset.label || 'Download';
      const fallback = `<a class="gh-pre" href="https://github.com/${esc(repo)}/releases" target="_blank" rel="noopener">Releases ↗</a>`;
      el.innerHTML = '<span class="gh-meta">…</span>';
      releases(repo).then(list => {
        const stable = pick(list, re, false), newest = pick(list, re, true);
        const main = stable || newest;
        if (!main) { el.innerHTML = fallback; return; }
        let h = `<a class="gh-btn" href="${esc(main.asset.url)}" title="${esc(main.asset.name)}">${ICON}${esc(label)} ${esc(main.rel.tag)}</a>`
              + `<span class="gh-meta">${mb(main.asset.size)}</span>`;
        if (newest.rel !== main.rel)
          h += `<a class="gh-pre" href="${esc(newest.asset.url)}" title="${esc(newest.asset.name)}">beta ${esc(newest.rel.tag)}</a>`;
        el.innerHTML = h;
      }).catch(() => { el.innerHTML = fallback; });
    });
  }

  window.GH = { releases, pick, find, hydrate, esc, mb, day, ICON };
  hydrate();
})();
