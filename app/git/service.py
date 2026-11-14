import os
import shutil
import subprocess
from datetime import datetime, timezone


class GitService:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    # ── 工作区注册表（原地模式：doc_id → 源目录） ────────────────

    def _registry_path(self, username):
        return os.path.join(self.data_dir, username, "workspaces.json")

    def load_registry(self, username):
        p = self._registry_path(username)
        if not os.path.isfile(p):
            return {}
        try:
            import json
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_registry(self, username, reg):
        import json
        os.makedirs(os.path.dirname(self._registry_path(username)), exist_ok=True)
        with open(self._registry_path(username), "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)

    def _repo_path(self, username, doc_id):
        """原地模式：注册表命中则返回源目录（仓库即源目录）；否则回退 data/<user>/<doc_id>（docs 模式）"""
        entry = self.load_registry(username).get(doc_id)
        if entry and entry.get("source_path") and os.path.isdir(entry["source_path"]):
            return entry["source_path"]
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
        # 默认提交身份，避免首次 commit 因缺 user.name/email 失败
        _, name, _ = self._git(repo_path, "config", "user.name")
        if not name.strip():
            self._git(repo_path, "config", "user.name", username)
        _, email, _ = self._git(repo_path, "config", "user.email")
        if not email.strip():
            self._git(repo_path, "config", "user.email", f"{username}@vanilla.local")
        self._ensure_local_exclude(repo_path)
        return repo_path

    _LOCAL_EXCLUDE_REQUIRED = (".ve/",)

    def _ensure_local_exclude(self, repo_path):
        """保证仓库本地排除规则包含 .ve/（DESIGN 4.3.2）。
        写入 `.git/info/exclude` 而非 .gitignore：排除规则本身属于设备本地配置，
        入库会在新设备首拉时与远端历史中的同名文件冲突（untracked overwritten），
        与 .ve 同类问题；info/exclude 天然不入库、无此冲突。幂等追加缺失行。"""
        exclude_dir = os.path.join(repo_path, ".git", "info")
        exclude_path = os.path.join(exclude_dir, "exclude")
        try:
            os.makedirs(exclude_dir, exist_ok=True)
            existing = ""
            if os.path.isfile(exclude_path):
                with open(exclude_path, encoding="utf-8") as f:
                    existing = f.read()
            missing = [line for line in self._LOCAL_EXCLUDE_REQUIRED
                       if line not in existing.splitlines()]
            if not missing:
                return
            with open(exclude_path, "a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write("# VanillaEditor 设备本地配置（不入库，DESIGN 4.3.2）\n")
                for line in missing:
                    f.write(line + "\n")
        except OSError:
            pass

    def _untrack_ve_if_tracked(self, repo_path):
        """历史仓库迁移：.ve/ 已被跟踪则 untrack 并提交一次（DESIGN 4.3.2）"""
        code, out, _ = self._git(repo_path, "ls-files", "--", ".ve")
        if code != 0 or not out.strip():
            return False
        self._git(repo_path, "rm", "-r", "--cached", "--quiet", ".ve")
        self._ensure_local_exclude(repo_path)
        # -c 内联身份：旧仓库可能未配置 user.name/email
        self._git(repo_path, "-c", "user.name=vanilla", "-c", "user.email=vanilla@local",
                  "commit", "-m", "chore: untrack .ve device-local config")
        return True

    def repo_exists(self, username, doc_id):
        """原地模式：注册表命中即存在；docs 模式：目录下有 .git 才算"""
        entry = self.load_registry(username).get(doc_id)
        if entry and entry.get("source_path"):
            return os.path.isdir(entry["source_path"])
        return os.path.isdir(os.path.join(self._repo_path(username, doc_id), ".git"))

    def ensure_repo(self, username, doc_id):
        """原地模式：源目录已含 .git 则复用（并迁移 .ve 入库遗留），否则在源目录内 git init（DESIGN 4.3.1/4.3.2）"""
        repo_path = self._repo_path(username, doc_id)
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            return self.init_repo(username, doc_id)
        self._ensure_local_exclude(repo_path)
        self._untrack_ve_if_tracked(repo_path)
        return repo_path

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
        """读取文件；不存在时返回空字符串（原地模式下禁止在用户目录凭空创建文件）"""
        repo_path = self._repo_path(username, doc_id)
        safe_path = self._md_path(repo_path, rel_path)
        if not os.path.isfile(safe_path):
            return ""
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
            ["git", "-c", "core.quotepath=false"] + list(args),
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
        """拉取默认 upstream；无 upstream 时回退到第一个远端（DESIGN 7.2）"""
        repo_path = self.ensure_repo(username, doc_id)
        branch = self.current_branch(username, doc_id)
        code, out, err = self._git(repo_path, "pull", "--no-rebase")
        if code != 0 and ("no tracking information" in err
                          or "did not specify a branch" in err):
            remote = self._first_remote(repo_path)
            if remote:
                return self.pull_from(username, doc_id, remote)
        return code == 0, err.strip() if code != 0 else ""

    def push(self, username, doc_id):
        """推送到默认 upstream；无 upstream 时回退到第一个远端（DESIGN 7.2）"""
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "push")
        if code != 0 and "no upstream branch" in err:
            remote = self._first_remote(repo_path)
            if remote:
                return self.push_to(username, doc_id, remote)
        return code == 0, err.strip() if code != 0 else ""

    def fetch_all(self, username, doc_id):
        """从所有远端拉取引用，但不合并。返回 (ok, error)"""
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "fetch", "--all", "--prune")
        return code == 0, err.strip() if code != 0 else ""

    def push_to(self, username, doc_id, remote):
        """按远端推送：显式携带当前分支名，首次推送 -u 建立 upstream（DESIGN 7.2）"""
        repo_path = self.ensure_repo(username, doc_id)
        branch = self.current_branch(username, doc_id)
        code, out, err = self._git(repo_path, "push", "-u", remote, branch)
        return code == 0, err.strip() if code != 0 else ""

    def pull_from(self, username, doc_id, remote):
        """按远端拉取：显式携带当前分支名，不依赖 upstream 配置（DESIGN 7.2）"""
        repo_path = self.ensure_repo(username, doc_id)
        branch = self.current_branch(username, doc_id)
        code, out, err = self._git(repo_path, "pull", "--no-rebase", remote, branch)
        return code == 0, err.strip() if code != 0 else ""

    def _first_remote(self, repo_path):
        """返回远端列表中的第一个名字，无远端时返回 None"""
        code, out, _ = self._git(repo_path, "remote")
        remotes = [line.strip() for line in out.strip().splitlines() if line.strip()]
        return remotes[0] if remotes else None

    def remote_list(self, username, doc_id):
        """返回 [{name, url, push_url}]"""
        repo_path = self.ensure_repo(username, doc_id)
        code, out, _ = self._git(repo_path, "remote", "-v")
        remotes = []
        seen = set()
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name, url = parts[0], parts[1]
            key = name + "|" + url
            if key in seen:
                continue
            seen.add(key)
            remotes.append({"name": name, "url": url})
        return remotes

    def remote_tracking(self, username, doc_id):
        """返回当前分支的跟踪信息 {branch, remote, ahead, behind, diverged}"""
        repo_path = self.ensure_repo(username, doc_id)
        branch = self.current_branch(username, doc_id)
        code, out, _ = self._git(repo_path, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
        upstream = out.strip() if code == 0 else ""
        if not upstream:
            return {"branch": branch, "remote": "", "ahead": 0, "behind": 0, "diverged": False, "synced": False}
        # 本地领先/落后远端的提交数
        code, out, _ = self._git(repo_path, "rev-list", "--left-right", "--count", f"{branch}...{upstream}")
        ahead = behind = 0
        if code == 0:
            try:
                parts = out.strip().split()
                ahead = int(parts[0])
                behind = int(parts[1])
            except (ValueError, IndexError):
                pass
        remote = upstream.split("/")[0] if "/" in upstream else ""
        return {
            "branch": branch,
            "remote": remote,
            "ahead": ahead,
            "behind": behind,
            "diverged": ahead > 0 and behind > 0,
            "synced": ahead == 0 and behind == 0,
        }

    def unmerged_files(self, username, doc_id):
        """返回冲突（未合并）文件列表"""
        repo_path = self.ensure_repo(username, doc_id)
        code, out, _ = self._git(repo_path, "diff", "--name-only", "--diff-filter=U")
        return [line for line in out.strip().splitlines() if line.strip()]

    def has_uncommitted(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, _ = self._git(repo_path, "status", "--porcelain")
        return bool(out.strip())

    def get_head_sha(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "rev-parse", "HEAD")
        return out.strip() if code == 0 else ""

    def current_branch(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, err = self._git(repo_path, "branch", "--show-current")
        return out.strip() if code == 0 else "main"

    # ── config / branches / merge / reset ───────────────────────

    def get_config(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        _, name, _ = self._git(repo_path, "config", "user.name")
        _, email, _ = self._git(repo_path, "config", "user.email")
        return {"name": name.strip(), "email": email.strip()}

    def set_config(self, username, doc_id, name=None, email=None):
        repo_path = self.ensure_repo(username, doc_id)
        ok = True
        if name:
            ok = ok and self._git(repo_path, "config", "user.name", name)[0] == 0
        if email:
            ok = ok and self._git(repo_path, "config", "user.email", email)[0] == 0
        return ok

    def branches(self, username, doc_id):
        repo_path = self.ensure_repo(username, doc_id)
        code, out, _ = self._git(repo_path, "branch", "--format=%(refname:short)|%(HEAD)")
        result = []
        for line in out.splitlines():
            if "|" in line:
                name, head = line.split("|", 1)
                result.append({"name": name.strip(), "current": head.strip() == "*"})
        return result

    def checkout(self, username, doc_id, name, create=False):
        repo_path = self.ensure_repo(username, doc_id)
        args = ["checkout", "-b", name] if create else ["checkout", name]
        code, _, err = self._git(repo_path, *args)
        return code == 0, err.strip() if code != 0 else ""

    def merge(self, username, doc_id, branch):
        repo_path = self.ensure_repo(username, doc_id)
        code, _, err = self._git(repo_path, "merge", "--no-edit", branch)
        return code == 0, err.strip() if code != 0 else ""

    def reset_hard(self, username, doc_id, sha):
        repo_path = self.ensure_repo(username, doc_id)
        code, _, err = self._git(repo_path, "reset", "--hard", sha)
        return code == 0, err.strip() if code != 0 else ""
