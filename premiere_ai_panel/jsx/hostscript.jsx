/**
 * hostscript.jsx - Premiere AI Agent ExtendScript 함수 모음
 * CSInterface.evalScript()를 통해 호출됩니다.
 */

// QE DOM 활성화
app.enableQE();

// Array.indexOf polyfill
if (!Array.prototype.indexOf) {
    Array.prototype.indexOf = function (item) {
        var i = this.length;
        while (i--) { if (this[i] === item) return i; }
        return -1;
    };
}

// ─────────────────────────────────────────────
//  유틸리티
// ─────────────────────────────────────────────

function _jsonStr(obj) {
    // 간단한 JSON stringify (ExtendScript에는 JSON 없음)
    if (obj === null || obj === undefined) return "null";
    if (typeof obj === "boolean" || typeof obj === "number") return String(obj);
    if (typeof obj === "string") {
        return '"' + obj.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
                        .replace(/\n/g, '\\n').replace(/\r/g, '\\r')
                        .replace(/\t/g, '\\t') + '"';
    }
    if (obj instanceof Array) {
        var arrParts = [];
        for (var ai = 0; ai < obj.length; ai++) {
            arrParts.push(_jsonStr(obj[ai]));
        }
        return "[" + arrParts.join(",") + "]";
    }
    if (typeof obj === "object") {
        var parts = [];
        for (var k in obj) {
            if (obj.hasOwnProperty(k)) {
                parts.push(_jsonStr(k) + ":" + _jsonStr(obj[k]));
            }
        }
        return "{" + parts.join(",") + "}";
    }
    return "null";
}

function _ok(data) {
    return _jsonStr({ status: "ok", data: data });
}

function _err(msg) {
    return _jsonStr({ status: "error", message: String(msg) });
}

function _getSeq() {
    var seq = app.project.activeSequence;
    if (!seq) throw "활성 시퀀스가 없습니다";
    return seq;
}

// ─────────────────────────────────────────────
//  프로젝트 관리
// ─────────────────────────────────────────────

function projectInfo() {
    try {
        var proj = app.project;
        var seq = proj.activeSequence;
        var info = {
            name: proj.name,
            path: proj.path,
            activeSequence: seq ? seq.name : null,
            numSequences: proj.sequences.numItems,
            numItems: proj.rootItem.children.numItems
        };
        return _ok(info);
    } catch (e) { return _err(e); }
}

function saveProject() {
    try {
        app.project.save();
        return _ok("프로젝트 저장 완료");
    } catch (e) { return _err(e); }
}

function importMedia(filePaths) {
    try {
        var paths = filePaths.split("|");
        var arr = [];
        for (var i = 0; i < paths.length; i++) arr.push(paths[i]);
        app.project.importFiles(arr);
        return _ok("임포트 완료: " + paths.length + "개 파일");
    } catch (e) { return _err(e); }
}

function createSequence(name) {
    try {
        app.project.createNewSequence(name);
        return _ok("시퀀스 생성: " + name);
    } catch (e) { return _err(e); }
}

function listSequences() {
    try {
        var proj = app.project;
        var seqs = [];
        for (var i = 0; i < proj.sequences.numItems; i++) {
            var s = proj.sequences[i];
            seqs.push({
                name: s.name,
                duration: s.end.seconds,
                videoTrackCount: s.videoTracks.numTracks,
                audioTrackCount: s.audioTracks.numTracks
            });
        }
        return _ok(seqs);
    } catch (e) { return _err(e); }
}

function setActiveSequence(name) {
    try {
        var proj = app.project;
        for (var i = 0; i < proj.sequences.numItems; i++) {
            if (proj.sequences[i].name === name) {
                proj.activeSequence = proj.sequences[i];
                return _ok("활성 시퀀스 변경: " + name);
            }
        }
        return _err("시퀀스를 찾을 수 없음: " + name);
    } catch (e) { return _err(e); }
}

