"""타임라인 편집 모듈 - 클립 추가/삭제/이동/트리밍"""

import os
from .connection import PremiereConnection


class TimelineEditor:
    """타임라인(시퀀스) 편집 기능을 제공합니다."""

    def __init__(self, conn: PremiereConnection):
        self.conn = conn

    @property
    def active_sequence(self):
        """현재 활성 시퀀스를 반환합니다."""
        seq = self.conn.app.project.activeSequence
        if not seq:
            raise RuntimeError("활성 시퀀스가 없습니다.")
        return seq

    # ─── 시퀀스 정보 ──────────────────────────────────

    def get_sequence_info(self) -> dict:
        """현재 시퀀스 정보를 반환합니다."""
        seq = self.active_sequence
        return {
            "name": seq.name,
            "id": seq.sequenceID,
            "duration": seq.end,
            "frame_rate": str(seq.timebase),
            "video_tracks": seq.videoTracks.numTracks,
            "audio_tracks": seq.audioTracks.numTracks,
        }

    def list_clips(self, track_type: str = "video", track_index: int = 0) -> list[dict]:
        """트랙의 클립 목록을 반환합니다.

        Args:
            track_type: "video" 또는 "audio"
            track_index: 트랙 번호 (0부터 시작)
        """
        seq = self.active_sequence
        if track_type == "video":
            track = seq.videoTracks[track_index]
        else:
            track = seq.audioTracks[track_index]

        clips = []
        for i in range(track.clips.numItems):
            clip = track.clips[i]
            clips.append({
                "index": i,
                "name": clip.name,
                "start": clip.start.seconds,
                "end": clip.end.seconds,
                "duration": clip.duration.seconds,
                "in_point": clip.inPoint.seconds if hasattr(clip, "inPoint") else None,
                "out_point": clip.outPoint.seconds if hasattr(clip, "outPoint") else None,
            })
        return clips

    # ─── 클립 추가 ──────────────────────────────────

    def add_clip_to_timeline(
        self,
        project_item_name: str,
        time_seconds: float = 0.0,
        video_track: int = 0,
        audio_track: int = 0,
    ) -> bool:
        """프로젝트 아이템을 타임라인에 추가합니다.

        Args:
            project_item_name: 프로젝트 패널의 아이템 이름
            time_seconds: 삽입 위치 (초)
            video_track: 비디오 트랙 번호
            audio_track: 오디오 트랙 번호
        """
        project = self.conn.app.project
        item = self._find_project_item(project.rootItem, project_item_name)
        if not item:
            raise ValueError(f"프로젝트 아이템을 찾을 수 없습니다: {project_item_name}")

        seq = self.active_sequence
        seq.insertClip(item, time_seconds, video_track, audio_track)
        return True

    def overwrite_clip(
        self,
        project_item_name: str,
        time_seconds: float,
        video_track: int = 0,
        audio_track: int = 0,
    ) -> bool:
        """프로젝트 아이템을 타임라인에 덮어쓰기(overwrite)로 추가합니다."""
        project = self.conn.app.project
        item = self._find_project_item(project.rootItem, project_item_name)
        if not item:
            raise ValueError(f"프로젝트 아이템을 찾을 수 없습니다: {project_item_name}")

        seq = self.active_sequence
        seq.overwriteClip(item, time_seconds)
        return True

    # ─── 클립 삭제 ──────────────────────────────────

    def remove_clip(self, track_type: str, track_index: int, clip_index: int) -> bool:
        """클립을 삭제합니다.

        Args:
            track_type: "video" 또는 "audio"
            track_index: 트랙 번호
            clip_index: 클립 인덱스
        """
        seq = self.active_sequence
        if track_type == "video":
            track = seq.videoTracks[track_index]
        else:
            track = seq.audioTracks[track_index]

        clip = track.clips[clip_index]
        clip.remove(inRipple=False, inAlignToVideo=False)
        return True

    def ripple_delete(self, track_type: str, track_index: int, clip_index: int) -> bool:
        """클립을 리플 삭제합니다 (빈 공간 없이 제거)."""
        seq = self.active_sequence
        if track_type == "video":
            track = seq.videoTracks[track_index]
        else:
            track = seq.audioTracks[track_index]

        clip = track.clips[clip_index]
        clip.remove(inRipple=True, inAlignToVideo=True)
        return True

    # ─── 클립 이동 & 트리밍 ────────────────────────

    def move_clip(
        self,
        track_type: str,
        track_index: int,
        clip_index: int,
        new_start_seconds: float,
    ) -> bool:
        """클립의 시작 위치를 변경합니다."""
        seq = self.active_sequence
        if track_type == "video":
            track = seq.videoTracks[track_index]
        else:
            track = seq.audioTracks[track_index]

        clip = track.clips[clip_index]
        clip.start = new_start_seconds
        return True

    def trim_clip(
        self,
        track_type: str,
        track_index: int,
        clip_index: int,
        new_in: float = None,
        new_out: float = None,
    ) -> bool:
        """클립의 인/아웃 포인트를 변경하여 트리밍합니다.

        Args:
            new_in: 새 인포인트 (초, 소스 기준)
            new_out: 새 아웃포인트 (초, 소스 기준)
        """
        seq = self.active_sequence
        if track_type == "video":
            track = seq.videoTracks[track_index]
        else:
            track = seq.audioTracks[track_index]

        clip = track.clips[clip_index]
        if new_in is not None:
            clip.inPoint = new_in
        if new_out is not None:
            clip.outPoint = new_out
        return True

    def set_clip_speed(
        self,
        track_index: int,
        clip_index: int,
        speed_multiplier: float,
    ) -> bool:
        """클립 속도를 변경합니다. JSX를 통해 실행합니다.

        Args:
            speed_multiplier: 1.0 = 정상, 2.0 = 2배속, 0.5 = 0.5배속
        """
        jsx = f"""
        var seq = app.project.activeSequence;
        var track = seq.videoTracks[{track_index}];
        var clip = track.clips[{clip_index}];
        clip.setSpeed({speed_multiplier}, 0, true, false);
        "success";
        """
        result = self.conn.execute_jsx(jsx)
        return result == "success"

    # ─── 타임라인 자르기 (Razor Cut) ─────────────────

    def razor_cut(self, time_seconds: float, track_indices: list[int] = None) -> bool:
        """지정된 시간에 razor cut을 수행합니다.

        Args:
            time_seconds: 자를 위치 (초)
            track_indices: 자를 트랙 인덱스 목록 (None이면 모든 트랙)
        """
        seq = self.active_sequence

        if track_indices is None:
            track_indices = list(range(seq.videoTracks.numTracks))

        tracks_js = ",".join(str(i) for i in track_indices)
        jsx = f"""
        var seq = app.project.activeSequence;
        var time = new Time();
        time.seconds = {time_seconds};
        var trackIndices = [{tracks_js}];

        for (var t = 0; t < trackIndices.length; t++) {{
            var trackIdx = trackIndices[t];
            var track = seq.videoTracks[trackIdx];
            for (var c = track.clips.numItems - 1; c >= 0; c--) {{
                var clip = track.clips[c];
                if (clip.start.seconds < time.seconds && clip.end.seconds > time.seconds) {{
                    // QE를 사용한 razor cut
                    var qeSeq = qe.project.getActiveSequence();
                    var qeTrack = qeSeq.getVideoTrackAt(trackIdx);
                    qeTrack.razor(time);
                    break;
                }}
            }}
        }}
        "success";
        """
        result = self.conn.execute_jsx(jsx)
        return "success" in result

    # ─── 재생 제어 ──────────────────────────────────

    def play(self) -> None:
        """재생합니다."""
        jsx = "app.project.activeSequence.player.play(1.0);"
        self.conn.execute_jsx(jsx)

    def pause(self) -> None:
        """일시정지합니다."""
        jsx = "app.project.activeSequence.player.play(0);"
        self.conn.execute_jsx(jsx)

    def go_to_time(self, seconds: float) -> None:
        """특정 시간으로 이동합니다."""
        jsx = f"""
        var time = new Time();
        time.seconds = {seconds};
        app.project.activeSequence.setPlayerPosition(time.ticks);
        """
        self.conn.execute_jsx(jsx)

    def get_current_time(self) -> float:
        """현재 재생 헤드 위치를 초 단위로 반환합니다."""
        jsx = """
        var pos = app.project.activeSequence.getPlayerPosition();
        var time = new Time();
        time.ticks = pos;
        time.seconds;
        """
        result = self.conn.execute_jsx(jsx)
        return float(result)

    # ─── 시퀀스 인/아웃 포인트 ──────────────────────

    def set_work_area(self, in_seconds: float, out_seconds: float) -> bool:
        """시퀀스의 작업 영역(인/아웃 포인트)을 설정합니다."""
        seq = self.active_sequence
        seq.setInPoint(in_seconds)
        seq.setOutPoint(out_seconds)
        return True

    # ─── 유틸리티 ──────────────────────────────────

    def _find_project_item(self, root_item, name: str):
        """프로젝트 아이템을 이름으로 재귀 검색합니다."""
        for i in range(root_item.children.numItems):
            child = root_item.children[i]
            if child.name == name:
                return child
            # 빈 내부 검색
            if hasattr(child, "children") and child.children:
                found = self._find_project_item(child, name)
                if found:
                    return found
        return None
