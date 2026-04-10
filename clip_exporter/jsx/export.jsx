/*
 * Clip Exporter — ExtendScript host 로직
 *
 * 주요 함수:
 *   ceGetSequenceInfo()                — 활성 시퀀스의 클립 목록 반환
 *   ceExportThumbnail(outputPath, ticks, format)
 *                                      — 특정 시간의 프레임을 JPEG/PNG로 캡처
 *   ceExportClip(outputPath, presetPath, startTicks, endTicks)
 *                                      — 단일 클립을 exportAsMediaDirect로 저장
 *   ceExportAllClips(optionsJson)      — 전체 클립 일괄 처리 (메인 엔트리)
 *
 * CEP main.js에서 csInterface.evalScript로 호출.
 */

var TPS = 254016000000; // Adobe ticks per second

function _ok(obj) {
    obj = obj || {};
    obj.ok = true;
    return _stringify(obj);
}

function _err(msg, extra) {
    var o = { ok: false, error: String(msg) };
    if (extra) {
        for (var k in extra) {
            if (extra.hasOwnProperty(k)) o[k] = extra[k];
        }
    }
    return _stringify(o);
}

// ExtendScript는 네이티브 JSON이 없을 수 있으므로 간단한 직렬화기 제공
function _stringify(obj) {
    if (obj === null || obj === undefined) return "null";
    var t = typeof obj;
    if (t === "number") return isFinite(obj) ? String(obj) : "null";
    if (t === "boolean") return obj ? "true" : "false";
    if (t === "string") return '"' + obj.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
                                         .replace(/\n/g, "\\n").replace(/\r/g, "\\r")
                                         .replace(/\t/g, "\\t") + '"';
    if (obj instanceof Array) {
        var parts = [];
        for (var i = 0; i < obj.length; i++) parts.push(_stringify(obj[i]));
        return "[" + parts.join(",") + "]";
    }
    if (t === "object") {
        var ps = [];
        for (var k in obj) {
            if (obj.hasOwnProperty(k)) {
                ps.push('"' + k + '":' + _stringify(obj[k]));
            }
        }
        return "{" + ps.join(",") + "}";
    }
    return '""';
}

function _pad(n, width) {
    var s = String(n);
    while (s.length < width) s = "0" + s;
    return s;
}

