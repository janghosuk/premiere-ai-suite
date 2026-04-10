/*
 * Clip Exporter — CEP 패널 메인 스크립트
 * UI 이벤트 처리 + csInterface.evalScript로 ExtendScript 호출
 */

(function () {
    var csInterface = new CSInterface();

    // DOM
    var $ = function (id) { return document.getElementById(id); };
    var outputFolderInput = $("outputFolder");
    var presetPathInput = $("presetPath");
    var namePatternInput = $("namePattern");
    var videoExtSelect = $("videoExt");
    var captureThumbnailCheck = $("captureThumbnail");
    var thumbnailFormatSelect = $("thumbnailFormat");
    var thumbFormatRow = $("thumbFormatRow");
    var exportBtn = $("exportBtn");
    var refreshBtn = $("refreshBtn");
    var browseFolderBtn = $("browseFolderBtn");
    var browsePresetBtn = $("browsePresetBtn");
    var progressBar = $("progressBar");
    var progressText = $("progressText");
    var logWrap = $("logWrap");

    var seqNameEl = $("seqName");
    var clipCountEl = $("clipCount");
    var totalDurEl = $("totalDur");

    var LS_KEYS = {
        outputFolder: "ce.outputFolder",
        presetPath: "ce.presetPath",
        namePattern: "ce.namePattern",
        videoExt: "ce.videoExt",
        captureThumbnail: "ce.captureThumbnail",
        thumbnailFormat: "ce.thumbnailFormat"
    };

    // ── 로깅 ──
    function log(message, tag) {
        var line = document.createElement("div");
        line.className = "log-line " + (tag || "info");
        line.textContent = message;
        logWrap.appendChild(line);
        logWrap.scrollTop = logWrap.scrollHeight;
    }

    function setProgress(pct, text) {
        progressBar.style.width = Math.max(0, Math.min(100, pct)) + "%";
        if (text !== undefined) progressText.textContent = text;
    }

    function formatSec(s) {
        if (typeof s !== "number" || !isFinite(s)) return "—";
        var m = Math.floor(s / 60);
        var sec = s - m * 60;
        return m + ":" + (sec < 10 ? "0" : "") + sec.toFixed(2);
    }

    // ── Settings persistence ──
    function loadSettings() {
        try {
            var v;
            if ((v = localStorage.getItem(LS_KEYS.outputFolder))) outputFolderInput.value = v;
            if ((v = localStorage.getItem(LS_KEYS.presetPath))) presetPathInput.value = v;
            if ((v = localStorage.getItem(LS_KEYS.namePattern))) namePatternInput.value = v;
            if ((v = localStorage.getItem(LS_KEYS.videoExt))) videoExtSelect.value = v;
            if ((v = localStorage.getItem(LS_KEYS.captureThumbnail)) !== null) {
                captureThumbnailCheck.checked = (v === "true");
            }
            if ((v = localStorage.getItem(LS_KEYS.thumbnailFormat))) thumbnailFormatSelect.value = v;
            updateThumbRow();
        } catch (e) {
            log("설정 로드 실패: " + e.message, "error");
        }
    }

    function saveSettings() {
        try {
            localStorage.setItem(LS_KEYS.outputFolder, outputFolderInput.value);
            localStorage.setItem(LS_KEYS.presetPath, presetPathInput.value);
            localStorage.setItem(LS_KEYS.namePattern, namePatternInput.value);
            localStorage.setItem(LS_KEYS.videoExt, videoExtSelect.value);
            localStorage.setItem(LS_KEYS.captureThumbnail, String(captureThumbnailCheck.checked));
            localStorage.setItem(LS_KEYS.thumbnailFormat, thumbnailFormatSelect.value);
        } catch (e) {}
    }

    function updateThumbRow() {
        thumbFormatRow.style.display = captureThumbnailCheck.checked ? "flex" : "none";
    }

    // ── JSX eval 래퍼 ──
    // CEP의 evalScript는 문자열 결과를 콜백으로 전달
    function callJSX(script, callback) {
        csInterface.evalScript(script, function (raw) {
            if (!raw || raw === "undefined" || raw === "null") {
                callback({ ok: false, error: "빈 응답" });
                return;
            }
            try {
                var parsed = JSON.parse(raw);
                callback(parsed);
            } catch (e) {
                callback({ ok: false, error: "JSON 파싱 실패: " + raw.substring(0, 200) });
            }
        });
    }

    // ── 시퀀스 정보 새로고침 ──
    function refreshSequenceInfo() {
        callJSX("ceGetSequenceInfo()", function (res) {
            if (!res.ok) {
                seqNameEl.textContent = "—";
                clipCountEl.textContent = "—";
                totalDurEl.textContent = "—";
                exportBtn.disabled = true;
                log("✗ " + res.error, "error");
                return;
            }
            seqNameEl.textContent = res.sequenceName || "—";
            clipCountEl.textContent = String(res.clipCount || 0);
            totalDurEl.textContent = formatSec(res.totalDuration || 0);
            exportBtn.disabled = (res.clipCount === 0);

            if (res.clipCount > 0) {
                log("✓ 시퀀스: " + res.sequenceName + " (" + res.clipCount + "개 클립)", "success");
            }
        });
    }

    // ── 폴더 / 프리셋 브라우즈 ──
    browseFolderBtn.addEventListener("click", function () {
        callJSX('ceBrowseFolder("출력 폴더 선택")', function (res) {
            if (res.ok) {
                outputFolderInput.value = res.path;
                saveSettings();
            }
        });
    });

    browsePresetBtn.addEventListener("click", function () {
        callJSX("ceBrowsePresetFile()", function (res) {
            if (res.ok) {
                presetPathInput.value = res.path;
                saveSettings();
                log("✓ 프리셋: " + res.path.split("/").pop(), "success");
            }
        });
    });

    // ── 입력 변경시 자동 저장 ──
    [outputFolderInput, presetPathInput, namePatternInput, videoExtSelect,
     captureThumbnailCheck, thumbnailFormatSelect].forEach(function (el) {
        el.addEventListener("change", saveSettings);
        el.addEventListener("input", saveSettings);
    });
    captureThumbnailCheck.addEventListener("change", updateThumbRow);

    refreshBtn.addEventListener("click", refreshSequenceInfo);

    // ── 메인 익스포트 실행 ──
    exportBtn.addEventListener("click", function () {
        var outputFolder = outputFolderInput.value.trim().replace(/\\/g, "/");
        var presetPath = presetPathInput.value.trim().replace(/\\/g, "/");
        var namePattern = namePatternInput.value.trim() || "{sequence}_Clip_{num}";
        var videoExt = videoExtSelect.value;
        var captureThumbnail = captureThumbnailCheck.checked;
        var thumbnailFormat = thumbnailFormatSelect.value;

        if (!outputFolder) {
            log("✗ 출력 폴더를 지정하세요", "error");
            return;
        }
        if (!presetPath) {
            log("✗ Export 프리셋 (.epr)을 지정하세요", "error");
            return;
        }

        saveSettings();
        exportBtn.disabled = true;
        exportBtn.textContent = "처리 중...";
        setProgress(0, "시작");

        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "accent");
        log("출력: " + outputFolder, "info");
        log("프리셋: " + presetPath.split("/").pop(), "info");
        if (captureThumbnail) log("썸네일: " + thumbnailFormat.toUpperCase(), "info");

        // 옵션을 JSON 문자열로 직렬화하여 JSX로 전달
        var opts = {
            outputFolder: outputFolder,
            presetPath: presetPath,
            captureThumbnail: captureThumbnail,
            thumbnailFormat: thumbnailFormat,
            namePattern: namePattern,
            videoExt: videoExt
        };
        var optsJson = JSON.stringify(opts);
        // JSX 문자열 리터럴 안전 이스케이프
        var safeJson = optsJson.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        var jsxCall = 'ceExportAllClips("' + safeJson + '")';

        log("익스포트 시작... (클립 하나당 수초~수분 소요)", "info");
        setProgress(10, "Premiere에서 익스포트 중...");

        // 주의: exportAsMediaDirect는 동기식 블로킹 호출이며
        // 전체 클립이 모두 끝날 때까지 이 콜백은 발생하지 않음
        callJSX(jsxCall, function (res) {
            exportBtn.disabled = false;
            exportBtn.textContent = "▶  타임라인 클립 일괄 익스포트";

            if (!res.ok) {
                log("✗ 실패: " + res.error, "error");
                setProgress(0, "실패");
                return;
            }

            setProgress(100, "완료");
            log("", "info");
            log("✓ 완료: " + res.succeeded + "/" + res.total + " 성공", "success");
            if (res.failed > 0) {
                log("⚠ " + res.failed + "개 실패", "error");
            }

            // 각 클립 결과 상세
            (res.results || []).forEach(function (r) {
                var tag = r.videoOk ? "success" : "error";
                var status = r.videoOk ? "✓" : "✗";
                var thumbStatus = r.thumbOk ? " 🖼" : (captureThumbnail ? " (썸네일 실패)" : "");
                log("  " + status + " [" + String(r.index).padStart(3, "0") + "] " +
                    r.name + thumbStatus, tag);
                if (r.error) log("      → " + r.error, "dim");
            });

            log("", "info");
            log("📁 저장 위치: " + res.outputFolder, "accent");
        });
    });

    // ── 초기화 ──
    loadSettings();
    refreshSequenceInfo();

    log("Clip Exporter v1.0 준비 완료", "accent");
})();
