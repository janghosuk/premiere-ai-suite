/**
 * add_edit.jsx - Premiere Pro 타임라인 razor cut 및 편집 보조 스크립트
 * pymiere에서 직접 지원하지 않는 QE 기반 편집 기능을 제공합니다.
 */

// 특정 시간에 모든 비디오 트랙에 razor cut
function razorCutAll(timeInSeconds) {
    var seq = qe.project.getActiveSequence();
    if (!seq) {
        return "error: no active sequence";
    }

    var time = new Time();
    time.seconds = timeInSeconds;

    var count = seq.numVideoTracks;
    for (var i = 0; i < count; i++) {
        var track = seq.getVideoTrackAt(i);
        track.razor(time);
    }

    // 오디오 트랙도 같이 자르기
    var audioCount = seq.numAudioTracks;
    for (var j = 0; j < audioCount; j++) {
        var audioTrack = seq.getAudioTrackAt(j);
        audioTrack.razor(time);
    }

    return "success: razor cut at " + timeInSeconds + "s on all tracks";
}

// 특정 비디오 트랙만 razor cut
function razorCutTrack(timeInSeconds, trackIndex) {
    var seq = qe.project.getActiveSequence();
    if (!seq) {
        return "error: no active sequence";
    }

    var time = new Time();
    time.seconds = timeInSeconds;

    var track = seq.getVideoTrackAt(trackIndex);
    track.razor(time);

    return "success: razor cut at " + timeInSeconds + "s on track " + trackIndex;
}

// 시간 범위를 삭제 (lift)
function liftRange(startSeconds, endSeconds) {
    var seq = app.project.activeSequence;
    if (!seq) {
        return "error: no active sequence";
    }

    seq.setInPoint(startSeconds);
    seq.setOutPoint(endSeconds);

    var qeSeq = qe.project.getActiveSequence();
    qeSeq.lift();

    return "success: lifted range " + startSeconds + "s - " + endSeconds + "s";
}

// 시간 범위를 추출 (extract / ripple delete)
function extractRange(startSeconds, endSeconds) {
    var seq = app.project.activeSequence;
    if (!seq) {
        return "error: no active sequence";
    }

    seq.setInPoint(startSeconds);
    seq.setOutPoint(endSeconds);

    var qeSeq = qe.project.getActiveSequence();
    qeSeq.extract();

    return "success: extracted range " + startSeconds + "s - " + endSeconds + "s";
}

// 클립 복제 (같은 트랙에 바로 뒤에 배치)
function duplicateClip(trackIndex, clipIndex) {
    var seq = app.project.activeSequence;
    var track = seq.videoTracks[trackIndex];
    var clip = track.clips[clipIndex];

    var projectItem = clip.projectItem;
    var insertTime = clip.end.seconds;

    seq.insertClip(projectItem, insertTime, trackIndex, 0);

    return "success: duplicated clip at " + insertTime + "s";
}
