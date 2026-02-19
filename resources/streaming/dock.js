// Global dock component for live session monitoring
(function() {
    // Create dock element
    const dock = document.createElement('div');
    dock.id = 'global-dock';
    dock.className = 'global-dock';
    dock.innerHTML = `
        <div class="dock-content">

            <div id="dock-sessions" class="dock-sessions">
                <!-- Live sessions will be added here -->
            </div>
            <div class="dock-menu">
                <a href="/flow-builder" class="dock-menu-item" title="Flow Builder">
                    <span class="menu-icon">⚡</span>
                    <span class="menu-label">BUILD</span>
                </a>
                <a href="/streaming" class="dock-menu-item" title="All Sessions">
                    <span class="menu-icon">⊞</span>
                    <span class="menu-label">ALL</span>
                </a>
                <button class="dock-menu-item" onclick="exportTests()" title="Export all test definitions">
                    <span class="menu-icon">↓</span>
                    <span class="menu-label">EXPORT</span>
                </button>
                <button class="dock-menu-item" onclick="importTests()" title="Import test definitions">
                    <span class="menu-icon">↑</span>
                    <span class="menu-label">IMPORT</span>
                </button>
                <input type="file" id="import-file-input" accept=".json" style="display: none;" onchange="handleImportFile(event)">
            </div>
        </div>
    `;
    document.body.appendChild(dock);

    // Track active sessions
    let activeSessions = [];

    // Update dock sessions
    async function updateDockSessions() {
        try {
            const response = await fetch('/api/sessions');
            const sessions = await response.json();

            // Filter active sessions
            activeSessions = sessions.filter(s => s.status === 'active');

            const sessionsContainer = document.getElementById('dock-sessions');

            if (activeSessions.length === 0) {
                dock.classList.remove('has-sessions');
                sessionsContainer.innerHTML = '<div class="dock-empty">No active sessions</div>';
                return;
            }

            dock.classList.add('has-sessions');
            sessionsContainer.innerHTML = activeSessions.map(session => `
                <div class="dock-session"
                     data-session-key="${session.clientId}/${session.testId}/${session.sessionId}"
                     onclick="window.location.href='/single-session/${session.clientId}/${session.testId}/${session.sessionId}'">
                    <div class="dock-session-preview">
                        <img src="/rabbitize-runs/${session.clientId}/${session.testId}/${session.sessionId}/latest.jpg">
                    </div>
                    <div class="dock-session-info">
                        <div class="dock-session-client">${session.clientId}</div>
                        <div class="dock-session-test">${session.testId}</div>
                    </div>
                    <div class="dock-session-status">
                        <span class="pulse-dot"></span>
                        ${session.commandsExecuted || 0}/${session.commandCount || 0}
                    </div>
                </div>
            `).join('');

            // Add hover preview functionality
            addHoverPreviews();

        } catch (error) {
            console.error('Failed to update dock sessions:', error);
        }
    }

    // Add hover preview
    function addHoverPreviews() {
        const dockSessions = document.querySelectorAll('.dock-session');

        dockSessions.forEach(session => {
            session.addEventListener('mouseenter', function() {
                // Create preview popup
                const preview = document.createElement('div');
                preview.className = 'dock-preview-popup';
                const sessionKey = this.dataset.sessionKey;
                const [clientId, testId, sessionId] = sessionKey.split('/');
                const sessionData = activeSessions.find(s =>
                    `${s.clientId}/${s.testId}/${s.sessionId}` === sessionKey
                );

                preview.innerHTML = `
                    <div class="dock-preview-header">
                        ${clientId} / ${testId}
                    </div>
                    <div class="dock-preview-image">
                        <img src="${sessionData?.isExternal && sessionData?.port ? `http://${window.location.hostname}:${sessionData.port}` : ''}/stream/${clientId}/${testId}/${sessionId}?cid=hover-${Date.now()}-${Math.random().toString(36).substr(2, 5)}"
                             alt="Live preview"
                             onerror="this.src='/rabbitize-runs/${clientId}/${testId}/${sessionId}/latest.jpg'; this.onerror=null;">
                    </div>
                    <div class="dock-preview-info">
                        <div>Session: ${sessionId}</div>
                        <div>URL: ${sessionData?.initialUrl || 'Unknown'}</div>
                        <div>Phase: ${sessionData?.phase || 'Unknown'}</div>
                    </div>
                `;

                this.appendChild(preview);

                // Position above the dock item
                const rect = this.getBoundingClientRect();
                preview.style.left = '50%';
                preview.style.transform = 'translateX(-50%)';
                preview.style.bottom = '100%';
            });

            session.addEventListener('mouseleave', function() {
                const preview = this.querySelector('.dock-preview-popup');
                if (preview) {
                    preview.remove();
                }
            });
        });
    }

    // Initial update
    updateDockSessions();

    // Update every second
    setInterval(updateDockSessions, 1000);

    // Make dock draggable between bottom and top
    let dockPosition = localStorage.getItem('dockPosition') || 'bottom';
    if (dockPosition === 'top') {
        dock.classList.add('dock-top');
    }

    // Add dock controls (currently hidden)
    const dockControls = document.createElement('div');
    dockControls.className = 'dock-controls';
    dockControls.innerHTML = `
        <!-- Hidden for now but functions still available
        <button class="dock-control" onclick="toggleDockPosition()" title="Move dock">⇅</button>
        <button class="dock-control" onclick="minimizeDock()" title="Minimize">_</button>
        -->
    `;
    dock.querySelector('.dock-content').appendChild(dockControls);

    // Toggle dock position
    window.toggleDockPosition = function() {
        dock.classList.toggle('dock-top');
        dockPosition = dock.classList.contains('dock-top') ? 'top' : 'bottom';
        localStorage.setItem('dockPosition', dockPosition);
    };

    // Minimize dock
    window.minimizeDock = function() {
        dock.classList.toggle('minimized');
    };

    // Export all test definitions
    window.exportTests = async function() {
        try {
            const response = await fetch('/api/export-tests');
            if (!response.ok) {
                throw new Error('Export failed');
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `rabbitize-tests-${new Date().toISOString().split('T')[0]}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Export failed:', error);
            alert('Failed to export tests: ' + error.message);
        }
    };

    // Import test definitions
    window.importTests = function() {
        document.getElementById('import-file-input').click();
    };

    // Handle import file selection
    window.handleImportFile = async function(event) {
        const file = event.target.files[0];
        if (!file) return;

        try {
            const text = await file.text();
            const data = JSON.parse(text);

            // Validate structure
            if (!data.tests) {
                throw new Error('Invalid file format: missing "tests" field');
            }

            // Count tests
            let testCount = 0;
            for (const client of Object.values(data.tests)) {
                testCount += Object.keys(client).length;
            }

            if (!confirm(`Import ${testCount} test definition(s) from "${file.name}"?\n\nThis will create new sessions with the imported commands.`)) {
                event.target.value = '';
                return;
            }

            const response = await fetch('/api/import-tests', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: text
            });

            const result = await response.json();

            if (result.success) {
                alert(`Import successful!\n\nImported: ${result.imported} test(s)\nSkipped: ${result.skipped}`);
                // Reload the page to show imported tests
                window.location.reload();
            } else {
                throw new Error(result.error || 'Import failed');
            }

        } catch (error) {
            console.error('Import failed:', error);
            alert('Failed to import tests: ' + error.message);
        }

        // Reset file input
        event.target.value = '';
    };
})();