function listProjectItems(binPath) {
    try {
        var root = app.project.rootItem;
        var parent = root;
        if (binPath && binPath !== "" && binPath !== "/") {
            var parts = binPath.split("/");
            for (var p = 0; p < parts.length; p++) {
                if (parts[p] === "") continue;
                var found = false;
                for (var c = 0; c < parent.children.numItems; c++) {
                    if (parent.children[c].name === parts[p] && parent.children[c].type === 2) {
                        parent = parent.children[c];
                        found = true;
                        break;
                    }
                }
                if (!found) return _err("빈을 찾을 수 없음: " + parts[p]);
            }
        }
        var items = [];
        for (var i = 0; i < parent.children.numItems; i++) {
            var item = parent.children[i];
            items.push({
                name: item.name,
                type: item.type === 2 ? "bin" : (item.type === 1 ? "clip" : "other"),
                path: item.treePath
            });
        }
        return _ok(items);
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  타임라인 / 시퀀스 정보
// ─────────────────────────────────────────────

function sequenceInfo() {
    try {
        var seq = _getSeq();
        var info = {
            name: seq.name,
            duration: seq.end.seconds,
            videoTrackCount: seq.videoTracks.numTracks,
            audioTrackCount: seq.audioTracks.numTracks,
            frameRate: seq.getSettings().videoFrameRate ? seq.getSettings().videoFrameRate.seconds : null,
            width: seq.frameSizeHorizontal,
            height: seq.frameSizeVertical
        };
        return _ok(info);
    } catch (e) { return _err(e); }
}

function listClips(trackType, trackIndex) {
    try {
        var seq = _getSeq();
        var tracks = (trackType === "audio") ? seq.audioTracks : seq.videoTracks;
        if (trackIndex >= tracks.numTracks) return _err("트랙 인덱스 범위 초과");
        var track = tracks[trackIndex];
        var clips = [];
        for (var i = 0; i < track.clips.numItems; i++) {
            var c = track.clips[i];
            clips.push({
                index: i,
                name: c.name,
                start: c.start.seconds,
                end: c.end.seconds,
                duration: c.duration.seconds,
                inPoint: c.inPoint ? c.inPoint.seconds : 0,
                outPoint: c.outPoint ? c.outPoint.seconds : 0,
                mediaType: c.mediaType
            });
        }
        return _ok({ trackName: track.name, clips: clips });
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  타임라인 편집
// ─────────────────────────────────────────────

function removeClip(trackType, trackIndex, clipIndex) {
    try {
        var seq = _getSeq();
        var tracks = (trackType === "audio") ? seq.audioTracks : seq.videoTracks;
        var clip = tracks[trackIndex].clips[clipIndex];
        if (!clip) return _err("클립을 찾을 수 없음");
        clip.remove(false, false);
        return _ok("클립 삭제 완료");
    } catch (e) { return _err(e); }
}

function rippleDelete(trackType, trackIndex, clipIndex) {
    try {
        var seq = _getSeq();
        var tracks = (trackType === "audio") ? seq.audioTracks : seq.videoTracks;
        var clip = tracks[trackIndex].clips[clipIndex];
        if (!clip) return _err("클립을 찾을 수 없음");
        clip.remove(true, true);
        return _ok("리플 삭제 완료");
    } catch (e) { return _err(e); }
}

function moveClip(trackType, trackIndex, clipIndex, newStartSeconds) {
    try {
        var seq = _getSeq();
        var tracks = (trackType === "audio") ? seq.audioTracks : seq.videoTracks;
        var clip = tracks[trackIndex].clips[clipIndex];
        var newTime = new Time();
        newTime.seconds = newStartSeconds;
        clip.start = newTime;
        return _ok("클립 이동 완료: " + newStartSeconds + "초");
    } catch (e) { return _err(e); }
}

function trimClip(trackType, trackIndex, clipIndex, newIn, newOut) {
    try {
        var seq = _getSeq();
        var tracks = (trackType === "audio") ? seq.audioTracks : seq.videoTracks;
        var clip = tracks[trackIndex].clips[clipIndex];
        if (newIn !== null && newIn !== undefined && newIn >= 0) {
            var inTime = new Time();
            inTime.seconds = newIn;
            clip.inPoint = inTime;
        }
        if (newOut !== null && newOut !== undefined && newOut > 0) {
            var outTime = new Time();
            outTime.seconds = newOut;
            clip.outPoint = outTime;
        }
        return _ok("클립 트리밍 완료");
    } catch (e) { return _err(e); }
}

function razorCut(timeSeconds, trackIndicesStr) {
    try {
        var seq = qe.project.getActiveSequence();
        if (!seq) return _err("활성 시퀀스 없음");
        var time = new Time();
        time.seconds = timeSeconds;
        if (trackIndicesStr && trackIndicesStr !== "") {
            var indices = trackIndicesStr.split(",");
            for (var i = 0; i < indices.length; i++) {
                var idx = parseInt(indices[i], 10);
                seq.getVideoTrackAt(idx).razor(time);
            }
        } else {
            // 모든 트랙
            for (var v = 0; v < seq.numVideoTracks; v++) {
                seq.getVideoTrackAt(v).razor(time);
            }
            for (var a = 0; a < seq.numAudioTracks; a++) {
                seq.getAudioTrackAt(a).razor(time);
            }
        }
        return _ok("Razor cut 완료: " + timeSeconds + "초");
    } catch (e) { return _err(e); }
}

function setClipSpeed(trackIndex, clipIndex, speed) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        clip.setSpeed(speed, 0, true, false);
        return _ok("속도 변경: " + speed + "x");
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  재생 제어
// ─────────────────────────────────────────────

function play() {
    try {
        _getSeq().player.play(1.0);
        return _ok("재생");
    } catch (e) { return _err(e); }
}

function pause() {
    try {
        _getSeq().player.play(0);
        return _ok("정지");
    } catch (e) { return _err(e); }
}

function goToTime(seconds) {
    try {
        var seq = _getSeq();
        var t = new Time();
        t.seconds = seconds;
        seq.setPlayerPosition(t.ticks);
        return _ok("이동: " + seconds + "초");
    } catch (e) { return _err(e); }
}

function getCurrentTime() {
    try {
        var seq = _getSeq();
        var pos = seq.getPlayerPosition();
        var t = new Time();
        t.ticks = pos;
        return _ok({ seconds: t.seconds });
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  이펙트 & 트랜지션
// ─────────────────────────────────────────────

function applyEffect(trackIndex, clipIndex, effectName) {
    try {
        var qeSeq = qe.project.getActiveSequence();
        var qeTrack = qeSeq.getVideoTrackAt(trackIndex);
        var qeClip = qeTrack.getItemAt(clipIndex);
        var effect = qe.project.getVideoEffectByName(effectName);
        if (!effect) return _err("이펙트를 찾을 수 없음: " + effectName);
        qeClip.addVideoEffect(effect);
        return _ok("이펙트 적용: " + effectName);
    } catch (e) { return _err(e); }
}

function removeEffect(trackIndex, clipIndex, effectIndex) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var userIdx = effectIndex + 2; // Motion(0) + Opacity(1)
        if (userIdx < clip.components.numItems) {
            clip.components[userIdx].remove();
            return _ok("이펙트 삭제 완료");
        }
        return _err("이펙트를 찾을 수 없음");
    } catch (e) { return _err(e); }
}

function listEffects(trackIndex, clipIndex) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var effects = [];
        for (var i = 0; i < clip.components.numItems; i++) {
            var comp = clip.components[i];
            var params = [];
            for (var j = 0; j < comp.properties.numItems; j++) {
                var p = comp.properties[j];
                params.push({
                    name: p.displayName,
                    value: (typeof p.getValue === "function") ? String(p.getValue()) : "N/A"
                });
            }
            effects.push({
                index: i,
                name: comp.displayName,
                params: params
            });
        }
        return _ok(effects);
    } catch (e) { return _err(e); }
}

function setParameter(trackIndex, clipIndex, componentIndex, paramName, value) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var comp = clip.components[componentIndex];
        for (var i = 0; i < comp.properties.numItems; i++) {
            var p = comp.properties[i];
            if (p.displayName === paramName) {
                p.setValue(value, true);
                return _ok(paramName + " = " + value);
            }
        }
        return _err("파라미터를 찾을 수 없음: " + paramName);
    } catch (e) { return _err(e); }
}

