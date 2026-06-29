/* ═══════════════════════════════════════════════════════════════════════
   VERSION WATCHER
   Polls /version.json every 60 seconds. When the file's "version" string
   changes from what was loaded at page open, surfaces a small banner in
   the bottom-right with a "Refresh now" button and a 10-second auto-
   reload countdown.

   How to ship a new client version (any of these works):
     - Bump version.json manually before deploy:
         echo '{"version": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}' > version.json
     - Hook into a deploy script.
     - Add a git pre-commit hook that auto-bumps version.json.

   Why this exists: page navigation already uses cache: 'no-cache' so
   moving between pages picks up fresh HTML/JS. But admins keep the same
   page open all day — they never re-navigate. Without this watcher
   they'd run yesterday's UI until they happened to hard-refresh. With
   this watcher they get a banner within ~60 seconds of any deploy and
   the browser is fully refreshed (index.html, shared/*, page bundles)
   on the auto-reload.

   No dependencies. Loaded by index.html after shared/api.js.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const VERSION_URL = 'version.json';
    const POLL_INTERVAL_MS = 60 * 1000;   // 60 seconds — backgrounded tabs are throttled to 1/min by the browser anyway
    const AUTO_RELOAD_COUNTDOWN_S = 10;   // grace window after the banner appears before forced reload

    let initialVersion = null;            // captured at page load
    let pollTimer = null;
    let bannerShown = false;
    let countdownTimer = null;

    /**
     * Fetch /version.json bypassing the browser cache. Returns the
     * "version" string, or null on any failure (network, JSON parse,
     * missing field). Failures are logged but never surfaced to the
     * user — a transient blip shouldn't prompt anything.
     */
    async function fetchVersion() {
        try {
            const resp = await fetch(VERSION_URL, { cache: 'no-cache' });
            if (!resp.ok) {
                console.warn('[VersionWatcher] fetch failed:', resp.status, resp.statusText);
                return null;
            }
            const data = await resp.json();
            const v = data && data.version ? String(data.version) : null;
            if (!v) {
                console.warn('[VersionWatcher] version.json missing "version" field:', data);
                return null;
            }
            return v;
        } catch (err) {
            console.warn('[VersionWatcher] fetch error:', err.message);
            return null;
        }
    }

    /**
     * Inject the banner styles once. Self-contained so this whole module
     * is one drop-in file; no CSS edits needed elsewhere.
     */
    function injectStyles() {
        if (document.getElementById('version-watcher-styles')) return;
        const style = document.createElement('style');
        style.id = 'version-watcher-styles';
        style.textContent = `
            #version-watcher-banner {
                position: fixed;
                bottom: 16px;
                right: 16px;
                z-index: 99999;
                background: #1e293b;
                color: #f1f5f9;
                border: 1px solid #f59e0b;
                border-left: 4px solid #f59e0b;
                border-radius: 6px;
                padding: 12px 16px;
                font-size: 13px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.35);
                display: flex;
                align-items: center;
                gap: 12px;
                max-width: 380px;
                animation: vwSlideIn 0.25s ease-out;
            }
            @keyframes vwSlideIn {
                from { transform: translateY(20px); opacity: 0; }
                to   { transform: translateY(0); opacity: 1; }
            }
            #version-watcher-banner .vw-text { line-height: 1.4; }
            #version-watcher-banner .vw-text strong { color: #f59e0b; }
            #version-watcher-banner button {
                background: #f59e0b;
                color: #1e293b;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 12px;
                cursor: pointer;
            }
            #version-watcher-banner button:hover { background: #fbbf24; }
            #version-watcher-banner .vw-secondary {
                background: transparent;
                color: #94a3b8;
                font-weight: 400;
                font-size: 11px;
                padding: 4px 8px;
            }
            #version-watcher-banner .vw-secondary:hover {
                color: #f1f5f9; background: rgba(255, 255, 255, 0.05);
            }
        `;
        document.head.appendChild(style);
    }

    /**
     * Show the new-version banner with a countdown that ends in a
     * forced reload. The user can hit "Refresh now" to skip the
     * countdown or "Later" to dismiss for this session (we won't show
     * the banner again until they actually navigate or refresh — but
     * we keep polling so we'd catch a SECOND deploy after the first
     * was dismissed).
     */
    function showBanner(newVersion) {
        if (bannerShown) return;
        bannerShown = true;
        console.log('[VersionWatcher] new version detected — showing banner. initial=', initialVersion, 'new=', newVersion);

        injectStyles();

        const banner = document.createElement('div');
        banner.id = 'version-watcher-banner';
        banner.innerHTML = `
            <div class="vw-text">
                <strong>New version available.</strong><br>
                Auto-refreshing in <span id="vw-countdown">${AUTO_RELOAD_COUNTDOWN_S}</span>s…
            </div>
            <button id="vw-refresh">Refresh now</button>
            <button class="vw-secondary" id="vw-later">Later</button>
        `;
        document.body.appendChild(banner);

        document.getElementById('vw-refresh').addEventListener('click', () => {
            console.log('[VersionWatcher] user clicked Refresh now');
            forceReload();
        });
        document.getElementById('vw-later').addEventListener('click', () => {
            console.log('[VersionWatcher] user clicked Later — dismissing banner; will not re-show until next version change');
            clearInterval(countdownTimer);
            banner.remove();
            // Note: bannerShown stays true so we don't re-pop the banner on
            // the same deploy. A later deploy will trip a fresh comparison
            // because initialVersion is still the original (we never update
            // it). The user would then get banner #2.
            // Reset bannerShown so the NEXT deploy's banner actually appears:
            bannerShown = false;
            // And advance initialVersion to the now-known version so we
            // don't immediately re-pop for the same one.
            initialVersion = newVersion;
        });

        // Countdown
        let remaining = AUTO_RELOAD_COUNTDOWN_S;
        countdownTimer = setInterval(() => {
            remaining -= 1;
            const el = document.getElementById('vw-countdown');
            if (el) el.textContent = String(remaining);
            if (remaining <= 0) {
                clearInterval(countdownTimer);
                console.log('[VersionWatcher] countdown expired — auto-reloading');
                forceReload();
            }
        }, 1000);
    }

    /**
     * Force a fresh fetch of the document AND every sub-resource by
     * navigating to the same URL with a one-shot cache-busting query
     * parameter (_v=<timestamp>) replacing any previous one. The
     * browser treats the new URL as never-seen, refuses to satisfy it
     * from cache, and the fresh HTML it pulls in contains the new
     * ?v=<APP_VERSION> query strings on theme/script tags — so those
     * sub-resources also pull fresh.
     *
     * Why not window.location.reload(true)? The `true`/`forceGet`
     * parameter was removed from the spec years ago. Chrome quietly
     * dropped support; some intermediate proxy/SW combinations
     * silently serve the old document anyway. We saw the symptom in
     * the wild: a deploy added new <img src="assets/logo.png"> tags,
     * the watcher tripped, reload(true) ran, and the operator still
     * saw the old HTML (without the img tags) until they
     * Ctrl+F5'd by hand. The _v query swap is the only reliable
     * cross-browser way to force a true cold reload from JS.
     */
    function forceReload() {
        var url = new URL(window.location.href);
        // Remove any prior _v we appended so the query string doesn't
        // accumulate parameters across consecutive reloads.
        url.searchParams.delete('_v');
        url.searchParams.set('_v', Date.now().toString());
        var target = url.toString();
        console.log('[VersionWatcher] forceReload via cache-bust query →', target);
        // replace() instead of href = so the cache-busted URL doesn't
        // pollute the history stack — Back should still take the user
        // wherever they came from, not the bust-URL.
        window.location.replace(target);
    }

    async function poll() {
        const current = await fetchVersion();
        if (!current) return;             // transient failure — try again next interval
        if (current !== initialVersion) {
            showBanner(current);
        }
    }

    async function start() {
        initialVersion = await fetchVersion();
        if (!initialVersion) {
            console.warn('[VersionWatcher] no initial version available — watcher disabled (will retry on visibility)');
            // Retry once on tab focus in case the missing version.json is a
            // transient deployment-in-progress condition.
            document.addEventListener('visibilitychange', async function onceOnVisible() {
                if (document.visibilityState !== 'visible') return;
                document.removeEventListener('visibilitychange', onceOnVisible);
                initialVersion = await fetchVersion();
                if (initialVersion) {
                    console.log('[VersionWatcher] initial version captured on tab focus:', initialVersion);
                    schedulePolling();
                }
            });
            return;
        }
        console.log('[VersionWatcher] initial version captured:', initialVersion);
        schedulePolling();
    }

    function schedulePolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(poll, POLL_INTERVAL_MS);
        // Also poll immediately whenever the tab regains focus — the
        // browser throttles background timers, so a long-backgrounded
        // tab might be N minutes stale. A returning admin should see
        // the banner within seconds, not the next 60-second tick.
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                console.log('[VersionWatcher] tab visible — polling immediately');
                poll();
            }
        });
    }

    // Kick off as soon as the DOM is parsed; we don't need to wait for
    // page-bundle JS or anything else.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