function _sanitize(name) {
    return String(name).replace(/[<>:"/\\|?*]/g, "_");
}

function _joinPath(folder, file) {
    folder = String(folder).replace(/[\\\/]+$/, "");
    return folder + "/" + file;
}

// ─────────────────────────────────────
// 시퀀스 정보 조회
// ─────────────────────────────────────
function ceGetSequenceInfo() {
    try {
        var seq = app.project.activeSequence;
        if (!seq) return _err("활성 시퀀스가 없습니다. Premiere에서 시퀀스를 여세요.");

        if (!seq.videoTracks || seq.videoTracks.numTracks === 0) {
            return _err("시퀀스에 비디오 트랙이 없습니다.");
        }

        var track = seq.videoTracks[0];
        var clipCount = track.clips.numItems;
        var clips = [];
        var totalDur = 0;

        for (var i = 0; i < clipCount; i++) {
            var c = track.clips[i];
            var startSec = c.start.ticks / TPS;
            var endSec = c.end.ticks / TPS;
            var dur = endSec - startSec;
            totalDur += dur;
            clips.push({
                index: i,
                name: c.name || "Clip " + (i + 1),
                startSec: startSec,
                endSec: endSec,
                durationSec: dur,
                startTicks: String(c.start.ticks),
                endTicks: String(c.end.ticks)
            });
        }

        return _ok({
            sequenceName: seq.name,
            clipCount: clipCount,
            totalDuration: totalDur,
            clips: clips
        });
    } catch (e) {
        return _err("시퀀스 정보 조회 실패: " + e.toString());
    }
}

// ─────────────────────────────────────
// 단일 프레임 캡처 (JPEG/PNG)
// ─────────────────────────────────────
function ceExportThumbnail(outputPath, ticksStr, format) {
    try {
        var seq = app.project.activeSequence;
        if (!seq) return _err("활성 시퀀스 없음");

        // Playhead를 해당 시간으로 이동
        seq.setPlayerPosition(ticksStr);

        format = (format || "jpg").toLowerCase();

        // Premiere Pro의 exportFrame* 함수들은 현재 CTI 위치의 프레임을 파일로 저장
        if (format === "jpg" || format === "jpeg") {
            if (typeof seq.exportFrameJPEG === "function") {
                seq.exportFrameJPEG(outputPath);
            } else if (typeof seq.exportFramePNG === "function") {
                // JPEG 미지원이면 PNG로 폴백
                outputPath = outputPath.replace(/\.jpe?g$/i, ".png");
                seq.exportFramePNG(outputPath);
            } else {
                return _err("exportFrameJPEG 미지원 (Premiere 버전 확인)");
            }
        } else if (format === "png") {
            if (typeof seq.exportFramePNG === "function") {
                seq.exportFramePNG(outputPath);
            } else {
                return _err("exportFramePNG 미지원");
            }
        } else if (format === "tiff") {
            if (typeof seq.exportFrameTIFF === "function") {
                seq.exportFrameTIFF(outputPath);
            } else {
                return _err("exportFrameTIFF 미지원");
            }
        } else {
            return _err("지원하지 않는 포맷: " + format);
        }

        return _ok({ path: outputPath });
    } catch (e) {
        return _err("프레임 캡처 실패: " + e.toString());
    }
}

// ─────────────────────────────────────
// 단일 클립 익스포트
// ─────────────────────────────────────
function ceExportClip(outputPath, presetPath, startSec, endSec) {
    try {
        var seq = app.project.activeSequence;
        if (!seq) return _err("활성 시퀀스 없음");

        var f = new File(presetPath);
        if (!f.exists) {
            return _err("프리셋 파일을 찾을 수 없음: " + presetPath);
        }

        // In/Out 포인트를 클립 구간으로 설정
        seq.setInPoint(startSec);
        seq.setOutPoint(endSec);

        // ENCODE_IN_TO_OUT = 1
        // exportAsMediaDirect는 동기식이며 완료될 때까지 블록됨
        var result = seq.exportAsMediaDirect(outputPath, presetPath, 1);

        // exportAsMediaDirect는 성공 시 빈 문자열, 실패 시 오류 메시지 반환
        if (result && result.length > 0) {
            return _err("익스포트 실패: " + result);
        }

        return _ok({ path: outputPath });
    } catch (e) {
        return _err("ceExportClip 예외: " + e.toString());
    }
}

// ─────────────────────────────────────
// 일괄 익스포트 — 메인 엔트리
// ─────────────────────────────────────
// optionsJson 파라미터 (문자열):
// {
//   "outputFolder": "C:/...",
//   "presetPath": "C:/.../MyPreset.epr",
//   "captureThumbnail": true,
//   "thumbnailFormat": "jpg",
//   "namePattern": "{sequence}_Clip_{num}",
//   "videoExt": "mp4"
// }
function ceExportAllClips(optionsJson) {
    try {
        var opts = {};
        try {
            // ExtendScript 호환 JSON parse (간단 eval 래핑)
            opts = eval("(" + optionsJson + ")");
        } catch (pe) {
            return _err("옵션 파싱 실패: " + pe.toString());
        }

        var outputFolder = opts.outputFolder;
        var presetPath = opts.presetPath;
        var captureThumbnail = (opts.captureThumbnail === true);
        var thumbnailFormat = (opts.thumbnailFormat || "jpg").toLowerCase();
        var namePattern = opts.namePattern || "{sequence}_Clip_{num}";
        var videoExt = (opts.videoExt || "mp4").toLowerCase();

        if (!outputFolder) return _err("outputFolder 누락");
        if (!presetPath) return _err("presetPath 누락");

        // 출력 폴더 확인/생성
        var folder = new Folder(outputFolder);
        if (!folder.exists) {
            if (!folder.create()) {
                return _err("출력 폴더 생성 실패: " + outputFolder);
            }
        }

        // 썸네일 서브 폴더
        var thumbFolder = null;
        if (captureThumbnail) {
            thumbFolder = new Folder(outputFolder + "/thumbnails");
            if (!thumbFolder.exists) thumbFolder.create();
        }

        // 프리셋 파일 확인
        var pf = new File(presetPath);
        if (!pf.exists) {
            return _err("프리셋 파일 없음: " + presetPath);
        }

        // 활성 시퀀스
        var seq = app.project.activeSequence;
        if (!seq) return _err("활성 시퀀스 없음");

        var track = seq.videoTracks[0];
        if (!track || track.clips.numItems === 0) {
            return _err("비디오 트랙 1에 클립이 없습니다");
        }

        var total = track.clips.numItems;
        var sanitizedSeqName = _sanitize(seq.name);

        // 원래 In/Out 백업
        var origIn = null, origOut = null;
        try { origIn = seq.getInPoint(); } catch (_) {}
        try { origOut = seq.getOutPoint(); } catch (_) {}

        var results = [];
        var failCount = 0;

        for (var i = 0; i < total; i++) {
            var clip = track.clips[i];
            var num = _pad(i + 1, 3);

            // 파일명 생성
            var baseName = namePattern
                .replace(/\{sequence\}/g, sanitizedSeqName)
                .replace(/\{num\}/g, num)
                .replace(/\{name\}/g, _sanitize(clip.name || ("Clip" + num)));

            var videoPath = _joinPath(outputFolder, baseName + "." + videoExt);
            var thumbPath = null;
            if (captureThumbnail && thumbFolder) {
                thumbPath = _joinPath(outputFolder + "/thumbnails", baseName + "." + thumbnailFormat);
            }

            var startSec = clip.start.ticks / TPS;
            var endSec = clip.end.ticks / TPS;

            var clipResult = {
                index: i + 1,
                name: baseName,
                startSec: startSec,
                endSec: endSec,
                videoPath: videoPath,
                thumbPath: thumbPath,
                videoOk: false,
                thumbOk: false,
                error: null
            };

            // 1) 썸네일 먼저 (playhead 이동만 하면 되어 빠름)
            if (captureThumbnail && thumbPath) {
                try {
                    // 클립 시작 + 0.05s 지점 (검은 프레임 회피)
                    var thumbTicks = clip.start.ticks + Math.round(0.05 * TPS);
                    seq.setPlayerPosition(String(thumbTicks));
                    if (thumbnailFormat === "png") {
                        seq.exportFramePNG(thumbPath);
                    } else if (thumbnailFormat === "tiff") {
                        seq.exportFrameTIFF(thumbPath);
                    } else {
                        seq.exportFrameJPEG(thumbPath);
                    }
                    clipResult.thumbOk = true;
                } catch (te) {
                    clipResult.error = "thumb: " + te.toString();
                }
            }

            // 2) 클립 비디오 익스포트
            try {
                seq.setInPoint(startSec);
                seq.setOutPoint(endSec);
                var res = seq.exportAsMediaDirect(videoPath, presetPath, 1);
                if (res && String(res).length > 0) {
                    clipResult.error = "export: " + res;
                    failCount++;
                } else {
                    clipResult.videoOk = true;
                }
            } catch (ee) {
                clipResult.error = "export exception: " + ee.toString();
                failCount++;
            }

            results.push(clipResult);
        }

        // In/Out 복원
        try {
            if (origIn !== null) seq.setInPoint(Number(origIn) / TPS);
            if (origOut !== null) seq.setOutPoint(Number(origOut) / TPS);
        } catch (_) {}

        return _ok({
            total: total,
            succeeded: total - failCount,
            failed: failCount,
            results: results,
            outputFolder: outputFolder
        });
    } catch (e) {
        return _err("ceExportAllClips 예외: " + e.toString() + " / line " + (e.line || "?"));
    }
}

// ─────────────────────────────────────
// 폴더/파일 선택 다이얼로그 (ExtendScript)
// ─────────────────────────────────────
function ceBrowseFolder(title) {
    try {
        var f = Folder.selectDialog(title || "폴더 선택");
        if (!f) return _err("취소됨");
        return _ok({ path: f.fsName.replace(/\\/g, "/") });
    } catch (e) {
        return _err(e.toString());
    }
}

function ceBrowsePresetFile() {
    try {
        var f = File.openDialog("Premiere 프리셋 파일 선택 (.epr)", "*.epr");
        if (!f) return _err("취소됨");
        return _ok({ path: f.fsName.replace(/\\/g, "/") });
    } catch (e) {
        return _err(e.toString());
    }
}
