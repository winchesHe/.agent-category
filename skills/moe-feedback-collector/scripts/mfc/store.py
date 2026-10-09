from __future__ import annotations

import json
import hashlib
import fcntl
import os
import tempfile
from pathlib import Path

from .errors import BusinessError


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def _safe_dir(self, path):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        current = path
        while current == self.root or self.root in current.parents:
            os.chmod(current, 0o700)
            if current == self.root:
                break
            current = current.parent
        return path

    def _write_json(self, path, value):
        path = Path(path)
        self._safe_dir(path.parent)
        handle = None
        temp_path = None
        try:
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            )
            temp_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
            return path
        except OSError as exc:
            if handle and not handle.closed:
                handle.close()
            if temp_path and temp_path.exists():
                temp_path.unlink()
            raise BusinessError(f"无法写入本地证据：{path}") from exc

    def load_checkpoint(self, source):
        path = self.root / "state" / f"{source}.json"
        if not path.exists():
            return {"schemaVersion": 1, "sourceKey": source, "posts": {}}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BusinessError("本地检查点损坏") from exc
        if value.get("schemaVersion") != 1 or not isinstance(value.get("posts"), dict):
            raise BusinessError("本地检查点 Schema 不受支持")
        return value

    def acquire_source_lock(self, source):
        lock_path = self._safe_dir(self.root / "locks") / f"{source}.lock"
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = None
        try:
            descriptor = os.open(str(lock_path), flags, 0o600)
            os.chmod(lock_path, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return descriptor
        except BlockingIOError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise BusinessError(f"信息源已有采集任务运行：{source}") from exc
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise BusinessError(f"无法锁定信息源：{source}") from exc

    @staticmethod
    def release_source_lock(descriptor):
        if descriptor is None:
            return
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    def save_run(
        self, source, run_id, manifest, evidence, checkpoint, report_rows=None
    ):
        evidence_paths = []
        for item in evidence:
            evidence_id = str(item["evidenceId"])
            artifact_id = hashlib.sha256(evidence_id.encode("utf-8")).hexdigest()[:24]
            object_type = str(item.get("objectType") or "object")
            path = self.root / "evidence" / source / f"{object_type}-{artifact_id}.json"
            evidence_paths.append(str(self._write_json(path, item)))
        run_path = self._write_json(
            self.root / "runs" / source / f"{run_id}.json",
            {
                "manifest": manifest,
                "evidence": evidence,
                "reportRows": report_rows if report_rows is not None else evidence,
            },
        )
        checkpoint_path = (
            self._write_json(self.root / "state" / f"{source}.json", checkpoint)
            if checkpoint is not None
            else None
        )
        manifest_value = dict(manifest)
        manifest_value.update(
            {
                "runArtifact": str(run_path),
                "evidenceArtifacts": evidence_paths,
            }
        )
        if checkpoint_path is not None:
            manifest_value["checkpointArtifact"] = str(checkpoint_path)
        manifest_path = self._write_json(
            self.root / "manifests" / f"{run_id}.json", manifest_value
        )
        return str(manifest_path), manifest_value