function setOpacity(trackIndex, clipIndex, value) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var opacity = clip.components[1];
        for (var i = 0; i < opacity.properties.numItems; i++) {
            if (opacity.properties[i].displayName === "Opacity") {
                opacity.properties[i].setValue(value, true);
                return _ok("불투명도: " + value + "%");
            }
        }
        return _err("Opacity 속성을 찾을 수 없음");
    } catch (e) { return _err(e); }
}

function setScale(trackIndex, clipIndex, value) {
    return setParameter(trackIndex, clipIndex, 0, "Scale", value);
}

function setPosition(trackIndex, clipIndex, x, y) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var motion = clip.components[0];
        for (var i = 0; i < motion.properties.numItems; i++) {
            if (motion.properties[i].displayName === "Position") {
                motion.properties[i].setValue([x, y], true);
                return _ok("위치: " + x + ", " + y);
            }
        }
        return _err("Position 속성을 찾을 수 없음");
    } catch (e) { return _err(e); }
}

function setRotation(trackIndex, clipIndex, degrees) {
    return setParameter(trackIndex, clipIndex, 0, "Rotation", degrees);
}

function applyTransition(trackIndex, clipIndex, transitionName, position, durationSeconds) {
    try {
        var qeSeq = qe.project.getActiveSequence();
        var qeTrack = qeSeq.getVideoTrackAt(trackIndex);
        var qeClip = qeTrack.getItemAt(clipIndex);
        var transition = qe.project.getVideoTransitionByName(transitionName);
        if (!transition) return _err("트랜지션을 찾을 수 없음: " + transitionName);

        var ticks = String(Math.round(durationSeconds * 254016000000));
        if (position === "start" || position === "both") {
            qeClip.addTransition(transition, true, ticks);
        }
        if (position === "end" || position === "both") {
            qeClip.addTransition(transition, false, ticks);
        }
        return _ok("트랜지션 적용: " + transitionName);
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  키프레임 & 고급 이펙트
// ─────────────────────────────────────────────

function addKeyframe(trackIndex, clipIndex, componentIndex, paramName, timeSec, value) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var comp = clip.components[componentIndex];
        for (var i = 0; i < comp.properties.numItems; i++) {
            var p = comp.properties[i];
            if (p.displayName === paramName) {
                p.setTimeVarying(true);
                p.addKey(timeSec);
                p.setValueAtKey(timeSec, value);
                return _ok("키프레임 추가: " + paramName + " @" + timeSec + "s = " + value);
            }
        }
        return _err("파라미터를 찾을 수 없음: " + paramName);
    } catch (e) { return _err(e); }
}

