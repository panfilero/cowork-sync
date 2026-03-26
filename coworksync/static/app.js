/* CoworkSync — status polling and form handling */

(function () {
    "use strict";

    var sourceEl = document.getElementById("source_folder");
    var localEl = document.getElementById("local_folder");
    var intervalEl = document.getElementById("sync_interval");
    var startupEl = document.getElementById("start_with_windows");
    var btnSave = document.getElementById("btn-save");
    var btnStop = document.getElementById("btn-stop");
    var btnSync = document.getElementById("btn-sync");
    var msgEl = document.getElementById("message");
    var statusDot = document.getElementById("status-dot");
    var statusText = document.getElementById("status-text");
    var lastSyncEl = document.getElementById("last-sync");
    var nextPollEl = document.getElementById("next-poll");
    var filesTodayEl = document.getElementById("files-today");
    var activityLog = document.getElementById("activity-log");

    // --- Messages ---
    function showMessage(text, type) {
        msgEl.textContent = text;
        msgEl.className = "message " + type;
        setTimeout(function () {
            msgEl.className = "message hidden";
        }, 5000);
    }

    // --- Load config ---
    function loadConfig() {
        fetch("/api/config")
            .then(function (r) { return r.json(); })
            .then(function (cfg) {
                sourceEl.value = cfg.source_folder || "";
                localEl.value = cfg.local_folder || "";
                intervalEl.value = cfg.sync_interval || 5;
                startupEl.checked = cfg.start_with_windows !== false;
            })
            .catch(function () {});
    }

    // --- Save config ---
    btnSave.addEventListener("click", function () {
        var data = {
            source_folder: sourceEl.value,
            local_folder: localEl.value,
            sync_interval: parseInt(intervalEl.value, 10) || 5,
            start_with_windows: startupEl.checked
        };

        fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
        .then(function (res) {
            if (!res.ok) {
                showMessage(res.body.error || "Save failed.", "error");
                return;
            }
            if (res.body.warning) {
                showMessage("Saved. " + res.body.warning, "warning");
            } else {
                showMessage("Configuration saved.", "success");
            }
            // Start engine
            return fetch("/api/start", { method: "POST" });
        })
        .then(function () { refreshStatus(); })
        .catch(function () { showMessage("Network error.", "error"); });
    });

    // --- Stop ---
    btnStop.addEventListener("click", function () {
        fetch("/api/stop", { method: "POST" })
            .then(function () { refreshStatus(); })
            .catch(function () {});
    });

    // --- Sync Now ---
    btnSync.addEventListener("click", function () {
        fetch("/api/sync-now", { method: "POST" })
            .then(function () {
                showMessage("Sync triggered.", "success");
                setTimeout(refreshStatus, 2000);
            })
            .catch(function () {});
    });

    // --- Status polling ---
    function refreshStatus() {
        fetch("/api/status")
            .then(function (r) { return r.json(); })
            .then(function (s) {
                // Status dot
                var color = "gray";
                var label = "Stopped";
                if (s.status === "running") { color = "green"; label = "Running"; }
                else if (s.status === "syncing") { color = "yellow"; label = "Syncing..."; }
                else if (s.status === "error") { color = "red"; label = "Error"; }
                statusDot.className = "status-dot " + color;
                statusText.textContent = label;
                if (s.error) statusText.textContent = label + " — " + s.error;

                // Last sync
                if (s.last_sync) {
                    var d = new Date(s.last_sync);
                    var diff = Math.floor((Date.now() - d.getTime()) / 1000);
                    if (diff < 60) lastSyncEl.textContent = "just now";
                    else if (diff < 3600) lastSyncEl.textContent = Math.floor(diff / 60) + " minutes ago";
                    else lastSyncEl.textContent = d.toLocaleTimeString();
                } else {
                    lastSyncEl.textContent = "\u2014";
                }

                // Next poll
                if (s.next_poll !== null && s.next_poll !== undefined && s.status === "running") {
                    var mins = Math.ceil(s.next_poll / 60);
                    nextPollEl.textContent = mins + " minute" + (mins !== 1 ? "s" : "");
                } else {
                    nextPollEl.textContent = "\u2014";
                }

                // Files today
                filesTodayEl.textContent = s.files_today + " file" + (s.files_today !== 1 ? "s" : "");

                // Update stop button label
                btnStop.textContent = s.status === "stopped" ? "Resume" : "Stop";
                if (s.status === "stopped") {
                    btnStop.onclick = function () {
                        fetch("/api/start", { method: "POST" }).then(function () { refreshStatus(); });
                    };
                } else {
                    btnStop.onclick = function () {
                        fetch("/api/stop", { method: "POST" }).then(function () { refreshStatus(); });
                    };
                }
            })
            .catch(function () {});
    }

    // --- Activity log ---
    function refreshLog() {
        fetch("/api/log")
            .then(function (r) { return r.json(); })
            .then(function (entries) {
                if (!entries || entries.length === 0) {
                    activityLog.innerHTML = '<div class="log-empty">No recent activity</div>';
                    return;
                }
                var html = "";
                var shown = entries.slice(0, 10);
                for (var i = 0; i < shown.length; i++) {
                    var e = shown[i];
                    if (e.raw) {
                        // Fallback: raw log line
                        html += '<div class="log-entry"><span class="log-file">' + escapeHtml(e.raw) + '</span></div>';
                        continue;
                    }
                    var cls = "";
                    if (e.action === "Error") cls = " error";
                    else if (e.action === "Conflict") cls = " conflict";
                    html += '<div class="log-entry' + cls + '">'
                        + '<span class="log-time">' + escapeHtml(e.time || "") + '</span>'
                        + '<span class="log-action">' + escapeHtml(e.action || "") + '</span>'
                        + '<span class="log-file">' + escapeHtml(e.file || "") + '</span>'
                        + '<span class="log-dir">' + escapeHtml(e.direction || "") + '</span>'
                        + '</div>';
                }
                activityLog.innerHTML = html;
            })
            .catch(function () {});
    }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.appendChild(document.createTextNode(s));
        return d.innerHTML;
    }

    // --- Init ---
    loadConfig();
    refreshStatus();
    refreshLog();

    setInterval(refreshStatus, 15000);
    setInterval(refreshLog, 15000);
})();
