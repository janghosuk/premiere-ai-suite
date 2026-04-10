"""마커 관리 모듈"""

from .connection import PremiereConnection


class MarkerManager:
    """시퀀스 및 클립 마커를 관리합니다."""

    # 마커 색상 매핑
    COLORS = {
        "green": 0, "녹색": 0,
        "red": 1, "빨강": 1,
        "purple": 2, "보라": 2,
        "orange": 3, "주황": 3,
        "yellow": 4, "노랑": 4,
        "white": 5, "흰색": 5,
        "blue": 6, "파랑": 6,
        "cyan": 7, "청록": 7,
    }

    def __init__(self, conn: PremiereConnection):
        self.conn = conn

    @property
    def active_sequence(self):
        seq = self.conn.app.project.activeSequence
        if not seq:
            raise RuntimeError("활성 시퀀스가 없습니다.")
        return seq

    def list_markers(self) -> list[dict]:
        """시퀀스 마커 목록을 반환합니다."""
        seq = self.active_sequence
        markers_obj = seq.markers
        markers = []

        marker = markers_obj.getFirstMarker()
        while marker:
            markers.append({
                "name": marker.name,
                "comment": marker.comments,
                "start": marker.start.seconds,
                "end": marker.end.seconds,
                "type": marker.type,
                "color": self._color_name(marker.colorIndex if hasattr(marker, "colorIndex") else -1),
            })
            marker = markers_obj.getNextMarker(marker)

        return markers

    def add_marker(
        self,
        time_seconds: float,
        name: str = "",
        comment: str = "",
        color: str = "green",
        duration_seconds: float = 0.0,
    ) -> bool:
        """시퀀스에 마커를 추가합니다.

        Args:
            time_seconds: 마커 위치 (초)
            name: 마커 이름
            comment: 마커 코멘트
            color: 마커 색상 (한글/영문)
            duration_seconds: 마커 길이 (0 = 포인트 마커)
        """
        seq = self.active_sequence
        marker = seq.markers.createMarker(time_seconds)
        marker.name = name
        marker.comments = comment

        if duration_seconds > 0:
            marker.end = time_seconds + duration_seconds

        color_idx = self.COLORS.get(color.lower(), 0)
        jsx = f"""
        var seq = app.project.activeSequence;
        var markers = seq.markers;
        var marker = markers.getFirstMarker();
        var targetTime = {time_seconds};

        while (marker) {{
            if (Math.abs(marker.start.seconds - targetTime) < 0.01) {{
                marker.setColorByIndex({color_idx});
                break;
            }}
            marker = markers.getNextMarker(marker);
        }}
        "success";
        """
        self.conn.execute_jsx(jsx)
        return True

    def remove_marker_at(self, time_seconds: float) -> bool:
        """특정 시간의 마커를 제거합니다."""
        seq = self.active_sequence
        markers_obj = seq.markers

        marker = markers_obj.getFirstMarker()
        while marker:
            if abs(marker.start.seconds - time_seconds) < 0.01:
                markers_obj.deleteMarker(marker)
                return True
            marker = markers_obj.getNextMarker(marker)

        raise ValueError(f"{time_seconds}초 위치에 마커가 없습니다.")

    def clear_all_markers(self) -> int:
        """모든 시퀀스 마커를 제거합니다. 제거된 마커 수를 반환합니다."""
        seq = self.active_sequence
        markers_obj = seq.markers
        count = 0

        marker = markers_obj.getFirstMarker()
        while marker:
            next_marker = markers_obj.getNextMarker(marker)
            markers_obj.deleteMarker(marker)
            count += 1
            marker = next_marker

        return count

    def add_clip_marker(
        self,
        track_index: int,
        clip_index: int,
        time_seconds: float,
        name: str = "",
        comment: str = "",
    ) -> bool:
        """클립에 마커를 추가합니다.

        Args:
            track_index: 비디오 트랙 번호
            clip_index: 클립 인덱스
            time_seconds: 클립 내 상대 시간 (초)
            name: 마커 이름
            comment: 코멘트
        """
        seq = self.active_sequence
        clip = seq.videoTracks[track_index].clips[clip_index]
        project_item = clip.projectItem

        marker = project_item.markers.createMarker(time_seconds)
        marker.name = name
        marker.comments = comment
        return True

    def _color_name(self, index: int) -> str:
        """색상 인덱스를 이름으로 변환합니다."""
        names = ["green", "red", "purple", "orange", "yellow", "white", "blue", "cyan"]
        if 0 <= index < len(names):
            return names[index]
        return "unknown"
