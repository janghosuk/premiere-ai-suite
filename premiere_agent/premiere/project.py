"""프로젝트 관리 모듈 - 프로젝트 열기/저장/미디어 임포트"""

import os
from .connection import PremiereConnection


class ProjectManager:
    """Premiere Pro 프로젝트를 관리합니다."""

    def __init__(self, conn: PremiereConnection):
        self.conn = conn

    def get_project_info(self) -> dict:
        """현재 프로젝트 정보를 반환합니다."""
        project = self.conn.app.project
        if not project:
            return {"error": "열린 프로젝트가 없습니다."}

        sequences = []
        for i in range(project.sequences.numSequences):
            seq = project.sequences[i]
            sequences.append({
                "name": seq.name,
                "id": seq.sequenceID,
                "frame_rate": str(seq.timebase),
            })

        active_seq = project.activeSequence
        return {
            "name": project.name,
            "path": project.path,
            "sequences": sequences,
            "active_sequence": active_seq.name if active_seq else None,
            "num_sequences": project.sequences.numSequences,
        }

    def open_project(self, path: str) -> bool:
        """프로젝트 파일을 엽니다."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"프로젝트 파일을 찾을 수 없습니다: {path}")
        return self.conn.app.openDocument(path)

    def save_project(self) -> bool:
        """현재 프로젝트를 저장합니다."""
        project = self.conn.app.project
        if not project:
            raise RuntimeError("열린 프로젝트가 없습니다.")
        project.save()
        return True

    def save_project_as(self, path: str) -> bool:
        """다른 이름으로 프로젝트를 저장합니다."""
        project = self.conn.app.project
        if not project:
            raise RuntimeError("열린 프로젝트가 없습니다.")
        project.saveAs(path)
        return True

    def close_project(self, save: bool = True) -> bool:
        """프로젝트를 닫습니다."""
        if save:
            self.save_project()
        return self.conn.app.project.closeDocument()

    def import_media(self, file_paths: list[str], target_bin: str = None) -> list[str]:
        """미디어 파일을 프로젝트에 임포트합니다.

        Args:
            file_paths: 임포트할 파일 경로 목록
            target_bin: 대상 빈 이름 (None이면 루트)

        Returns:
            성공적으로 임포트된 파일 목록
        """
        project = self.conn.app.project
        if not project:
            raise RuntimeError("열린 프로젝트가 없습니다.")

        # 파일 존재 확인
        valid_paths = []
        for fp in file_paths:
            if os.path.exists(fp):
                valid_paths.append(fp)
            else:
                print(f"[경고] 파일을 찾을 수 없습니다: {fp}")

        if not valid_paths:
            return []

        if target_bin:
            # 빈 찾기 또는 생성
            root_item = project.rootItem
            bin_item = self._find_or_create_bin(root_item, target_bin)
            success = project.importFiles(
                valid_paths,
                suppressUI=True,
                targetBin=bin_item,
                importAsNumberedStills=False,
            )
        else:
            success = project.importFiles(valid_paths)

        return valid_paths if success else []

    def create_bin(self, name: str, parent_path: str = None) -> bool:
        """새 빈(폴더)을 생성합니다."""
        project = self.conn.app.project
        root = project.rootItem

        if parent_path:
            parent = self._find_bin_by_path(root, parent_path)
            if not parent:
                raise ValueError(f"빈을 찾을 수 없습니다: {parent_path}")
            parent.createBin(name)
        else:
            root.createBin(name)
        return True

    def list_project_items(self, bin_path: str = None) -> list[dict]:
        """프로젝트 아이템 목록을 반환합니다."""
        project = self.conn.app.project
        root = project.rootItem

        if bin_path:
            target = self._find_bin_by_path(root, bin_path)
            if not target:
                return []
        else:
            target = root

        items = []
        for i in range(target.children.numItems):
            child = target.children[i]
            items.append({
                "name": child.name,
                "type": str(child.type),
                "path": child.treePath if hasattr(child, "treePath") else "",
            })
        return items

    def create_sequence(self, name: str, preset_path: str = None) -> bool:
        """새 시퀀스를 생성합니다."""
        project = self.conn.app.project
        if preset_path:
            project.createNewSequenceFromPreset(preset_path, name)
        else:
            # 기본 프리셋으로 생성 (JSX 사용)
            jsx = f"""
            var project = app.project;
            project.createNewSequence("{name}");
            """
            self.conn.execute_jsx(jsx)
        return True

    def set_active_sequence(self, sequence_name: str) -> bool:
        """활성 시퀀스를 변경합니다."""
        project = self.conn.app.project
        for i in range(project.sequences.numSequences):
            seq = project.sequences[i]
            if seq.name == sequence_name:
                project.activeSequence = seq
                return True
        raise ValueError(f"시퀀스를 찾을 수 없습니다: {sequence_name}")

    def _find_or_create_bin(self, root_item, bin_name: str):
        """빈을 찾거나 없으면 생성합니다."""
        for i in range(root_item.children.numItems):
            child = root_item.children[i]
            if child.name == bin_name and child.type == 2:  # bin type
                return child
        root_item.createBin(bin_name)
        # 새로 만든 빈 반환
        for i in range(root_item.children.numItems):
            child = root_item.children[i]
            if child.name == bin_name:
                return child
        return None

    def _find_bin_by_path(self, root_item, path: str):
        """경로로 빈을 찾습니다. 예: 'Footage/Raw'"""
        parts = path.split("/")
        current = root_item
        for part in parts:
            found = False
            for i in range(current.children.numItems):
                child = current.children[i]
                if child.name == part:
                    current = child
                    found = True
                    break
            if not found:
                return None
        return current
