/**
 * Reverse Face Search Dashboard — Client-side logic.
 * Handles upload, WebSocket progress, and result rendering.
 */

(function () {
    'use strict';

    // ── State ──
    let searchId = null;
    let ws = null;
    let dossier = null;

    // ── DOM refs ──
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const uploadPreview = document.getElementById('upload-preview');
    const previewImg = document.getElementById('preview-img');
    const uploadInfo = document.getElementById('upload-info');
    const searchBtn = document.getElementById('search-btn');
    const uploadStatus = document.getElementById('upload-status');
    const progressPanel = document.getElementById('progress-panel');
    const resultsPanel = document.getElementById('results-panel');
    const exportPanel = document.getElementById('export-panel');

    // ── Upload: Drag & Drop ──
    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-active');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-active');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-active');
        const files = e.dataTransfer.files;
        if (files.length > 0) handleFile(files[0]);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) handleFile(fileInput.files[0]);
    });

    async function handleFile(file) {
        const validTypes = ['image/jpeg', 'image/png', 'image/webp'];
        if (!validTypes.includes(file.type)) {
            showStatus('Invalid file type. Use JPEG, PNG, or WebP.', 'error');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        showStatus('Uploading...', '');
        dropZone.classList.add('hidden');
        uploadPreview.classList.remove('hidden');
        previewImg.src = URL.createObjectURL(file);
        uploadInfo.textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`;

        try {
            const resp = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || 'Upload failed');

            searchId = data.search_id;
            showStatus(`Uploaded — ID: ${searchId}`, 'success');
            searchBtn.classList.remove('hidden');
            searchBtn.onclick = startSearch;
        } catch (err) {
            showStatus(`Upload failed: ${err.message}`, 'error');
            resetUpload();
        }
    }

    function resetUpload() {
        dropZone.classList.remove('hidden');
        uploadPreview.classList.add('hidden');
        searchBtn.classList.add('hidden');
        previewImg.src = '';
        uploadInfo.textContent = '';
        searchId = null;
    }

    function showStatus(msg, cls) {
        uploadStatus.textContent = msg;
        uploadStatus.className = 'status ' + cls;
    }

    // ── Search ──
    async function startSearch() {
        searchBtn.disabled = true;
        searchBtn.textContent = 'Searching...';
        progressPanel.classList.remove('hidden');
        resetStages();
        setStageActive('upload', 'done');

        // Connect WebSocket
        connectWebSocket();

        // Trigger search
        try {
            const resp = await fetch(`/api/search/${searchId}`, { method: 'POST' });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || 'Search start failed');
            showStatus('Search running...', 'success');
        } catch (err) {
            showStatus(`Search error: ${err.message}`, 'error');
            searchBtn.disabled = false;
            searchBtn.textContent = 'Start Search';
        }
    }

    // ── WebSocket ──
    function connectWebSocket() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${protocol}//${location.host}/ws/${searchId}`);

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                updateProgress(data);
            } catch (e) { /* ignore malformed */ }
        };

        ws.onclose = () => {
            // Poll for completion if WS closes
            if (searchId) pollForCompletion();
        };

        ws.onerror = () => {
            // Fall back to polling
            if (searchId) pollForCompletion();
        };
    }

    function updateProgress(data) {
        const stage = data.stage;
        const progress = data.progress || {};

        if (stage === 'uploading_to_host') {
            setStageActive('upload', 'done');
            setStageActive('uploading_to_host', 'active');
        } else if (stage === 'reverse_search') {
            setStageActive('uploading_to_host', 'done');
            setStageActive('reverse_search', 'active');
            if (progress.current_engine) {
                document.getElementById('engine-details').textContent = `Scanning: ${progress.current_engine}`;
            }
        } else if (stage === 'clustering') {
            setStageActive('reverse_search', 'done');
            setStageActive('clustering', 'active');
        } else if (stage === 'username_extraction') {
            setStageActive('clustering', 'done');
            setStageActive('username_extraction', 'active');
        } else if (stage === 'maigret') {
            setStageActive('username_extraction', 'done');
            setStageActive('maigret', 'active');
            if (progress.usernames) {
                document.getElementById('engine-details').textContent = `Usernames: ${progress.usernames.join(', ')}`;
            }
        } else if (stage === 'intel_report') {
            setStageActive('maigret', 'done');
            setStageActive('intel_report', 'active');
        } else if (stage === 'dossier') {
            setStageActive('intel_report', 'done');
            setStageActive('dossier', 'active');
        } else if (stage === 'completed') {
            setStageActive('dossier', 'done');
            setStageActive('completed', 'done');
            fetchDossier();
        } else if (stage === 'failed') {
            setStageActive(stage, 'failed');
        }
    }

    function setStageActive(stageName, state) {
        const el = document.querySelector(`.stage[data-stage="${stageName}"]`);
        if (!el) return;
        el.classList.remove('active', 'done', 'failed');
        if (state) el.classList.add(state);
        const statusEl = el.querySelector('.stage-status');
        if (statusEl) {
            if (state === 'active') statusEl.textContent = 'Running...';
            else if (state === 'done') statusEl.textContent = '✓';
            else if (state === 'failed') statusEl.textContent = '✗';
        }
    }

    function resetStages() {
        document.querySelectorAll('.stage').forEach(el => {
            el.classList.remove('active', 'done', 'failed');
            const s = el.querySelector('.stage-status');
            if (s) s.textContent = '';
        });
    }

    // ── Poll for completion ──
    async function pollForCompletion() {
        for (let i = 0; i < 30; i++) {
            await sleep(2000);
            try {
                const resp = await fetch(`/api/status/${searchId}`);
                const data = await resp.json();
                if (data.stage === 'completed') {
                    updateProgress({ stage: 'completed', progress: data.progress });
                    return;
                }
                if (data.stage === 'failed') {
                    updateProgress({ stage: 'failed', progress: { error: data.errors?.join(', ') } });
                    return;
                }
                updateProgress({ stage: data.stage, progress: data.progress || {} });
            } catch (e) { /* keep polling */ }
        }
    }

    // ── Fetch Dossier ──
    async function fetchDossier() {
        try {
            const resp = await fetch(`/api/dossier/${searchId}`);
            dossier = await resp.json();
            renderResults();
            exportPanel.classList.remove('hidden');
            searchBtn.textContent = 'Search Complete';
        } catch (err) {
            console.error('Dossier fetch error:', err);
        }
    }

    // ── Render Results ──
    function renderResults() {
        if (!dossier) return;
        resultsPanel.classList.remove('hidden');

        renderIntelReport();
        renderEngineResults();
        renderClusters();
        renderUsernames();
        renderMaigretGrid();
    }

    function renderIntelReport() {
        const ir = dossier.intel_report;
        if (!ir) return;
        
        document.getElementById('intel-report-section').classList.remove('hidden');
        
        // Subject + classification
        const name = ir.subject_name || dossier.summary?.subject_name || 'Unknown';
        const pf = ir.public_figure || {};
        const level = (pf.level || 'UNKNOWN').replace(/_/g, ' ');
        const badge = pf.level && pf.level.includes('PUBLIC') ? 'badge-public' : 'badge-private';
        document.getElementById('intel-subject').innerHTML = `${escapeHtml(name)} <span class="badge ${badge}">${level}</span>`;
        document.getElementById('intel-classification').innerHTML = `Confidence: ${pf.confidence || 'N/A'} | Search results: ${pf.total_search_results || 0}`;
        
        // Wikipedia
        const wiki = ir.wikipedia || {};
        if (wiki.found) {
            const facts = wiki.facts || {};
            let w = `<div class="section-box"><strong>${escapeHtml(wiki.title)}</strong> <span class="badge badge-wiki">Wikipedia</span>`;
            if (facts.profession) w += `<br>Profession: ${escapeHtml(facts.profession)}`;
            if (facts.nationality) w += `<br>Nationality: ${escapeHtml(facts.nationality)}`;
            if (facts.birth_year) w += `<br>Born: ${facts.birth_year}`;
            if (wiki.summary) w += `<br><br>${escapeHtml(wiki.summary).substring(0, 500)}...`;
            w += '</div>';
            document.getElementById('intel-wikipedia').innerHTML = w;
        } else {
            document.getElementById('intel-wikipedia').innerHTML = '<p class="text-muted">No Wikipedia entry found.</p>';
        }
        
        // Risk
        const risk = ir.risk_assessment || {};
        if (risk.found) {
            const cls = 'risk-' + (risk.risk_level || 'low').toLowerCase();
            document.getElementById('intel-risk').innerHTML = `<div class="section-box"><span class="${cls}">Risk: ${risk.risk_level}</span> — ${escapeHtml(risk.name || '')}</div>`;
        }
        
        // Affiliations
        const aff = ir.affiliations || {};
        const orgs = (aff.organizations || []).slice(0, 5).map(o => o.name).join(', ');
        const locs = (aff.locations || []).slice(0, 5).map(l => l.name).join(', ');
        if (orgs || locs) {
            let a = '';
            if (orgs) a += `<strong>Orgs:</strong> ${escapeHtml(orgs)}<br>`;
            if (locs) a += `<strong>Locations:</strong> ${escapeHtml(locs)}`;
            document.getElementById('intel-affiliations').innerHTML = `<div class="section-box">${a}</div>`;
        }
        
        // Narrative
        if (ir.narrative) {
            document.getElementById('intel-narrative').innerHTML = `<p>${escapeHtml(ir.narrative).replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>')}</p>`;
        }
    }

    function renderEngineResults() {
        const tabs = document.getElementById('engine-tabs');
        const content = document.getElementById('engine-content');
        const engines = dossier.engines || {};

        tabs.innerHTML = '';
        content.innerHTML = '';

        let first = true;
        for (const [name, data] of Object.entries(engines)) {
            // Tab
            const tab = document.createElement('button');
            tab.className = 'tab-btn' + (first ? ' active' : '');
            tab.textContent = `${name} (${data.url_count || 0})`;
            tab.onclick = () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                tab.classList.add('active');
                showEngineTab(name, data);
            };
            tabs.appendChild(tab);

            if (first) {
                showEngineTab(name, data);
                first = false;
            }
        }
    }

    function showEngineTab(name, data) {
        const content = document.getElementById('engine-content');
        content.innerHTML = '';

        if (data.error) {
            content.innerHTML = `<p class="text-error">Error: ${data.error}</p>`;
            return;
        }

        const urls = data.sample_urls || [];
        if (urls.length === 0) {
            content.innerHTML = '<p class="text-muted">No results.</p>';
            return;
        }

        urls.forEach(url => {
            const div = document.createElement('div');
            div.className = 'url-item';
            div.innerHTML = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(url)}</a>`;
            content.appendChild(div);
        });
    }

    function renderClusters() {
        const grid = document.getElementById('cluster-grid');
        const clusters = dossier.clusters || {};
        const categories = clusters.categories || {};
        const socialBreakdown = clusters.social_media_breakdown || {};

        grid.innerHTML = '';

        for (const [cat, data] of Object.entries(categories)) {
            if (data.url_count === 0) continue;
            const card = document.createElement('div');
            card.className = 'cluster-card';
            card.innerHTML = `
                <div class="cat-name">${cat.replace(/_/g, ' ')}</div>
                <div class="cat-count">${data.url_count}</div>
                <div class="cat-confidence">confidence: ${(data.confidence * 100).toFixed(0)}%</div>
            `;
            grid.appendChild(card);
        }

        // Social breakdown bars
        if (Object.keys(socialBreakdown).length > 0) {
            const breakdown = document.createElement('div');
            breakdown.className = 'social-breakdown';
            breakdown.innerHTML = '<h4>Social Media Breakdown</h4>';

            const maxCount = Math.max(...Object.values(socialBreakdown), 1);
            for (const [platform, count] of Object.entries(socialBreakdown)) {
                const pct = ((count / maxCount) * 100).toFixed(0);
                breakdown.innerHTML += `
                    <div class="social-bar">
                        <span class="platform-name">${platform}</span>
                        <div class="bar-track">
                            <div class="bar-fill" style="width:${pct}%"></div>
                        </div>
                        <span class="bar-count">${count}</span>
                    </div>
                `;
            }
            grid.parentElement.appendChild(breakdown);
        }
    }

    function renderUsernames() {
        const tbody = document.querySelector('#username-table tbody');
        const usernames = dossier.usernames || [];
        tbody.innerHTML = '';

        if (usernames.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-muted">No usernames extracted.</td></tr>';
            return;
        }

        usernames.forEach(u => {
            const row = document.createElement('tr');
            const matchPct = u.name_match_score ? (u.name_match_score * 100).toFixed(0) + '%' : '-';
            const matchIcon = u.name_match_score >= 0.5 ? '✓' : (u.name_match_score >= 0.3 ? '~' : '?');
            row.innerHTML = `
                <td><strong>${escapeHtml(u.username)}</strong></td>
                <td>${(u.platforms || []).map(escapeHtml).join(', ')}</td>
                <td>${matchIcon} ${matchPct}</td>
                <td>${(u.source_urls || []).slice(0, 2).map(url => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">link</a>`).join(' ')}</td>
            `;
            tbody.appendChild(row);
        });
    }

    function renderMaigretGrid() {
        const grid = document.getElementById('maigret-grid');
        const correlation = dossier.cross_platform_correlation || {};
        grid.innerHTML = '';

        let hasData = false;
        for (const [username, data] of Object.entries(correlation)) {
            const hits = data.hit_platforms || [];
            const sitesChecked = data.sites_checked || 0;

            if (hits.length === 0 && sitesChecked === 0) continue;
            hasData = true;

            // Show username header
            const header = document.createElement('div');
            header.style.cssText = 'grid-column: 1 / -1; font-weight: 600; margin-top: 8px; font-size: 0.85rem;';
            header.textContent = `${username} (${hits.length} hits / ${sitesChecked} checked)`;
            grid.appendChild(header);

            // Show hit platforms
            hits.forEach(site => {
                const hit = document.createElement('div');
                hit.className = 'maigret-hit found';
                hit.innerHTML = `<span class="dot"></span>${escapeHtml(site)}`;
                grid.appendChild(hit);
            });
        }

        if (!hasData) {
            grid.innerHTML = '<p class="text-muted">No cross-platform data available.</p>';
        }
    }

    // ── Export ──
    document.getElementById('export-json-btn').addEventListener('click', () => {
        if (!dossier) return;
        const blob = new Blob([JSON.stringify(dossier, null, 2)], { type: 'application/json' });
        downloadBlob(blob, `dossier-${searchId}.json`);
    });

    document.getElementById('export-pdf-btn').addEventListener('click', () => {
        if (!searchId) return;
        // Use anchor download for proper file download
        const a = document.createElement('a');
        a.href = `/api/report/${searchId}`;
        a.download = `intel-report-${searchId.slice(0,8)}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    });

    document.getElementById('new-search-btn').addEventListener('click', () => {
        if (ws) ws.close();
        searchId = null;
        dossier = null;
        resetUpload();
        progressPanel.classList.add('hidden');
        resultsPanel.classList.add('hidden');
        exportPanel.classList.add('hidden');
        searchBtn.classList.add('hidden');
        showStatus('', '');
        resetStages();
    });

    // ── Helpers ──
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
})();
