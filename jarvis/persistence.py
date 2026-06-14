"""Free persistence for JARVIS by snapshotting to a (private) HF Dataset.

A Hugging Face Space's free tier has no persistent disk: the container's
filesystem is wiped on every restart. To keep your conversations and long-term
memory for free, we mirror the small set of data files (the SQLite database and
the facts JSON) to a private HF Dataset repo:

* on boot, download the latest snapshot into the data directory;
* after changes, upload the files back — debounced, so a burst of turns
  produces at most one commit every few seconds.

It reuses the same Hugging Face account used for inference; you only need a
*write* token and a dataset repo id (JARVIS_HF_DATASET). If either is missing,
persistence is silently disabled and JARVIS runs exactly as before.
"""

from __future__ import annotations

import threading
from pathlib import Path

# Files in data_dir worth preserving. Both are small (KBs–low MBs for one user).
SNAPSHOT_FILES = ("jarvis.db", "memory.json")


class HFDatasetPersistence:
    def __init__(
        self,
        data_dir: Path,
        repo_id: str,
        token: str,
        debounce_seconds: float = 5.0,
    ) -> None:
        from huggingface_hub import HfApi  # imported lazily; optional dependency

        self.data_dir = data_dir
        self.repo_id = repo_id
        self.token = token
        self.debounce = debounce_seconds
        self.api = HfApi(token=token)
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config) -> "HFDatasetPersistence | None":
        """Build from config, or return None if not configured / unavailable."""
        if not config.hf_dataset or not config.hf_data_token:
            return None
        try:
            import huggingface_hub  # noqa: F401
        except ImportError:
            print("[persistence] huggingface_hub not installed; skipping.")
            return None
        try:
            inst = cls(config.data_dir, config.hf_dataset, config.hf_data_token)
            inst.api.create_repo(
                repo_id=inst.repo_id,
                repo_type="dataset",
                private=True,
                exist_ok=True,
            )
            return inst
        except Exception as exc:  # network / auth / bad repo id
            print(f"[persistence] disabled ({exc}).")
            return None

    # ── restore (boot) ─────────────────────────────────────────────────
    def restore(self) -> None:
        """Pull the latest snapshot into data_dir. Missing files are fine — a
        brand-new dataset simply has nothing to restore yet."""
        from huggingface_hub import hf_hub_download
        from huggingface_hub.utils import EntryNotFoundError

        self.data_dir.mkdir(parents=True, exist_ok=True)
        restored = []
        for name in SNAPSHOT_FILES:
            try:
                path = hf_hub_download(
                    repo_id=self.repo_id,
                    repo_type="dataset",
                    filename=name,
                    token=self.token,
                )
                (self.data_dir / name).write_bytes(Path(path).read_bytes())
                restored.append(name)
            except EntryNotFoundError:
                continue
            except Exception as exc:
                print(f"[persistence] could not restore {name}: {exc}")
        if restored:
            print(f"[persistence] restored {', '.join(restored)} from {self.repo_id}.")

    # ── save (debounced) ───────────────────────────────────────────────
    def request_save(self) -> None:
        """Schedule an upload, coalescing rapid successive calls into one."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def flush_now(self) -> None:
        """Upload immediately (e.g. on shutdown), cancelling any pending timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._flush()

    def _flush(self) -> None:
        from huggingface_hub import CommitOperationAdd

        ops = [
            CommitOperationAdd(
                path_in_repo=name,
                path_or_fileobj=str(self.data_dir / name),
            )
            for name in SNAPSHOT_FILES
            if (self.data_dir / name).exists()
        ]
        if not ops:
            return
        try:
            self.api.create_commit(
                repo_id=self.repo_id,
                repo_type="dataset",
                operations=ops,
                commit_message="Update JARVIS snapshot",
            )
        except Exception as exc:
            print(f"[persistence] save failed: {exc}")