function fadeIn(trackIndex, clipIndex, durationSeconds) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var opacity = clip.components[1];
        for (var i = 0; i < opacity.properties.numItems; i++) {
            if (opacity.properties[i].displayName === "Opacity") {
                var p = opacity.properties[i];
                p.setTimeVarying(true);
                p.addKey(0);
                p.setValueAtKey(0, 0);
                p.addKey(durationSeconds);
                p.setValueAtKey(durationSeconds, 100);
                return _ok("페이드 인: " + durationSeconds + "초");
            }
        }
        return _err("Opacity 속성을 찾을 수 없음");
    } catch (e) { return _err(e); }
}

function fadeOut(trackIndex, clipIndex, durationSeconds) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var dur = clip.duration.seconds;
        var opacity = clip.components[1];
        for (var i = 0; i < opacity.properties.numItems; i++) {
            if (opacity.properties[i].displayName === "Opacity") {
                var p = opacity.properties[i];
                p.setTimeVarying(true);
                p.addKey(dur - durationSeconds);
                p.setValueAtKey(dur - durationSeconds, 100);
                p.addKey(dur);
                p.setValueAtKey(dur, 0);
                return _ok("페이드 아웃: " + durationSeconds + "초");
            }
        }
        return _err("Opacity 속성을 찾을 수 없음");
    } catch (e) { return _err(e); }
}

function resetEffects(trackIndex, clipIndex) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var motion = clip.components[0];
        for (var i = 0; i < motion.properties.numItems; i++) {
            var mp = motion.properties[i];
            if (mp.isTimeVarying()) mp.setTimeVarying(false);
            if (mp.displayName === "Position") mp.setValue([960, 540]);
            else if (mp.displayName === "Scale") mp.setValue(100);
            else if (mp.displayName === "Rotation") mp.setValue(0);
        }
        var opacity = clip.components[1];
        for (var j = 0; j < opacity.properties.numItems; j++) {
            var op = opacity.properties[j];
            if (op.isTimeVarying()) op.setTimeVarying(false);
            if (op.displayName === "Opacity") op.setValue(100);
        }
        while (clip.components.numItems > 2) {
            clip.components[2].remove();
        }
        return _ok("이펙트 초기화 완료");
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  마커
// ─────────────────────────────────────────────

