/* ===========================================================================
   CareerFlow AI — Autonomous Mission Control Dashboard Logic
   Retro-Analog Interactive Controller
   =========================================================================== */

document.addEventListener("DOMContentLoaded", () => {

    // ---- DOM References ----
    const statusOrb          = document.getElementById("status-orb");
    const daemonLabel        = document.getElementById("daemon-status-label");
    const clockEl            = document.getElementById("clock");
    const uptimeText         = document.getElementById("uptime-text");
    const greetingText       = document.getElementById("greeting-text");
    const greetingSub        = document.getElementById("greeting-sub");

    const statScanned        = document.getElementById("stat-scanned");
    const statMatched        = document.getElementById("stat-matched");
    const statApplied        = document.getElementById("stat-applied");
    const statVisibility     = document.getElementById("stat-visibility");
    const statSyncs          = document.getElementById("stat-syncs");
    const ringFill           = document.getElementById("ring-fill");


    const timelineContainer  = document.getElementById("timeline-container");
    const timelineCount      = document.getElementById("timeline-count");

    const terminalOutput     = document.getElementById("terminal-output");
    const terminalStatus     = document.getElementById("terminal-status");

    const appsContainer      = document.getElementById("apps-container");
    const appsCount          = document.getElementById("apps-count");

    // AI Tab References
    const aiBadge            = document.getElementById("ai-badge");
    const aiModel            = document.getElementById("ai-model");
    const aiApikey           = document.getElementById("ai-apikey");
    const aiSkills           = document.getElementById("ai-skills");
    const aiProjects         = document.getElementById("ai-projects");
    const aiProfile          = document.getElementById("ai-profile");
    const aiHeadline         = document.getElementById("ai-headline");
    const aiNextCycle        = document.getElementById("ai-next-cycle");

    // Retro Control References
    const crtEffectSwitch    = document.getElementById("crt-effect-switch");
    const crtDisplayScreen   = document.getElementById("crt-display-screen");
    const masterPowerLed     = document.getElementById("master-power-led");

    // VHS Reels & Tapes
    const vhsTapeBody        = document.getElementById("vhs-tape-body");
    const leftTapePack       = document.getElementById("left-tape-pack");
    const rightTapePack      = document.getElementById("right-tape-pack");

    // Physical Buttons & Chunky Lever
    const btnPlay            = document.getElementById("btn-play");
    const btnScan            = document.getElementById("btn-scan");
    const btnSync            = document.getElementById("btn-sync");
    const liveToggleSwitch   = document.getElementById("live-toggle-switch");
    const liveToggleLever    = document.getElementById("live-toggle-lever");
    const liveWarningLed     = document.getElementById("live-warning-led");

    // Auth Mainframe Overlay Elements
    const loginOverlay       = document.getElementById("login-overlay");
    const loginCliLog        = document.getElementById("login-cli-log");
    const loginMobileInput   = document.getElementById("login-mobile-input");
    const loginOtpInput      = document.getElementById("login-otp-input");
    const loginUsernameInput = document.getElementById("login-username-input");
    const loginPasswordInput = document.getElementById("login-password-input");

    const formOtp            = document.getElementById("login-form-otp");
    const formVerify         = document.getElementById("login-form-verify");
    const formPwd            = document.getElementById("login-form-pwd");

    // AI Coprocessor Panels
    const tabBtnStatus       = document.getElementById("tab-btn-status");
    const tabBtnResume       = document.getElementById("tab-btn-resume");
    const tabBtnHeadline     = document.getElementById("tab-btn-headline");
    const tabBtnApi          = document.getElementById("tab-btn-api");

    const tabContentStatus   = document.getElementById("ai-tab-status");
    const tabContentResume   = document.getElementById("ai-tab-resume");
    const tabContentHeadline = document.getElementById("ai-tab-headline");
    const tabContentApi      = document.getElementById("ai-tab-api");

    const toastContainer     = document.getElementById("toast-container");

    // ---- State ----
    let lastLogLength = 0;
    let timelineEvents = [];
    let startTime = Date.now();
    let prevDaemonActive = null;
    let isLiveMode = false;
    let isAuthOverlayVisible = false;
    let registeredMobile = "8019642185";

    // ---- Web Audio Retro Click Synthesizer ----
    function playMechanicalSound(pitch = 140, duration = 0.05, type = "sine") {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();
            
            osc.type = type;
            osc.frequency.setValueAtTime(pitch, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(pitch * 0.3, ctx.currentTime + duration);
            
            gainNode.gain.setValueAtTime(0.04, ctx.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
            
            osc.connect(gainNode);
            gainNode.connect(ctx.destination);
            
            osc.start();
            osc.stop(ctx.currentTime + duration);
        } catch(e) {}
    }

    // Attach click sound to keyboard inputs and console buttons
    document.addEventListener("keydown", (e) => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
            playMechanicalSound(350, 0.02, "triangle");
        }
    });

    function registerSoundEvent(el, pitch = 120, duration = 0.06, type = "sine") {
        if (el) {
            el.addEventListener("click", () => playMechanicalSound(pitch, duration, type));
        }
    }

    // ---- Digital Clock ----
    function updateClock() {
        const now = new Date();
        clockEl.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    }
    setInterval(updateClock, 1000);
    updateClock();

    // ---- Greeting System ----
    function setGreeting() {
        const h = new Date().getHours();
        let greeting = "SYSTEM BOOT SUCCESS";
        if (h < 12) greeting = "GOOD MORNING, PRUDHVI";
        else if (h < 17) greeting = "GOOD AFTERNOON, PRUDHVI";
        else greeting = "GOOD EVENING, PRUDHVI";
        greetingText.textContent = greeting;
    }
    setGreeting();

    // ---- Uptime HUD ----
    function updateUptime() {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const m = Math.floor(elapsed / 60);
        const h = Math.floor(m / 60);
        if (h > 0) uptimeText.textContent = `Uptime // ${h}H ${m % 60}M`;
        else if (m > 0) uptimeText.textContent = `Uptime // ${m}M`;
        else uptimeText.textContent = `Uptime // ${elapsed}S`;
    }
    setInterval(updateUptime, 5000);
    updateUptime();

    // ---- Analog LED UV Meters Bouncer ----
    let restingVU = true;
    function bounceVUMeters(intensity = 0.2) {
        const channels = document.querySelectorAll(".vu-channel .vu-light");
        channels.forEach((light, i) => {
            let height = 0;
            if (restingVU) {
                // Low resting wave
                const cycle = Date.now() / 400;
                height = Math.abs(Math.sin(cycle + i)) * 12 + Math.random() * 6;
            } else {
                // High activity surge
                height = Math.random() * 70 + intensity * 30;
                if (i === 0 || i === 9) height *= 0.6; // lower edge bounds
            }
            light.style.height = `${Math.min(100, Math.max(0, height))}%`;
        });
    }

    // Resting VU bounce loop
    setInterval(() => {
        bounceVUMeters();
    }, 100);

    function triggerVUSurge() {
        restingVU = false;
        setTimeout(() => {
            restingVU = true;
        }, 1500);
    }

    // ---- Ambient CRT Toast Notifications ----
    function showToast(message, type = "info") {
        const toast = document.createElement("div");
        toast.className = `toast toast-${type}`;
        let icon = "fa-circle-info";
        if (type === "success") icon = "fa-circle-check";
        if (type === "error") icon = "fa-circle-xmark";
        
        toast.innerHTML = `<i class="fa-solid ${icon} toast-icon"></i><span>${message.toUpperCase()}</span>`;
        toastContainer.appendChild(toast);
        
        playMechanicalSound(500, 0.08, "triangle");
        
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(30px)";
            toast.style.transition = "all 0.3s ease";
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // ---- Escape HTML ----
    function esc(str) {
        if (!str) return "";
        return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }

    // ---- Incident Timeline ----
    function addTimelineEvent(msg, type = "info") {
        const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
        timelineEvents.unshift({ msg, type, time });
        if (timelineEvents.length > 80) timelineEvents.pop();
        renderTimeline();
    }

    function renderTimeline() {
        if (timelineEvents.length === 0) return;
        timelineCount.textContent = `${timelineEvents.length} ALERTS`;
        timelineContainer.innerHTML = timelineEvents.map(ev => `
            <div class="tl-item">
                <div class="tl-dot dot-${ev.type}"></div>
                <div class="tl-content">
                    <div class="tl-msg">${esc(ev.msg).toUpperCase()}</div>
                    <div class="tl-time">${ev.time}</div>
                </div>
            </div>
        `).join("");
    }

    // ---- CRT Terminal Log Rendering ----
    function appendTerminalLine(line) {
        if (!line.trim()) return;
        const span = document.createElement("span");
        const clean = line.trim();

        if (clean.includes("[ERROR]") || clean.includes("ERROR"))        span.className = "t-error";
        else if (clean.includes("✅") || clean.includes("[SUCCESS]"))     span.className = "t-success";
        else if (clean.includes("[WARNING]") || clean.includes("[skip]")) span.className = "t-warning";
        else if (clean.includes("[SYS]") || clean.includes("[INFO]") || clean.includes("[START]"))     span.className = "t-system";
        else if (clean.includes("fetch") || clean.includes("Fetching") || clean.includes("internship-fetch")) span.className = "t-fetch";
        else span.className = "t-info";

        span.textContent = clean;
        terminalOutput.appendChild(span);

        // Limit to 400 lines in CRT buffer
        while (terminalOutput.children.length > 400) {
            terminalOutput.removeChild(terminalOutput.firstChild);
        }
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
        
        // Bounces VU meter dynamically for every line
        triggerVUSurge();
    }

    // ---- Parse log lines for timeline events ----
    function extractTimelineEvents(line) {
        const clean = line.trim();
        if (!clean) return;

        if (clean.includes("Successfully established active Naukri session")) {
            addTimelineEvent("Naukri authentication confirmed", "success");
        } else if (clean.includes("Profile successfully refreshed")) {
            addTimelineEvent("Naukri profile boosted -> visibility active", "success");
        } else if (clean.includes("Generating SEO-optimized headline")) {
            addTimelineEvent("Copressing optimized Naukri SEO headlines...", "ai");
        } else if (clean.includes("Submitting profile headline update")) {
            const match = clean.match(/update: '(.+)'/);
            addTimelineEvent(`Naukri headline written: ${match ? match[1] : "new headline"}`, "ai");
        } else if (clean.includes("Resume update status: 200") || clean.includes("Resume upload response")) {
            addTimelineEvent("Master candidate resume re-uploaded", "success");
        } else if (clean.includes("Fetching and analyzing")) {
            addTimelineEvent("Scanning Bangalore job networks...", "info");
        } else if (clean.includes("Fetched") && clean.includes("total job listings")) {
            const match = clean.match(/Fetched (\d+) total/);
            addTimelineEvent(`Indexed ${match ? match[1] : "?"} fresh vacancy slots`, "info");
        } else if (clean.includes("Found") && clean.includes("matched jobs")) {
            const match = clean.match(/Found (\d+) matched/);
            addTimelineEvent(`Matched ${match ? match[1] : "?"} target internship slots`, "success");
        } else if (clean.includes("Applied successfully") || clean.includes("Application submitted")) {
            addTimelineEvent(clean.substring(clean.indexOf("]") + 1).trim(), "success");
        } else if (clean.includes("Sleeping for")) {
            const match = clean.match(/Sleeping for ([\d.]+) hours/);
            addTimelineEvent(`Sweep cycle finished. Next sweep in ${match ? match[1] : "2"}H`, "warning");
        } else if (clean.includes("CAREERFLOW AI AUTONOMOUS ASSISTANT ACTIVATED")) {
            addTimelineEvent("Autonomous AI daemon initialized", "success");
        } else if (clean.includes("[START]") && clean.includes("background execution")) {
            const match = clean.match(/'(.+)'/);
            addTimelineEvent(`Launched console workflow: ${match ? match[1] : "Job Scan"}`, "info");
        }
    }

    // ---- Authenticated Status Polling ----
    async function fetchStatus() {
        try {
            const res = await fetch("/api/status");
            const data = await res.json();

            // Handle Secure Auth Shell Overlay visibility
            if (!data.authenticated) {
                if (!isAuthOverlayVisible) {
                    loginOverlay.classList.remove("hidden");
                    isAuthOverlayVisible = true;
                    addTimelineEvent("Core access blocked — session expired", "error");
                    loginCliLog.innerHTML = "[SYS] HANDSHAKE REQUIRED: Verify Naukri session.";
                }
            } else {
                if (isAuthOverlayVisible) {
                    loginOverlay.classList.add("hidden");
                    isAuthOverlayVisible = false;
                    addTimelineEvent("Access unblocked. Secure session active", "success");
                    showToast("Authentication confirmed!", "success");
                }
            }

            // Sync registered mobile number
            if (data.mobile) {
                registeredMobile = data.mobile;
                if (!loginMobileInput.value) {
                    loginMobileInput.value = data.mobile;
                }
            }

            // Daemon or background active workflow state
            const isActive = !!data.running_task;
            if (isActive) {
                statusOrb.className = "status-orb orb-active";
                daemonLabel.textContent = (data.running_task || "AUTONOMOUS DAEMON ACTIVE").toUpperCase();
                daemonLabel.className = "status-label label-active";
                terminalStatus.className = "terminal-badge badge-running";
                terminalStatus.innerHTML = '<span class="pulse-dot"></span> RUNNING';
                vhsTapeBody.classList.add("spinning"); // Spin VHS gears!
            } else {
                statusOrb.className = "status-orb orb-sleeping";
                daemonLabel.textContent = "DAEMON IDLE // WAITING FOR CYCLE";
                daemonLabel.className = "status-label label-sleeping";
                terminalStatus.className = "terminal-badge badge-idle";
                terminalStatus.innerHTML = '<span class="pulse-dot"></span> IDLE';
                vhsTapeBody.classList.remove("spinning"); // Stop VHS gears!
            }

            // Operator details
            if (data.profile) {
                aiProfile.textContent = data.profile.name || "Prudhvi Raj";
                aiHeadline.textContent = data.profile.headline || "—";
                aiHeadline.title = data.profile.headline || "";

                const completeness = data.profile.completeness || 85;
                statVisibility.textContent = `${completeness}%`;
                
                const ringElement = document.getElementById("ring-fill");
                if (ringElement) {
                    ringElement.setAttribute("stroke-dasharray", `${completeness}, 100`);
                }
            }

            prevDaemonActive = isActive;

        } catch (err) {
            statusOrb.className = "status-orb orb-inactive";
            daemonLabel.textContent = "CONSOLE LINK OFFLINE";
            daemonLabel.className = "status-label label-offline";
        }
    }

    // ---- Stats & Reels Tape Ribbon Ratio ----
    async function fetchStats() {
        try {
            const res = await fetch("/api/stats");
            const data = await res.json();

            animateNumber(statScanned, data.plan_total || 0);
            animateNumber(statMatched, data.plan_total || 0);
            animateNumber(statApplied, data.applied_total || 0);
            animateNumber(statSyncs, data.profile_refreshes_total || 0);

            appsCount.textContent = `${data.applied_total || 0} TOTAL`;

            // Calculate VHS tape ribbon shifting skeuomorphic ratios
            // More applied jobs = thicker right reel tape, smaller left reel tape
            const totalJobs = Math.max(10, (data.plan_total || 0) + (data.applied_total || 0));
            const rightRatio = (data.applied_total || 0) / totalJobs;
            const leftScale = 0.85 - (rightRatio * 0.5); // Shrink from 0.85 to 0.35
            const rightScale = 0.25 + (rightRatio * 0.55); // Grow from 0.25 to 0.8

            leftTapePack.style.transform = `scale(${leftScale})`;
            rightTapePack.style.transform = `scale(${rightScale})`;

            // Load and render persistent timeline events from database
            if (data.timeline && data.timeline.length > 0) {
                timelineEvents = data.timeline.map(item => ({
                    msg: item.message,
                    type: item.type,
                    time: item.time
                }));
                renderTimeline();
            }

            renderApplications(data.recent_applications || []);

        } catch (err) {
            console.error("Stats fetching link decay:", err);
        }
    }

    // ---- Number Counter Incrementor ----
    function animateNumber(el, target) {
        const current = parseInt(el.textContent) || 0;
        if (current === target) return;
        const diff = target - current;
        const steps = 15;
        const stepVal = diff / steps;
        let i = 0;
        const interval = setInterval(() => {
            i++;
            el.textContent = Math.round(current + stepVal * i);
            if (i >= steps) {
                el.textContent = target;
                clearInterval(interval);
            }
        }, 25);
    }

    // ---- Applications Ticker Table ----
    function renderApplications(records) {
        if (!records || records.length === 0) {
            appsContainer.innerHTML = `
                <div class="apps-empty">
                    <i class="fa-solid fa-inbox fa-2x"></i>
                    <p>No job submissions logged in current cycle.</p>
                </div>`;
            return;
        }

        appsContainer.innerHTML = records.map(row => {
            let appliedAt = "";
            if (row.applied_at) {
                try {
                    const dt = new Date(row.applied_at);
                    appliedAt = dt.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
                } catch(e) {}
            }
            const score = parseInt(row.score || 0);
            let scoreClass = "score-low";
            if (score >= 75) scoreClass = "score-high";
            else if (score >= 60) scoreClass = "score-mid";

            return `
                <div class="app-row">
                    <div class="app-info">
                        <span class="app-title">${esc(row.title).toUpperCase()}</span>
                        <span class="app-company">${esc(row.company).toUpperCase()}</span>
                    </div>
                    <span class="app-score ${scoreClass}">${score}</span>
                    <span class="app-time">${appliedAt.toUpperCase()}</span>
                </div>`;
        }).join("");
    }

    // ---- Real-time Logs Feed ----
    async function fetchLogs() {
        try {
            const res = await fetch("/api/logs");
            const data = await res.json();
            const raw = data.logs || "";
            const lines = raw.split("\n");

            if (lines.length > lastLogLength) {
                const newLines = lines.slice(lastLogLength);
                newLines.forEach(line => {
                    appendTerminalLine(line);
                    extractTimelineEvents(line);
                });
                lastLogLength = lines.length;
            }

            // Sync log indicator status
            if (data.running) {
                terminalStatus.className = "terminal-badge badge-running";
                terminalStatus.innerHTML = '<span class="pulse-dot"></span> RUNNING';
                vhsTapeBody.classList.add("spinning");
            }
        } catch (err) {
            console.error("CRT connection logs decay:", err);
        }
    }

    // ---- AI Engine Hub Status ----
    async function fetchAiStatus() {
        try {
            const res = await fetch("/api/ai/status");
            const data = await res.json();

            if (data.api_key_configured) {
                aiBadge.textContent = "ONLINE";
                aiBadge.className = "panel-badge badge-on";
            } else {
                aiBadge.textContent = "OFFLINE";
                aiBadge.className = "panel-badge badge-off";
            }

            const modelShort = (data.model || "").split("/").pop() || "—";
            aiModel.textContent = modelShort.toUpperCase();
            aiApikey.textContent = data.api_key_configured ? data.api_key_preview : "NOT SET";
            aiSkills.textContent = `${data.skills_count || 0} RESUMES`;
            aiProjects.textContent = `${data.projects_count || 0} PARAMS`;

            if (data.candidate_name) {
                aiProfile.textContent = data.candidate_name.toUpperCase();
            }
        } catch (err) {
            console.error("Co-processor telemetry error:", err);
        }
    }

    // ---- Next Scan Cycle Countdown ----
    let cycleStart = Date.now();
    const CYCLE_MS = 2 * 60 * 60 * 1000; // 2 hours

    function updateNextCycle() {
        const elapsed = Date.now() - cycleStart;
        const remaining = Math.max(0, CYCLE_MS - elapsed);
        const mins = Math.floor(remaining / 60000);
        const hrs = Math.floor(mins / 60);
        if (remaining <= 0) {
            aiNextCycle.textContent = "CYCLE EXECUTING NOW...";
            cycleStart = Date.now();
        } else if (hrs > 0) {
            aiNextCycle.textContent = `~${hrs}H ${mins % 60}M`;
        } else {
            aiNextCycle.textContent = `~${mins}M`;
        }
    }
    setInterval(updateNextCycle, 30000);
    updateNextCycle();

    // ---- Greeting sub-text rotations ----
    const subTexts = [
        "Autonomous operations running. Operator relaxed.",
        "Polling Bangalore internship networks...",
        "Keeping candidate profile fresh & visible.",
        "Tailoring SEO resumes dynamically per match.",
        "Fully autonomous mode — zero manual syncs.",
        "AI Co-processors standing by."
    ];
    let subIdx = 0;
    setInterval(() => {
        subIdx = (subIdx + 1) % subTexts.length;
        greetingSub.style.opacity = "0";
        setTimeout(() => {
            greetingSub.textContent = subTexts[subIdx];
            greetingSub.style.opacity = "1";
        }, 400);
    }, 8000);
    greetingSub.style.transition = "opacity 0.4s ease";

    // ==========================================
    // 3. PHYSICAL INTERACTIVE BUTTON TRIGGERS
    // ==========================================

    // Dynamic Chunky Live Toggle Lever
    registerSoundEvent(liveToggleSwitch, 110, 0.08, "triangle");
    liveToggleSwitch.addEventListener("click", () => {
        isLiveMode = !isLiveMode;
        if (isLiveMode) {
            liveToggleSwitch.classList.add("toggle-active");
            liveWarningLed.classList.add("led-blink");
            showToast("LIVE ACTION MODE DEPLOYED!", "error");
            addTimelineEvent("Lever set to LIVE: submissions authorized", "warning");
        } else {
            liveToggleSwitch.classList.remove("toggle-active");
            liveWarningLed.classList.remove("led-blink");
            showToast("Dry-run preview mode set.", "info");
            addTimelineEvent("Lever set to DRY: preview cycles active", "info");
        }
    });

    // SCAN PUSH BUTTON (Match/Plan flow)
    registerSoundEvent(btnScan, 140, 0.12, "sawtooth");
    btnScan.addEventListener("click", async () => {
        if (btnScan.disabled) return;
        showToast("PLANNING FLOW REQUESTED...", "info");
        
        try {
            const res = await fetch("/api/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "plan", confirm: false })
            });
            const data = await res.json();
            if (data.success) {
                showToast("Job scans initialized!", "success");
            } else {
                showToast(data.message || "Execution blocked.", "error");
            }
        } catch(e) {
            showToast("FastAPI host unreachable.", "error");
        }
    });

    // PLAY PUSH BUTTON (Apply flow)
    registerSoundEvent(btnPlay, 100, 0.15, "sawtooth");
    btnPlay.addEventListener("click", async () => {
        if (btnPlay.disabled) return;
        const msg = isLiveMode ? "LIVE SUBMISSION LAUNCHED!" : "DRY SCAN INITIALIZED...";
        showToast(msg, isLiveMode ? "error" : "info");
        
        try {
            const res = await fetch("/api/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "apply", confirm: isLiveMode })
            });
            const data = await res.json();
            if (data.success) {
                showToast("Application deck operational!", "success");
            } else {
                showToast(data.message || "Workflow blocked.", "error");
            }
        } catch(e) {
            showToast("FastAPI host unreachable.", "error");
        }
    });

    // SYNC PUSH BUTTON (Refresh profile)
    registerSoundEvent(btnSync, 180, 0.1, "sawtooth");
    btnSync.addEventListener("click", async () => {
        if (btnSync.disabled) return;
        const msg = isLiveMode ? "LIVE PROFILE REWRITE LAUNCHED!" : "PROFILE REWRITE PREVIEW...";
        showToast(msg, isLiveMode ? "error" : "info");

        try {
            const res = await fetch("/api/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "refresh", confirm: isLiveMode })
            });
            const data = await res.json();
            if (data.success) {
                showToast("Profile updater processing!", "success");
            } else {
                showToast(data.message || "Refresh rejected.", "error");
            }
        } catch(e) {
            showToast("FastAPI host unreachable.", "error");
        }
    });

    // CRT Toggle Switch (De-gauss)
    registerSoundEvent(crtEffectSwitch, 280, 0.04, "sine");
    crtEffectSwitch.addEventListener("change", (e) => {
        if (e.target.checked) {
            crtDisplayScreen.classList.add("crt-effect-active");
            masterPowerLed.classList.add("glow-red");
            showToast("CRT DE-GAUSS EFFECT DEPLOYED.", "success");
        } else {
            crtDisplayScreen.classList.remove("crt-effect-active");
            masterPowerLed.classList.remove("glow-red");
            showToast("Flat screen matrix mode set.", "info");
        }
    });

    // ==========================================
    // 4. RETRO MAIN SECURE AUTHENTICATION MATRIX
    // ==========================================
    const toggleToPwdBtn = document.getElementById("btn-toggle-password-mode");
    const toggleToOtpBtn = document.getElementById("btn-toggle-otp-mode");
    const btnRequestOtp = document.getElementById("btn-request-otp");
    const btnVerifyOtp = document.getElementById("btn-verify-otp");
    const btnCancelVerify = document.getElementById("btn-cancel-verify");
    const btnLoginPwd = document.getElementById("btn-login-pwd");

    registerSoundEvent(toggleToPwdBtn, 200, 0.04, "sine");
    toggleToPwdBtn.addEventListener("click", (e) => {
        e.preventDefault();
        formOtp.className = "login-form-hidden";
        formPwd.className = "login-form-active";
        loginCliLog.innerHTML = "[SYS] Entering password secure authentication mode...";
    });

    registerSoundEvent(toggleToOtpBtn, 200, 0.04, "sine");
    toggleToOtpBtn.addEventListener("click", (e) => {
        e.preventDefault();
        formPwd.className = "login-form-hidden";
        formOtp.className = "login-form-active";
        loginCliLog.innerHTML = "[SYS] Entering mobile OTP authentication mode...";
    });

    registerSoundEvent(btnCancelVerify, 150, 0.06, "sine");
    btnCancelVerify.addEventListener("click", (e) => {
        e.preventDefault();
        formVerify.className = "login-form-hidden";
        formOtp.className = "login-form-active";
        loginCliLog.innerHTML = "[SYS] OTP verification sequence cancelled.";
    });

    // Send OTP handler
    registerSoundEvent(btnRequestOtp, 160, 0.1, "triangle");
    btnRequestOtp.addEventListener("click", async (e) => {
        e.preventDefault();
        const mobile = loginMobileInput.value.trim();
        if (!mobile) {
            loginCliLog.innerHTML = "[ERROR] Input invalid: Enter registered mobile #.";
            return;
        }

        loginCliLog.innerHTML = `[SYS] Connecting to Naukri servers for +91${mobile}...`;
        btnRequestOtp.disabled = true;

        try {
            const res = await fetch("/api/send-otp", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mobile })
            });
            const data = await res.json();
            btnRequestOtp.disabled = false;
            
            if (data.success) {
                registeredMobile = mobile;
                formOtp.className = "login-form-hidden";
                formVerify.className = "login-form-active";
                loginCliLog.innerHTML = `[SUCCESS] OTP sent successfully! Verify login code.`;
                showToast("OTP sent to mobile!", "success");
            } else {
                loginCliLog.innerHTML = `[ERROR] OTP request failed: ${data.error || "Unknown"}`;
                showToast("OTP request failed.", "error");
            }
        } catch (err) {
            btnRequestOtp.disabled = false;
            loginCliLog.innerHTML = "[ERROR] Telemetry decay: Flask unreachable.";
        }
    });

    // Verify OTP handler
    registerSoundEvent(btnVerifyOtp, 160, 0.1, "triangle");
    btnVerifyOtp.addEventListener("click", async (e) => {
        e.preventDefault();
        const otp = loginOtpInput.value.trim();
        if (!otp || otp.length < 4) {
            loginCliLog.innerHTML = "[ERROR] Handshake invalid: Provide complete OTP.";
            return;
        }

        loginCliLog.innerHTML = `[SYS] Verifying security token '${otp}'...`;
        btnVerifyOtp.disabled = true;

        try {
            const res = await fetch("/api/verify-otp", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mobile: registeredMobile, otp })
            });
            const data = await res.json();
            btnVerifyOtp.disabled = false;

            if (data.success) {
                loginCliLog.innerHTML = "[SUCCESS] Handshake verified! System unblocking...";
                showToast("Access confirmed!", "success");
                setTimeout(() => {
                    loginOverlay.classList.add("hidden");
                    isAuthOverlayVisible = false;
                    fetchStatus();
                }, 800);
            } else {
                loginCliLog.innerHTML = `[ERROR] Handshake failed: ${data.error || "Incorrect Code"}`;
                showToast("Incorrect security code.", "error");
            }
        } catch (err) {
            btnVerifyOtp.disabled = false;
            loginCliLog.innerHTML = "[ERROR] Handshake decay: Host unreachable.";
        }
    });

    // Password login handler
    registerSoundEvent(btnLoginPwd, 160, 0.1, "triangle");
    btnLoginPwd.addEventListener("click", async (e) => {
        e.preventDefault();
        const username = loginUsernameInput.value.trim();
        const password = loginPasswordInput.value.trim();
        
        if (!username || !password) {
            loginCliLog.innerHTML = "[ERROR] Input invalid: Provide Naukri username and passcode.";
            return;
        }

        loginCliLog.innerHTML = `[SYS] Connecting password secure session for ${username}...`;
        btnLoginPwd.disabled = true;

        try {
            const res = await fetch("/api/login-password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();
            btnLoginPwd.disabled = false;

            if (data.success) {
                loginCliLog.innerHTML = "[SUCCESS] Password verified! System unblocking...";
                showToast("Credentials confirmed!", "success");
                setTimeout(() => {
                    loginOverlay.classList.add("hidden");
                    isAuthOverlayVisible = false;
                    fetchStatus();
                }, 800);
            } else {
                loginCliLog.innerHTML = `[ERROR] Secure session failed: ${data.error || "Bad Credentials"}`;
                showToast(data.error || "Bad username or passcode.", "error");
            }
        } catch (err) {
            btnLoginPwd.disabled = false;
            loginCliLog.innerHTML = "[ERROR] Connection decay: Host unreachable.";
        }
    });

    // ==========================================
    // 5. TABBED CO-PROCESSOR AI ENGINE PANEL
    // ==========================================
    const tabs = [
        { btn: tabBtnStatus, content: tabContentStatus },
        { btn: tabBtnResume, content: tabContentResume },
        { btn: tabBtnHeadline, content: tabContentHeadline },
        { btn: tabBtnApi, content: tabContentApi }
    ];

    tabs.forEach(tab => {
        registerSoundEvent(tab.btn, 220, 0.05, "sine");
        tab.btn.addEventListener("click", () => {
            tabs.forEach(t => {
                t.btn.classList.remove("tab-active");
                t.content.className = "ai-tab-content-hidden";
            });
            tab.btn.classList.add("tab-active");
            tab.content.className = "ai-tab-content-active";
        });
    });

    // Tab 2: Resume tailoring handler
    const btnTriggerTailor  = document.getElementById("btn-trigger-tailor");
    const aiTailorTitle     = document.getElementById("ai-tailor-title");
    const aiTailorCompany   = document.getElementById("ai-tailor-company");
    const aiTailorDesc      = document.getElementById("ai-tailor-desc");
    const aiTailorResult    = document.getElementById("ai-tailor-result");
    const aiTailorOutput    = document.getElementById("ai-tailor-output");

    registerSoundEvent(btnTriggerTailor, 120, 0.12, "sawtooth");
    btnTriggerTailor.addEventListener("click", async () => {
        const title = aiTailorTitle.value.trim();
        const company = aiTailorCompany.value.trim();
        const desc = aiTailorDesc.value.trim();

        if (!title || !desc) {
            showToast("Provide title and requirements.", "error");
            return;
        }

        btnTriggerTailor.disabled = true;
        aiTailorResult.classList.remove("hidden");
        aiTailorOutput.textContent = "CONNECTING CO-PROCESSOR MAINFRAME...\nGENERATING TAILORED RESUME SHARDS...";
        showToast("Synthesizing resume segments...", "info");

        try {
            const res = await fetch("/api/ai/generate-resume", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ job_title: title, company, job_description: desc })
            });
            const data = await res.json();
            btnTriggerTailor.disabled = false;

            if (data.success && data.data) {
                const doc = data.data;
                const formatted = `[SUCCESS] TAILOR COMPLETED.\n\n--- OPTIMIZED KEYWORDS ---\n${(doc.keywords || []).join(", ")}\n\n--- CRITICAL ACHIEVEMENTS ---\n${(doc.achievements || []).map(a => "- " + a).join("\n")}\n\n--- SUMMARY OVERLAY ---\n${doc.summary || "No tailored summary generated"}`;
                typewriterEffect(aiTailorOutput, formatted);
                showToast("Resume tailored successfully!", "success");
            } else {
                aiTailorOutput.textContent = `[ERROR] Synthesis failed: ${data.error || "Mainframe response invalid"}`;
                showToast("AI Synthesis failed.", "error");
            }
        } catch (e) {
            btnTriggerTailor.disabled = false;
            aiTailorOutput.textContent = "[ERROR] AI Link Decay: FastAPI host offline.";
        }
    });

    // Tab 3: Headline Booster handler
    const btnTriggerHeadline = document.getElementById("btn-trigger-headline");
    const aiHeadlineRole     = document.getElementById("ai-headline-role");
    const aiHeadlineResult   = document.getElementById("ai-headline-result");
    const aiHeadlineOutput   = document.getElementById("ai-headline-output");
    const btnHeadlineApply   = document.getElementById("btn-headline-apply-profile");
    let optimizedHeadlineTemp = "";

    registerSoundEvent(btnTriggerHeadline, 120, 0.12, "sawtooth");
    btnTriggerHeadline.addEventListener("click", async () => {
        const role = aiHeadlineRole.value.trim();
        if (!role) {
            showToast("Provide target role.", "error");
            return;
        }

        btnTriggerHeadline.disabled = true;
        aiHeadlineResult.classList.remove("hidden");
        btnHeadlineApply.classList.add("hidden");
        aiHeadlineOutput.textContent = "OPTIMIZING SEARCH PARAMETERS...\nCONSOLIDATING SEO TERM TOKENS...";
        showToast("Synthesizing SEO headline...", "info");

        try {
            const res = await fetch("/api/ai/optimize-headline", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ target_role: role, current_headline: aiHeadline.textContent })
            });
            const data = await res.json();
            btnTriggerHeadline.disabled = false;

            if (data.success && data.data && data.data.headline) {
                optimizedHeadlineTemp = data.data.headline;
                const formatted = `[SUCCESS] SEARCH BOOST COMPLETED.\n\n--- PROPOSED HEADLINE ---\n"${data.data.headline}"\n\n--- METRICS MATCH ---\nSEO keywords loaded into Naukri indexing engine.\nClick WRITE below to flash directly to your live Naukri profile.`;
                typewriterEffect(aiHeadlineOutput, formatted);
                btnHeadlineApply.classList.remove("hidden");
                showToast("Headline booster tailored!", "success");
            } else {
                aiHeadlineOutput.textContent = `[ERROR] Optimization failed: ${data.error || "Mainframe response invalid"}`;
                showToast("SEO booster failed.", "error");
            }
        } catch(e) {
            btnTriggerHeadline.disabled = false;
            aiHeadlineOutput.textContent = "[ERROR] AI Link Decay: FastAPI host offline.";
        }
    });

    // Write Optimized Headline directly to profile
    registerSoundEvent(btnHeadlineApply, 110, 0.15, "sawtooth");
    btnHeadlineApply.addEventListener("click", async () => {
        if (!optimizedHeadlineTemp) return;
        btnHeadlineApply.disabled = true;
        showToast("Submitting profile rewrite...", "info");

        try {
            const res = await fetch("/api/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: "refresh", confirm: true }) // force live refresh update
            });
            const data = await res.json();
            btnHeadlineApply.disabled = false;

            if (data.success) {
                showToast("Profile headline rewrite complete!", "success");
                addTimelineEvent(`Wrote new SEO headline: ${optimizedHeadlineTemp.substring(0, 30)}...`, "ai");
                btnHeadlineApply.classList.add("hidden");
            } else {
                showToast("Failed to write to profile.", "error");
            }
        } catch(e) {
            btnHeadlineApply.disabled = false;
            showToast("Connection decay: Host unreachable.", "error");
        }
    });

    // Tab 4: API Settings handler
    const btnSaveSettings = document.getElementById("btn-save-ai-settings");
    const aiSettingsKey   = document.getElementById("ai-settings-key");
    const aiSettingsModel = document.getElementById("ai-settings-model");

    registerSoundEvent(btnSaveSettings, 130, 0.1, "sine");
    btnSaveSettings.addEventListener("click", async () => {
        const apiKey = aiSettingsKey.value.trim();
        const model = aiSettingsModel.value.trim();

        if (!apiKey && !model) {
            showToast("Provide model parameters to save.", "error");
            return;
        }

        btnSaveSettings.disabled = true;
        showToast("Saving co-processor parameters...", "info");

        try {
            const res = await fetch("/api/ai/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ api_key: apiKey, model: model })
            });
            const data = await res.json();
            btnSaveSettings.disabled = false;

            if (data.success) {
                showToast("Co-processor config saved!", "success");
                aiSettingsKey.value = ""; // clear password text
                fetchAiStatus();
            } else {
                showToast("Save rejected by mainframe.", "error");
            }
        } catch(e) {
            btnSaveSettings.disabled = false;
            showToast("Link decay: host offline.", "error");
        }
    });

    // Typewriter printout micro-animation helper
    function typewriterEffect(el, text) {
        el.textContent = "";
        let i = 0;
        const speed = 12; // fast typing printout
        function type() {
            if (i < text.length) {
                el.textContent += text.charAt(i);
                i++;
                // Play subtle typewriter sound every 3 characters
                if (i % 3 === 0) {
                    playMechanicalSound(420, 0.015, "triangle");
                }
                setTimeout(type, speed);
            }
        }
        type();
    }

    // ---- Boot Matrix Telemetry ----
    addTimelineEvent("Console session synchronized with host", "info");

    fetchStatus();
    fetchStats();
    fetchLogs();
    fetchAiStatus();

    // ---- High Frequency Polling Matrices ----
    setInterval(fetchStatus, 7000);
    setInterval(fetchStats, 12000);
    setInterval(fetchLogs, 2500);
    setInterval(fetchAiStatus, 18000);

});
