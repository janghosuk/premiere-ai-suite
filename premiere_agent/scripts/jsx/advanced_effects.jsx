/**
 * advanced_effects.jsx - 고급 이펙트 및 트랜지션 보조 스크립트
 */

// 페이드 인 효과 (불투명도 키프레임)
function fadeIn(trackIndex, clipIndex, durationSeconds) {
    var seq = app.project.activeSequence;
    var clip = seq.videoTracks[trackIndex].clips[clipIndex];
    var opacity = clip.components[1]; // Opacity component

    for (var i = 0; i < opacity.properties.numItems; i++) {
        var prop = opacity.properties[i];
        if (prop.displayName === "Opacity") {
            prop.setTimeVarying(true);
            // 시작: 0%
            prop.addKey(0);
            prop.setValueAtKey(0, 0);
            // durationSeconds 후: 100%
            prop.addKey(durationSeconds);
            prop.setValueAtKey(durationSeconds, 100);
            break;
        }
    }
    return "success: fade in applied";
}

// 페이드 아웃 효과
function fadeOut(trackIndex, clipIndex, durationSeconds) {
    var seq = app.project.activeSequence;
    var clip = seq.videoTracks[trackIndex].clips[clipIndex];
    var clipDuration = clip.duration.seconds;
    var opacity = clip.components[1];

    for (var i = 0; i < opacity.properties.numItems; i++) {
        var prop = opacity.properties[i];
        if (prop.displayName === "Opacity") {
            prop.setTimeVarying(true);
            // 페이드 시작점: 100%
            prop.addKey(clipDuration - durationSeconds);
            prop.setValueAtKey(clipDuration - durationSeconds, 100);
            // 끝: 0%
            prop.addKey(clipDuration);
            prop.setValueAtKey(clipDuration, 0);
            break;
        }
    }
    return "success: fade out applied";
}

// 스케일 애니메이션 (줌 인/아웃)
function scaleAnimation(trackIndex, clipIndex, startScale, endScale, startTime, endTime) {
    var seq = app.project.activeSequence;
    var clip = seq.videoTracks[trackIndex].clips[clipIndex];
    var motion = clip.components[0]; // Motion component

    for (var i = 0; i < motion.properties.numItems; i++) {
        var prop = motion.properties[i];
        if (prop.displayName === "Scale") {
            prop.setTimeVarying(true);
            prop.addKey(startTime);
            prop.setValueAtKey(startTime, startScale);
            prop.addKey(endTime);
            prop.setValueAtKey(endTime, endScale);
            break;
        }
    }
    return "success: scale animation " + startScale + " -> " + endScale;
}

// 포지션 애니메이션 (슬라이드)
function slideAnimation(trackIndex, clipIndex, startX, startY, endX, endY, startTime, endTime) {
    var seq = app.project.activeSequence;
    var clip = seq.videoTracks[trackIndex].clips[clipIndex];
    var motion = clip.components[0];

    for (var i = 0; i < motion.properties.numItems; i++) {
        var prop = motion.properties[i];
        if (prop.displayName === "Position") {
            prop.setTimeVarying(true);
            prop.addKey(startTime);
            prop.setValueAtKey(startTime, [startX, startY]);
            prop.addKey(endTime);
            prop.setValueAtKey(endTime, [endX, endY]);
            break;
        }
    }
    return "success: slide animation applied";
}

// 모든 이펙트 초기화 (Motion, Opacity 기본값으로)
function resetEffects(trackIndex, clipIndex) {
    var seq = app.project.activeSequence;
    var clip = seq.videoTracks[trackIndex].clips[clipIndex];

    // Motion 리셋
    var motion = clip.components[0];
    for (var i = 0; i < motion.properties.numItems; i++) {
        var prop = motion.properties[i];
        if (prop.isTimeVarying()) {
            prop.setTimeVarying(false);
        }
        if (prop.displayName === "Position") {
            prop.setValue([960, 540]); // 1080p 중앙
        } else if (prop.displayName === "Scale") {
            prop.setValue(100);
        } else if (prop.displayName === "Rotation") {
            prop.setValue(0);
        }
    }

    // Opacity 리셋
    var opacity = clip.components[1];
    for (var j = 0; j < opacity.properties.numItems; j++) {
        var opProp = opacity.properties[j];
        if (opProp.isTimeVarying()) {
            opProp.setTimeVarying(false);
        }
        if (opProp.displayName === "Opacity") {
            opProp.setValue(100);
        }
    }

    // 추가 이펙트 제거
    while (clip.components.numItems > 2) {
        clip.components[2].remove();
    }

    return "success: all effects reset";
}
