// librarycard homepage: search, source detail and data preview over the read-only /api.
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u ?? "")) ? u : "#");
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const DOMAINS = [
    ["elections", "Elections"], ["politics_legislation", "Legislation"], ["demographics", "Demographics"],
    ["income_poverty", "Income & poverty"], ["labor", "Labor"], ["economy", "Economy"], ["housing", "Housing"],
    ["health", "Health"], ["education", "Education"], ["government_spending", "Spending"],
    ["disasters_emergency", "Disasters"], ["environment_climate", "Climate"],
  ];
  const GRAN = { congressional_district: "cong. district", block_group: "block group", state_legislative_district: "state leg. district",
    county_subdivision: "county subdivision", school_district: "school district", census_region: "region", census_division: "division" };
  let domain = "";
  let lastResults = [];

  async function api(path, opts) {
    const r = await fetch(path, opts);
    return r.json();
  }

  // ------------------------------------------------------------ copy buttons
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-copy]");
    if (!b) return;
    try {
      await navigator.clipboard.writeText(b.dataset.copy);
      const t = b.textContent;
      b.textContent = "Copied";
      setTimeout(() => (b.textContent = t), 1400);
    } catch {
      const code = b.parentElement.querySelector("code");
      if (code) window.getSelection().selectAllChildren(code);
    }
  });

  // ------------------------------------------------------------ search
  function stamp(r) {
    if (r.fetchable) return '<span class="stamp ok">Fetchable</span>';
    if (r.access_method === "restricted") return '<span class="stamp warn">Listed only</span>';
    if (r.status === "quarantined" || r.status === "retired") return `<span class="stamp bad">${esc(r.status)}</span>`;
    return '<span class="stamp info">Via publisher</span>';
  }
  function years(tr) {
    const s = String(tr.start).slice(0, 4);
    const e = tr.end ? String(tr.end).slice(0, 4) : "present";
    return s === e ? s : `${s}–${e}`;
  }
  function card(r) {
    const gran = r.geographic_granularity.filter((g) => !["person", "household", "establishment", "other"].includes(g))
      .slice(0, 4).map((g) => GRAN[g] || g.replace(/_/g, " ")).join(", ");
    return `<button class="catcard" type="button" data-id="${esc(r.id)}" aria-label="${esc(r.name)}">
      <div class="callno"><span>${esc(r.id)}</span>${stamp(r)}</div>
      <h3>${esc(r.name)}</h3>
      <p class="pub">${esc(r.publisher)}</p>
      <p class="desc">${esc(r.description)}</p>
      <p class="meta">${esc(years(r.time_range))} · ${esc(gran || "—")} · ${esc(r.caveat_count)} caveats</p>
    </button>`;
  }
  async function runSearch() {
    const q = $("#q").value.trim();
    const geo = $("#geo").value;
    const p = new URLSearchParams({ q, limit: "50" });
    if (geo) p.set("geography", geo);
    if (domain) p.set("domain", domain);
    const out = await api(`/api/search?${p}`);
    const res = $("#results");
    if (out.error) { res.innerHTML = `<p class="empty">${esc(out.error)}</p>`; return; }
    lastResults = out.results;
    res.innerHTML = out.results.length ? out.results.map(card).join("")
      : `<p class="empty">Nothing matched. Try fewer words, or <a href="https://github.com/lincolnq/librarycard/issues/new?template=data-request.yml">request this data</a>.</p>`;
    try { history.replaceState(null, "", q ? `?q=${encodeURIComponent(q)}${location.hash}` : `/${location.hash}`); } catch {}
  }
  let timer;
  $("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(runSearch, 220); });
  $("#geo").addEventListener("change", runSearch);
  $("#search-form").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });
  $("#domain-chips").innerHTML = [["", "All topics"], ...DOMAINS]
    .map(([v, l]) => `<button type="button" class="chip" data-domain="${v}" aria-pressed="${v === "" ? "true" : "false"}">${esc(l)}</button>`).join("");
  $("#domain-chips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    domain = b.dataset.domain;
    for (const c of $("#domain-chips").children) c.setAttribute("aria-pressed", c === b ? "true" : "false");
    runSearch();
  });
  $("#results").addEventListener("click", (e) => {
    const c = e.target.closest(".catcard");
    if (c) location.hash = `source-${c.dataset.id}`;
  });

  // ------------------------------------------------------------ detail
  async function showDetail(id) {
    const sec = $("#detail");
    const inner = $("#detail-inner");
    sec.hidden = false;
    inner.innerHTML = `<p class="empty">Loading ${esc(id)}…</p>`;
    sec.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    const d = await api(`/api/source/${encodeURIComponent(id)}`);
    if (d.error) { inner.innerHTML = `<p class="empty">${esc(d.error)}</p>`; return; }
    const lic = d.license;
    const cov = d.coverage;
    const fp = d.fetch_parameters;
    const how = d.how_to_access;
    inner.innerHTML = `
      <div class="detail-head">
        <a class="back" href="#search">← Back to results</a>
        <div class="callno mono-label"><span>${esc(d.id)}</span>${stamp({ ...d, access_method: d.access.method })}</div>
        <h2>${esc(d.name)}</h2>
        <p class="lede-small">${esc(d.publisher.name)} · <a href="${esc(safeUrl(d.homepage))}" rel="noopener">publisher page</a></p>
      </div>
      <div class="detail-grid">
        <section>
          <p>${esc(d.description)}</p>
          <h3>Read before using</h3>
          <ul class="caveats">${d.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
          <h3>Key variables</h3>
          <ul class="vars">${d.key_variables.map((v) => `<li><code>${esc(v.name)}</code>${v.unit ? ` <span class="mono-label">(${esc(v.unit)})</span>` : ""}: ${esc(v.definition)}</li>`).join("")}</ul>
        </section>
        <section>
          <h3>Coverage</h3>
          <dl class="kv">
            <dt>Where</dt><dd>${esc(cov.geography)}</dd>
            <dt>Finest unit</dt><dd>${esc(cov.geographic_granularity.map((g) => GRAN[g] || g.replace(/_/g, " ")).join(", "))}</dd>
            <dt>Years</dt><dd>${esc(years(cov.time_range))}${cov.time_range.notes ? ` <span class="mono-label">· ${esc(cov.time_range.notes)}</span>` : ""}</dd>
            <dt>Updated</dt><dd>${esc(d.update.cadence)}; ${esc(d.update.expected_lag)}</dd>
            <dt>Each row</dt><dd>${esc(cov.unit_of_observation)}</dd>
          </dl>
          <h3>License</h3>
          <dl class="kv">
            <dt>Terms</dt><dd><a href="${esc(safeUrl(lic.url))}" rel="noopener">${esc(lic.name)}</a></dd>
            <dt>Reuse</dt><dd>${lic.redistribution === "allowed" ? "Redistributable" : "Link to publisher (not mirrored)"}; commercial use: ${esc(lic.commercial_use)}</dd>
            <dt>Cite as</dt><dd>${esc(lic.attribution)}</dd>
          </dl>
          ${fp ? `<h3>Mirror</h3><dl class="kv"><dt>Release</dt><dd class="mono">${esc(fp.release)}</dd><dt>Rows</dt><dd>${Number(fp.row_count).toLocaleString()}</dd><dt>Mirrored</dt><dd>${esc(fp.ingested_at.slice(0, 10))}</dd></dl>` : ""}
          ${how ? `<div class="notice"><strong>Not served here.</strong> ${esc(how.reason)}${how.homepage ? ` Get it from <a href="${esc(safeUrl(how.homepage))}" rel="noopener">the publisher</a>.` : ""}${how.mcp_server ? ` MCP server: <code>${esc(how.mcp_server.url)}</code>` : ""}</div>` : ""}
        </section>
      </div>
      ${fp ? previewForm(d, fp) : ""}`;
    if (fp) wirePreview(d, fp);
  }

  function previewForm(d, fp) {
    const selects = fp.partition_keys.map((k) => {
      const vals = k.values.filter((v) => !String(v).startsWith("... "));
      // Default to a light slice: state- or county-level rows when that value exists, else the first value.
      const pref = ["state", "county", "us", "nation"].find((v) => vals.includes(v));
      const def = k.required ? (pref ?? vals[0]) : (pref && /geo|level|type/i.test(k.name) ? pref : "");
      return `<label for="pk-${esc(k.name)}">${esc(k.name)}${k.required ? " (required)" : ""}
        <select id="pk-${esc(k.name)}" data-key="${esc(k.name)}">
          ${k.required ? "" : '<option value="">any</option>'}${vals.map((v) => `<option value="${esc(v)}"${v === def ? " selected" : ""}>${esc(v || "(blank)")}</option>`).join("")}
        </select></label>`;
    }).join("");
    return `<div class="preview">
      <h3>Preview the data</h3>
      <p class="lede-small">Pick values for the partition keys (they choose which slice is read), then preview up to 25 rows or download up to 1,000 as CSV. Agents get the same rows through <span class="mono">fetch</span>.</p>
      <div class="filters">${selects}
        <button type="button" class="btn btn-primary" id="pv-go">Preview</button>
        <button type="button" class="btn" id="pv-csv">Download CSV</button>
      </div>
      <div id="pv-out"></div>
    </div>`;
  }

  function wirePreview(d, fp) {
    const filters = () => {
      const f = {};
      for (const s of document.querySelectorAll(".filters select")) if (s.value !== "") f[s.dataset.key] = s.value;
      return f;
    };
    const get = (limit) => api("/api/fetch", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ source_id: d.id, filters: filters(), limit }) });
    $("#pv-go").addEventListener("click", async () => {
      const out = $("#pv-out");
      out.innerHTML = '<p class="empty">Reading…</p>';
      const r = await get(25);
      if (r.error) { out.innerHTML = `<p class="notice">${esc(r.error)}</p>`; return; }
      const cols = r.columns;
      out.innerHTML = `<div class="tablewrap"><table><thead><tr>${cols.map((c) => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${r.rows.map((row) => `<tr>${cols.map((c) => `<td>${esc(row[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        <p class="citation">${r.row_count} rows shown${r.truncated ? " (more available)" : ""}. ${esc(r.provenance.citation)}</p>`;
    });
    $("#pv-csv").addEventListener("click", async () => {
      const r = await get(1000);
      if (r.error) { $("#pv-out").innerHTML = `<p class="notice">${esc(r.error)}</p>`; return; }
      // Neutralise spreadsheet formulas in filer-supplied text (CSV injection); numbers are left alone.
      const q = (v) => { let s = String(v ?? ""); if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = "'" + s; return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
      const csv = [r.columns.map(q).join(","), ...r.rows.map((row) => r.columns.map((c) => q(row[c])).join(","))].join("\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      a.download = `${d.id}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    });
  }

  function route() {
    const m = location.hash.match(/^#source-([a-z0-9-]+)$/);
    if (m) showDetail(m[1]);
    else $("#detail").hidden = true;
  }
  window.addEventListener("hashchange", route);

  // ------------------------------------------------------------ boot
  const q0 = new URLSearchParams(location.search).get("q");
  if (q0) $("#q").value = q0;
  runSearch();
  route();
  api("/api/status").then((s) => {
    $("#stats").textContent = `${s.total_sources} sources · ${s.fetchable} fetchable · updated ${s.as_of}`;
  }).catch(() => ($("#stats").textContent = ""));
})();
