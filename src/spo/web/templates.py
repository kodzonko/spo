"""Inline Jinja templates used by the bundled web UI."""

from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "base.html": """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title }} · spo</title>
    <link rel="icon" href="data:,">
    <link rel="apple-touch-icon" href="data:,">
    <link rel="apple-touch-icon-precomposed" href="data:,">
    <style>
      :root {
        color-scheme: light;
        --bg: #f4f3ef;
        --panel: #fffdf8;
        --panel-alt: #f0ede4;
        --text: #22201b;
        --muted: #675f4f;
        --border: #d7cfbc;
        --accent: #0f766e;
        --accent-2: #b45309;
        --danger: #b91c1c;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
        background: radial-gradient(circle at top left, #fff8ea, var(--bg) 45%);
        color: var(--text);
      }
      a { color: var(--accent); text-decoration: none; }
      a:hover { text-decoration: underline; }
      .shell {
        width: min(1100px, calc(100vw - 2rem));
        margin: 0 auto;
        padding: 1rem 0 3rem;
      }
      nav {
        display: flex;
        align-items: center;
        gap: 1rem;
        justify-content: space-between;
        padding: 1rem 0 1.5rem;
      }
      .nav-links {
        display: flex;
        gap: 1rem;
        align-items: center;
        font-size: 0.95rem;
      }
      .brand {
        font-size: 1.6rem;
        font-weight: 700;
        letter-spacing: 0.02em;
      }
      .hero, .panel {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 18px;
        padding: 1rem 1.2rem;
        box-shadow: 0 10px 35px rgba(50, 41, 23, 0.05);
      }
      .hero {
        display: grid;
        gap: 1rem;
        margin-bottom: 1.5rem;
      }
      .grid {
        display: grid;
        gap: 1rem;
      }
      .grid.cols-2 {
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      }
      .panel h2, .hero h1, .hero h2 {
        margin-top: 0;
      }
      .muted { color: var(--muted); }
      .flash {
        margin-bottom: 1rem;
        padding: 0.85rem 1rem;
        border-radius: 14px;
        border: 1px solid var(--border);
        background: #fff7e8;
      }
      .flash.error {
        background: #fef2f2;
        border-color: #fecaca;
        color: #7f1d1d;
      }
      form {
        display: grid;
        gap: 0.8rem;
      }
      label {
        display: grid;
        gap: 0.25rem;
        font-size: 0.94rem;
      }
      input, textarea, select, button {
        font: inherit;
      }
      input, textarea, select {
        width: 100%;
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0.7rem 0.8rem;
        background: white;
      }
      textarea { min-height: 9rem; resize: vertical; }
      button, .button-link {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.4rem;
        border-radius: 999px;
        border: none;
        background: var(--accent);
        color: white;
        padding: 0.72rem 1rem;
        cursor: pointer;
      }
      button.secondary, .button-link.secondary {
        background: var(--panel-alt);
        color: var(--text);
        border: 1px solid var(--border);
      }
      button.danger {
        background: var(--danger);
      }
      .button-row {
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
      }
      .pill {
        display: inline-flex;
        padding: 0.25rem 0.65rem;
        border-radius: 999px;
        background: var(--panel-alt);
        border: 1px solid var(--border);
        font-size: 0.84rem;
      }
      .stat-grid {
        display: grid;
        gap: 0.85rem;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      }
      .stat {
        border-radius: 16px;
        border: 1px solid var(--border);
        background: var(--panel-alt);
        padding: 0.9rem;
      }
      .stat .value {
        font-size: 1.5rem;
        font-weight: 700;
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th, td {
        text-align: left;
        padding: 0.75rem 0.6rem;
        border-bottom: 1px solid var(--border);
        vertical-align: top;
      }
      code {
        background: var(--panel-alt);
        padding: 0.08rem 0.3rem;
        border-radius: 6px;
      }
      ul.events {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 0.6rem;
      }
      ul.events li {
        padding: 0.75rem 0.9rem;
        border: 1px solid var(--border);
        border-radius: 14px;
        background: var(--panel-alt);
      }
      .small { font-size: 0.9rem; }
      .collection-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 0.6rem;
      }
      .checkbox {
        display: flex;
        gap: 0.55rem;
        align-items: flex-start;
        padding: 0.65rem 0.7rem;
        border-radius: 12px;
        border: 1px solid var(--border);
        background: #fff;
      }
      .checkbox input {
        width: auto;
        margin-top: 0.1rem;
      }
      .status-completed, .status-completed_with_warnings { color: var(--accent); }
      .status-failed, .status-canceled, .status-paused_auth, .status-paused_rate_limit { color: var(--accent-2); }
      @media (max-width: 640px) {
        nav { flex-direction: column; align-items: flex-start; }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <nav>
        <div class="brand"><a href="/">spo</a></div>
        <div class="nav-links">
          <a href="/">Dashboard</a>
          <a href="/connections">Connections</a>
          <a href="/sync/new">New Sync</a>
          <a href="/history">History</a>
        </div>
      </nav>
      {% if message %}
        <div class="flash">{{ message }}</div>
      {% endif %}
      {% if error %}
        <div class="flash error">{{ error }}</div>
      {% endif %}
      {{ body | safe }}
    </div>
    <script>
      document.body.addEventListener("htmx:responseError", function (event) {
        console.error(event.detail.xhr.responseText);
      });
    </script>
  </body>
</html>
""",
    "dashboard.html": """
<section class="hero">
  <div>
    <h1>Local migration console</h1>
    <p class="muted">Configure streaming accounts, start a one-off migration, and resume interrupted jobs without losing progress.</p>
  </div>
  <div class="button-row">
    <a class="button-link" href="/sync/new">Start a sync</a>
    <a class="button-link secondary" href="/connections">Manage connections</a>
  </div>
</section>
<section class="grid cols-2">
  <article class="panel">
    <h2>Connected Accounts</h2>
    {% if accounts %}
      <ul class="events">
        {% for account in accounts %}
          <li>
            <strong>{{ account.display_name or account.service }}</strong>
            <div class="small muted">{{ account.service }} · {{ account.auth_status }}</div>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="muted">No streaming accounts connected yet.</p>
    {% endif %}
  </article>
  <article class="panel">
    <h2>Recent Jobs</h2>
    {% if jobs %}
      <ul class="events">
        {% for job in jobs[:5] %}
          <li>
            <a href="/jobs/{{ job.id }}"><strong>Job #{{ job.id }}</strong></a>
            <div class="small muted">{{ job.source_service }} → {{ job.target_service }} · {{ job.status }}</div>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="muted">No sync jobs created yet.</p>
    {% endif %}
  </article>
</section>
""",
    "connections.html": """
<section class="hero">
  <div>
    <h1>Connections</h1>
    <p class="muted">Store local credentials for each streaming service on this machine. Spotify uses an OAuth redirect, and YouTube Music uses a guided Google device flow.</p>
  </div>
</section>
<section class="grid cols-2">
  <article class="panel">
    <h2>Spotify</h2>
    <form method="post" action="/api/connections/spotify">
      <label>Client ID
        <input name="client_id" placeholder="Spotify app client ID" required>
      </label>
      <label>Redirect URI
        <input name="redirect_uri" placeholder="Optional. Defaults to local callback URI.">
      </label>
      <div class="button-row">
        <button type="submit">Connect Spotify</button>
      </div>
    </form>
    <p class="small muted">Uses Spotify Authorization Code with PKCE. Provide your own Spotify developer app client ID and allow the local redirect URI in the dashboard.</p>
  </article>
  <article class="panel">
    <h2>YouTube Music</h2>
    <form method="post" action="/api/connections/ytmusic/oauth/start">
      <label>Google Client ID
        <input name="client_id" placeholder="Google OAuth client ID" required>
      </label>
      <label>Google Client Secret
        <input name="client_secret" type="password" placeholder="Google OAuth client secret" required>
      </label>
      <div class="button-row">
        <button type="submit">Connect YouTube Music</button>
      </div>
    </form>
    <p class="small muted">spo starts the Google device flow, opens the sign-in page, and saves the resulting token locally. You still need your own YouTube Data API OAuth client.</p>
    <p class="small muted">If the default YouTube Music OAuth client behavior is rejected, spo will now try a couple of experimental YouTube client profiles automatically before giving up.</p>
  </article>
</section>
<section class="panel" style="margin-top: 1rem;">
  <h2>Saved Accounts</h2>
  {% if accounts %}
    <table>
      <thead>
        <tr>
          <th>Service</th>
          <th>Display Name</th>
          <th>Status</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {% for account in accounts %}
          <tr>
            <td>{{ account.service }}</td>
            <td>{{ account.display_name or "Pending authorization" }}</td>
            <td>{{ account.auth_status }}</td>
            <td>{{ account.updated_at }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="muted">No accounts stored yet.</p>
  {% endif %}
</section>
""",
    "ytmusic_oauth.html": """
<section class="hero">
  <div>
    <h1>Connect YouTube Music</h1>
    <p class="muted">Keep this page open while you finish Google sign-in. `spo` will poll for completion and save the token locally without requiring you to paste JSON back into the app.</p>
  </div>
  <div class="button-row">
    <a id="ytmusic-open-auth" class="button-link" href="{{ verification_url }}" target="_blank" rel="noopener">Continue with Google</a>
    <a class="button-link secondary" href="/connections">Back to connections</a>
  </div>
</section>
<section class="grid cols-2">
  <article class="panel">
    <h2>Verification Code</h2>
    <p>Enter this code if Google asks for it:</p>
    <p><code id="ytmusic-user-code">{{ user_code }}</code></p>
    <p class="small muted">If a pop-up was blocked, use the button above to open the Google verification page manually.</p>
  </article>
  <article class="panel">
    <h2>Status</h2>
    <p id="ytmusic-oauth-status">Waiting for Google approval.</p>
    <p class="small muted">The page checks every {{ interval_seconds }} seconds and redirects back to Connections when the account is ready.</p>
  </article>
</section>
<script>
  (function () {
    const statusEl = document.getElementById("ytmusic-oauth-status");
    const openAuthLink = document.getElementById("ytmusic-open-auth");
    const statusUrl = "/api/connections/ytmusic/oauth/{{ flow_id }}/status";
    let intervalSeconds = {{ interval_seconds }};

    function setStatus(message) {
      statusEl.textContent = message;
    }

    async function poll() {
      try {
        const response = await fetch(statusUrl, { cache: "no-store" });
        const payload = await response.json();
        if (payload.status === "pending") {
          intervalSeconds = payload.interval_seconds || intervalSeconds;
          window.setTimeout(poll, intervalSeconds * 1000);
          return;
        }
        if (payload.redirect_url) {
          window.location.href = payload.redirect_url;
          return;
        }
        if (payload.message) {
          setStatus(payload.message);
          return;
        }
        setStatus("YouTube Music authorization stopped unexpectedly.");
      } catch (_error) {
        setStatus("Could not reach the local authorization status endpoint. Retrying shortly.");
        window.setTimeout(poll, intervalSeconds * 1000);
      }
    }

    try {
      const popup = window.open(openAuthLink.href, "_blank", "noopener");
      if (!popup) {
        setStatus("Pop-up blocked. Use Continue with Google to open the verification page.");
      }
    } catch (_error) {
      setStatus("Use Continue with Google to open the verification page.");
    }

    window.setTimeout(poll, intervalSeconds * 1000);
  })();
</script>
""",
    "sync_new.html": """
<section class="hero">
  <div>
    <h1>New Sync</h1>
    <p class="muted">Pick a source account, a target account, and the collections you want to migrate. The engine snapshots the source first, then resumes safely if a run is interrupted or rate-limited.</p>
  </div>
</section>
<section class="panel">
  <form method="post" action="/api/jobs">
    <label>Source account
      <select name="source_account_id" required>
        <option value="">Select source</option>
        {% for account in accounts %}
          <option value="{{ account.id }}">{{ account.display_name or account.service }} · {{ account.service }}</option>
        {% endfor %}
      </select>
    </label>
    <label>Target account
      <select name="target_account_id" required>
        <option value="">Select target</option>
        {% for account in accounts %}
          <option value="{{ account.id }}">{{ account.display_name or account.service }} · {{ account.service }}</option>
        {% endfor %}
      </select>
    </label>
    <div>
      <strong>Collections</strong>
      <div class="collection-grid" style="margin-top: 0.7rem;">
        {% for collection in collections %}
          <label class="checkbox">
            <input type="checkbox" name="collection_kinds" value="{{ collection.value }}" checked>
            <span>
              <strong>{{ collection.label }}</strong><br>
              <span class="small muted">{{ collection.description }}</span>
            </span>
          </label>
        {% endfor %}
      </div>
    </div>
    <div class="button-row">
      <button type="submit">Create sync job</button>
    </div>
  </form>
</section>
""",
    "history.html": """
<section class="hero">
  <div>
    <h1>Sync History</h1>
    <p class="muted">Every run is resumable and stored locally. Open any job to inspect its counters, warnings, and event log.</p>
  </div>
</section>
<section class="panel">
  {% if jobs %}
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Direction</th>
          <th>Status</th>
          <th>Scope</th>
          <th>Progress</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {% for job in jobs %}
          <tr>
            <td><a href="/jobs/{{ job.id }}">#{{ job.id }}</a></td>
            <td>{{ job.source_service }} → {{ job.target_service }}</td>
            <td class="status-{{ job.status }}">{{ job.status }}</td>
            <td>{{ ", ".join(job.scope) }}</td>
            <td>{{ job.progress_applied_count }} applied · {{ job.progress_skipped_count }} skipped · {{ job.progress_failed_count }} failed</td>
            <td>{{ job.updated_at }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p class="muted">No jobs yet.</p>
  {% endif %}
</section>
""",
    "job_detail.html": """
<section class="hero">
  <div>
    <h1>Job #{{ job.id }}</h1>
    <p class="muted">{{ source.display_name or source.service }} → {{ target.display_name or target.service }}</p>
  </div>
  <div class="button-row">
    <form method="post" action="/api/jobs/{{ job.id }}/resume">
      <button type="submit" class="secondary">Resume</button>
    </form>
    <form method="post" action="/api/jobs/{{ job.id }}/cancel">
      <button type="submit" class="danger">Cancel</button>
    </form>
  </div>
</section>
<section class="grid cols-2">
  <article class="panel">
    <h2>Status</h2>
    <div class="stat-grid">
      <div class="stat"><div class="small muted">Status</div><div class="value" id="job-status">{{ job.status }}</div></div>
      <div class="stat"><div class="small muted">Phase</div><div class="value" id="job-phase">{{ job.phase }}</div></div>
      <div class="stat"><div class="small muted">Collection</div><div class="value" id="job-collection">{{ job.current_collection_kind or "—" }}</div></div>
      <div class="stat"><div class="small muted">Snapshot</div><div class="value" id="job-snapshot">{{ job.progress_snapshot_count }}</div></div>
      <div class="stat"><div class="small muted">Applied</div><div class="value" id="job-applied">{{ job.progress_applied_count }}</div></div>
      <div class="stat"><div class="small muted">Skipped</div><div class="value" id="job-skipped">{{ job.progress_skipped_count }}</div></div>
      <div class="stat"><div class="small muted">Failed</div><div class="value" id="job-failed">{{ job.progress_failed_count }}</div></div>
    </div>
    <p class="small muted" id="job-error">{{ job.last_error or "" }}</p>
  </article>
  <article class="panel">
    <h2>Scope</h2>
    <p>{{ ", ".join(job.scope) }}</p>
    <p class="small muted">Started: {{ job.started_at or "not started" }}<br>Finished: {{ job.finished_at or "not finished" }}</p>
  </article>
</section>
<section class="panel" style="margin-top: 1rem;">
  <h2>Events</h2>
  <ul class="events" id="event-list">
    {% for event in events %}
      <li data-event-id="{{ event.id }}">
        <strong>[{{ event.level }}]</strong> {{ event.message }}
        <div class="small muted">{{ event.created_at }}</div>
      </li>
    {% endfor %}
  </ul>
</section>
<script>
  (function () {
    const jobId = {{ job.id }};
    const list = document.getElementById("event-list");
    const statusIds = ["status", "phase", "collection", "snapshot", "applied", "skipped", "failed", "error"];
    async function refreshJob() {
      const response = await fetch(`/api/jobs/${jobId}`);
      if (!response.ok) {
        return;
      }
      const job = await response.json();
      document.getElementById("job-status").textContent = job.status;
      document.getElementById("job-phase").textContent = job.phase;
      document.getElementById("job-collection").textContent = job.current_collection_kind || "—";
      document.getElementById("job-snapshot").textContent = job.progress_snapshot_count;
      document.getElementById("job-applied").textContent = job.progress_applied_count;
      document.getElementById("job-skipped").textContent = job.progress_skipped_count;
      document.getElementById("job-failed").textContent = job.progress_failed_count;
      document.getElementById("job-error").textContent = job.last_error || "";
    }
    const eventSource = new EventSource(`/api/jobs/${jobId}/events`);
    eventSource.onmessage = function (event) {
      const payload = JSON.parse(event.data);
      const item = document.createElement("li");
      item.dataset.eventId = payload.id;
      item.innerHTML = `<strong>[${payload.level}]</strong> ${payload.message}<div class="small muted">${payload.created_at}</div>`;
      list.appendChild(item);
      refreshJob();
    };
    eventSource.onerror = function () {
      console.warn("event stream disconnected");
    };
  })();
</script>
""",
}