function listMarkers() {
    try {
        var seq = _getSeq();
        var markers = seq.markers;
        var list = [];
        var m = markers.getFirstMarker();
        while (m) {
            list.push({
                name: m.name,
                comment: m.comments,
                start: m.start.seconds,
                end: m.end.seconds,
                color: m.getColorByIndex ? String(m.getColorByIndex()) : "unknown"
            });
            m = markers.getNextMarker(m);
        }
        return _ok(list);
    } catch (e) { return _err(e); }
}

function addMarker(timeSec, name, comment, colorIndex) {
    try {
        var seq = _getSeq();
        var markers = seq.markers;
        var t = new Time();
        t.seconds = timeSec;
        var m = markers.createMarker(t);
        if (name) m.name = name;
        if (comment) m.comments = comment;
        if (colorIndex >= 0) m.setColorByIndex(colorIndex);
        return _ok("마커 추가: " + timeSec + "초");
    } catch (e) { return _err(e); }
}

function removeMarker(timeSec) {
    try {
        var seq = _getSeq();
        var markers = seq.markers;
        var m = markers.getFirstMarker();
        while (m) {
            if (Math.abs(m.start.seconds - timeSec) < 0.01) {
                markers.deleteMarker(m);
                return _ok("마커 삭제: " + timeSec + "초");
            }
            m = markers.getNextMarker(m);
        }
        return _err("마커를 찾을 수 없음: " + timeSec + "초");
    } catch (e) { return _err(e); }
}

function clearMarkers() {
    try {
        var seq = _getSeq();
        var markers = seq.markers;
        var m = markers.getFirstMarker();
        var count = 0;
        while (m) {
            var next = markers.getNextMarker(m);
            markers.deleteMarker(m);
            count++;
            m = next;
        }
        return _ok("마커 " + count + "개 삭제");
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  내보내기
// ─────────────────────────────────────────────

function exportSequence(outputPath, presetPath, workAreaOnly) {
    try {
        var seq = _getSeq();
        var useWorkArea = (workAreaOnly === true || workAreaOnly === "true") ? 1 : 0;
        seq.exportAsMediaDirect(outputPath, presetPath, useWorkArea);
        return _ok("내보내기 완료: " + outputPath);
    } catch (e) { return _err(e); }
}

function exportToEncoder(outputPath, presetPath) {
    try {
        var seq = _getSeq();
        var jobId = app.encoder.encodeSequence(seq, outputPath, presetPath, 0, 1);
        app.encoder.startBatch();
        return _ok("Media Encoder로 전송: " + outputPath);
    } catch (e) { return _err(e); }
}

function exportFrame(outputPath, timeSec) {
    try {
        var seq = _getSeq();
        if (timeSec !== null && timeSec !== undefined && timeSec >= 0) {
            var t = new Time();
            t.seconds = timeSec;
            seq.setPlayerPosition(t.ticks);
        }
        seq.exportFramePNG(outputPath, seq.getPlayerPosition());
        return _ok("프레임 저장: " + outputPath);
    } catch (e) { return _err(e); }
}

// ─────────────────────────────────────────────
//  추가 편집 기능
// ─────────────────────────────────────────────

function liftRange(startSec, endSec) {
    try {
        var seq = _getSeq();
        seq.setInPoint(startSec);
        seq.setOutPoint(endSec);
        var qeSeq = qe.project.getActiveSequence();
        qeSeq.lift();
        return _ok("Lift 완료: " + startSec + "s - " + endSec + "s");
    } catch (e) { return _err(e); }
}

function extractRange(startSec, endSec) {
    try {
        var seq = _getSeq();
        seq.setInPoint(startSec);
        seq.setOutPoint(endSec);
        var qeSeq = qe.project.getActiveSequence();
        qeSeq.extract();
        return _ok("Extract 완료: " + startSec + "s - " + endSec + "s");
    } catch (e) { return _err(e); }
}

function duplicateClip(trackIndex, clipIndex) {
    try {
        var seq = _getSeq();
        var clip = seq.videoTracks[trackIndex].clips[clipIndex];
        var insertTime = clip.end.seconds;
        seq.insertClip(clip.projectItem, insertTime, trackIndex, 0);
        return _ok("클립 복제 완료");
    } catch (e) { return _err(e); }
}

function setWorkArea(inSec, outSec) {
    try {
        var seq = _getSeq();
        seq.setInPoint(inSec);
        seq.setOutPoint(outSec);
        return _ok("작업 영역 설정: " + inSec + "s - " + outSec + "s");
    } catch (e) { return _err(e); }
}
