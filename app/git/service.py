import os
import shutil
import subprocess
from datetime import datetime, timezone


class GitService:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def _repo_path(self, username, doc_id):
        return os.path.join(self.data_dir, username, doc_id)

    def _md_path(self, repo_path, rel_path):
        return os.path.normpath(os.path.join(repo_path, rel_path))

    # ── repo lifecycle ──────────────────────────────────────────

    def init_repo(self, username, doc_id):
        repo_path = self._repo_path(username, doc_id)
        os.makedirs(repo_path, exist_ok=True)
        subprocess.run(
            ["git", "init", "--initial-branch=main"],
            cwd=repo_path, check=True, capture_output=True
        )
        return repo_path

    def repo_exists(self, username, doc_id):
        return os.path.isdir(self._repo_path(username, doc_id))

    def ensure_repo(self, username, doc_id):
        if not self.repo_exists(username, doc_id):
            return self.init_repo(username, doc_id)
        return self._repo_path(username, doc_id)

    # ── file operations ─────────────────────────────────────────

    def list_files(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        result = []
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d != ".git"]
            rel = os.path.relpath(root, repo_path)
            for f in files:
                full_rel = os.path.join(rel, f) if rel != "." else f
                if full_rel.replace(os.sep, "/").startswith(".git/"):
                    continue
                result.append({
                    "name": f,
                    "path": full_rel,
                    "dir": rel if rel != "." else "",
                })
        return sorted(result, key=lambda x: x["path"])

    def read_file(self, username, doc_id, rel_path):
        repo_path = self.ensure_repo(username, doc_id)
        safe_path = self._md_path(repo_path, rel_path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        if not os.path.exists(safe_path):
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write("")
        with open(safe_path, encoding="utf-8") as f:
            return f.read()

    def write_file(self, username, doc_id, rel_path, content):
        repo_path = self.ensure_repo(username, doc_id)
        safe_path = self._md_path(repo_path, rel_path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return safe_path

    # ── git operations ──────────────────────────────────────────

    def _git(self, repo_path, *args):
        result = subprocess.run(
            ["git"] + list(args),
            cwd=repo_path, capture_output=True, text=True
        )
        return result.returncode, result.stdout, result.stderr

    def status(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "status", "--porcelain")
        changed = []
        for line in out.strip().splitlines():
            if line:
                st = line[:2]
                path = line[3:]
                changed.append({"path": path, "staged": "A" in st or "M" in st[:1], "modified": "M" in st or "M" in st[1:]})
        return changed

    def add_all(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "add", "-A")
        return code == 0

    def commit(self, username, doc_id, message):
        repo_path = self.ensure_repo(username, doc_id)
        self.add_all(username, doc_id)
        code, out, err = self._git(repo_path, "commit", "-m", message)
        if code != 0:
            return False, err.strip()
        _, sha, _ = self._git(repo_path, "rev-parse", "HEAD")
        return True, sha.strip()

    def log(self, username, doc_id, count=20):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(
            repo_path, "log", f"-n{count}",
            "--pretty=format:%H|%s|%an|%ad",
            "--date=iso"
        )
        commits = []
        for line in out.strip().splitlines():
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "sha": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                })
        return commits

    def diff(self, username, doc_id, sha=None, path=None):
        repo_path = self.ensure_repo(username, doc_id)
        args = ["diff"]
        if sha:
            args.extend(["HEAD", sha])
        else:
            args.append("--cached")
        if path:
            args.extend(["--", path])
        code, out, err = self._git(repo_path, *args)
        return out

    def pull(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "pull", "--no-rebase")
        return code == 0, err.strip() if code != 0 else ""

    def push(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "push")
        return code == 0, err.strip() if code != 0 else ""

    def get_head_sha(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "rev-parse", "HEAD")
        return out.strip() if code == 0 else ""

    def current_branch(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "branch", "--show-current")
        return out.strip() if code == 0 else "main"
