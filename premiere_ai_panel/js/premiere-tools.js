/**
 * premiere-tools.js - Claude 도구 호출을 ExtendScript로 디스패치
 */

(function () {
    'use strict';

    var csInterface = new CSInterface();

    // 한국어 → 영문 이펙트 매핑
    var EFFECT_MAP = {
        '블러': 'Gaussian Blur',
        '가우시안 블러': 'Gaussian Blur',
        '샤프닝': 'Sharpen',
        '모자이크': 'Mosaic',
        '흑백': 'Black & White',
        '컬러 보정': 'Lumetri Color',
        '루메트리': 'Lumetri Color',
        '크롭': 'Crop',
        '크로마키': 'Ultra Key',
        '울트라 키': 'Ultra Key',
        '밝기': 'Brightness & Contrast',
        '대비': 'Brightness & Contrast',
        '색조': 'Hue/Saturation',
        '채도': 'Hue/Saturation',
        '반전': 'Invert',
        '글로우': 'Glow',
        '노이즈': 'Noise',
        '왜곡': 'Twirl'
    };

    var TRANSITION_MAP = {
        '크로스 디졸브': 'Cross Dissolve',
        '디졸브': 'Cross Dissolve',
        '디핑 블랙': 'Dip to Black',
        '디핑 화이트': 'Dip to White',
        '페이드': 'Film Dissolve',
        '필름 디졸브': 'Film Dissolve',
        '와이프': 'Wipe',
        '슬라이드': 'Slide',
        '푸시': 'Push'
    };

    var COLOR_MAP = {
        '초록': 0, '녹색': 0, 'green': 0,
        '빨강': 1, '빨간': 1, 'red': 1,
        '보라': 2, '자주': 2, 'purple': 2,
        '주황': 3, '오렌지': 3, 'orange': 3,
        '노랑': 4, '노란': 4, 'yellow': 4,
        '하양': 5, '흰': 5, 'white': 5,
        '파랑': 6, '파란': 6, 'blue': 6,
        '청록': 7, '시안': 7, 'cyan': 7
    };

    function mapEffect(name) { return EFFECT_MAP[name] || name; }
    function mapTransition(name) { return TRANSITION_MAP[name] || name; }
    function mapColor(name) {
        if (typeof name === 'number') return name;
        return COLOR_MAP[name] !== undefined ? COLOR_MAP[name] : 1;
    }

    function escStr(s) {
        if (s === null || s === undefined) return '""';
        return '"' + String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
    }

    function n(v, def) {
        if (v === undefined || v === null) return def === undefined ? -1 : def;
        return Number(v);
    }

    /**
     * JSX 호출 헬퍼
     */
    function evalJSX(script, callback) {
        csInterface.evalScript(script, function (result) {
            try {
                // hostscript는 JSON 문자열을 반환
                var parsed = JSON.parse(result);
                callback(parsed);
            } catch (e) {
                callback({ status: 'error', message: 'JSX 응답 파싱 실패: ' + result });
            }
        });
    }

    /**
     * 도구 디스패치
     * @param {string} toolName
     * @param {object} input
     * @param {Function} callback - function(resultString)
     */
    function dispatch(toolName, input, callback) {
        var script = '';

        switch (toolName) {
            // ─── 프로젝트 ───
            case 'project_info':
                script = 'projectInfo()'; break;
            case 'save_project':
                script = 'saveProject()'; break;
            case 'import_media':
                script = 'importMedia(' + escStr(input.file_paths) + ')'; break;
            case 'create_sequence':
                script = 'createSequence(' + escStr(input.name) + ')'; break;
            case 'list_sequences':
                script = 'listSequences()'; break;
            case 'set_active_sequence':
                script = 'setActiveSequence(' + escStr(input.name) + ')'; break;
            case 'list_items':
                script = 'listProjectItems(' + escStr(input.bin_path || '') + ')'; break;

            // ─── 시퀀스 / 클립 ───
            case 'sequence_info':
                script = 'sequenceInfo()'; break;
            case 'list_clips':
                script = 'listClips(' + escStr(input.track_type) + ',' + n(input.track_index, 0) + ')'; break;
            case 'remove_clip':
                script = 'removeClip(' + escStr(input.track_type) + ',' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ')'; break;
            case 'ripple_delete':
                script = 'rippleDelete(' + escStr(input.track_type) + ',' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ')'; break;
            case 'move_clip':
                script = 'moveClip(' + escStr(input.track_type) + ',' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.new_start, 0) + ')'; break;
            case 'trim_clip':
                script = 'trimClip(' + escStr(input.track_type) + ',' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.new_in, -1) + ',' + n(input.new_out, -1) + ')'; break;
            case 'razor_cut':
                script = 'razorCut(' + n(input.time, 0) + ',' + escStr(input.tracks || '') + ')'; break;
            case 'set_speed':
                script = 'setClipSpeed(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.speed, 1) + ')'; break;
            case 'duplicate_clip':
                script = 'duplicateClip(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ')'; break;
            case 'lift_range':
                script = 'liftRange(' + n(input.start, 0) + ',' + n(input.end, 0) + ')'; break;
            case 'extract_range':
                script = 'extractRange(' + n(input.start, 0) + ',' + n(input.end, 0) + ')'; break;
            case 'set_work_area':
                script = 'setWorkArea(' + n(input['in'], 0) + ',' + n(input['out'], 0) + ')'; break;

            // ─── 재생 ───
            case 'play': script = 'play()'; break;
            case 'pause': script = 'pause()'; break;
            case 'go_to': script = 'goToTime(' + n(input.time, 0) + ')'; break;
            case 'current_time': script = 'getCurrentTime()'; break;

            // ─── 이펙트 ───
            case 'apply_effect':
                script = 'applyEffect(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + escStr(mapEffect(input.effect)) + ')';
                break;
            case 'remove_effect':
                script = 'removeEffect(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.effect_index, 0) + ')';
                break;
            case 'list_effects':
                script = 'listEffects(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ')'; break;
            case 'set_parameter':
                script = 'setParameter(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.component, 0) + ',' + escStr(input.param) + ',' + n(input.value, 0) + ')';
                break;
            case 'set_opacity':
                script = 'setOpacity(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.value, 100) + ')'; break;
            case 'set_scale':
                script = 'setScale(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.value, 100) + ')'; break;
            case 'set_position':
                script = 'setPosition(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.x, 960) + ',' + n(input.y, 540) + ')'; break;
            case 'set_rotation':
                script = 'setRotation(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.degrees, 0) + ')'; break;
            case 'apply_transition':
                script = 'applyTransition(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + escStr(mapTransition(input.transition)) + ',' + escStr(input.position || 'end') + ',' + n(input.duration, 1) + ')';
                break;
            case 'add_keyframe':
                script = 'addKeyframe(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.component, 0) + ',' + escStr(input.param) + ',' + n(input.time, 0) + ',' + n(input.value, 0) + ')';
                break;
            case 'fade_in':
                script = 'fadeIn(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.duration, 1) + ')'; break;
            case 'fade_out':
                script = 'fadeOut(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ',' + n(input.duration, 1) + ')'; break;
            case 'reset_effects':
                script = 'resetEffects(' + n(input.track_index, 0) + ',' + n(input.clip_index, 0) + ')'; break;

            // ─── 마커 ───
            case 'list_markers':
                script = 'listMarkers()'; break;
            case 'add_marker':
                script = 'addMarker(' + n(input.time, 0) + ',' + escStr(input.name || '') + ',' + escStr(input.comment || '') + ',' + mapColor(input.color) + ')'; break;
            case 'remove_marker':
                script = 'removeMarker(' + n(input.time, 0) + ')'; break;
            case 'clear_markers':
                script = 'clearMarkers()'; break;

            // ─── 내보내기 ───
            case 'export':
                script = 'exportSequence(' + escStr(input.output) + ',' + escStr(input.preset) + ',' + (input.work_area_only ? 'true' : 'false') + ')';
                break;
            case 'export_encoder':
                script = 'exportToEncoder(' + escStr(input.output) + ',' + escStr(input.preset) + ')'; break;
            case 'export_frame':
                script = 'exportFrame(' + escStr(input.output) + ',' + n(input.time, -1) + ')'; break;

            default:
                callback('알 수 없는 도구: ' + toolName);
                return;
        }

        evalJSX(script, function (result) {
            if (result.status === 'ok') {
                callback(typeof result.data === 'string' ? result.data : JSON.stringify(result.data, null, 2));
            } else {
                callback('오류: ' + result.message);
            }
        });
    }

    window.PremiereTools = {
        dispatch: dispatch,
        evalJSX: evalJSX
    };

})();
