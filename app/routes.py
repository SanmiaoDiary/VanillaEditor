import os
import shutil
import socket
import stat
import sys
import time
from flask import Flask, request, jsonify, g
from functools import wraps
import jwt
from datetime import datetime, timezone, timedelta
import bcrypt

from app.git.service import GitService

DEFAULT_PORT = 58446


def _port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _random_free_port(host):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))  # OS 分配一个可用高位端口
        return s.getsockname()[1]


def pick_port(host):
    """端口策略（DESIGN 8.3）：
    - 用户显式设置 PORT → 强意图，被占用直接报错退出
    - 未设置 → 默认 58446；被占用时让 OS 分配随机可用高位端口
    选定后写回 os.environ["PORT"]，debug reloader 重启子进程沿用同一端口
    - Werkzeug reloader 子进程（WERKZEUG_RUN_MAIN=true）不做二次探测：父进程此时
      已绑定端口，重新探测会把显式 PORT 误判为"被占用"而启动失败
    """
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return port
    explicit = "PORT" in os.environ
    if not explicit:
        os.environ["PORT"] = str(port)
    if _port_free(host, port):
        return port
    if explicit:
        raise SystemExit(f"[启动失败] 端口 {port} 已被占用（PORT 为显式配置，不自动更换）")
    fallback = _random_free_port(host)
    os.environ["PORT"] = str(fallback)
    print(f"[端口回退] 默认端口 {port} 已被占用，改用 {fallback}")
    return fallback


def _force_rmtree(path, retries=3):
    """Windows 下 .git 对象文件可能带只读属性，先清除只读再删除，失败重试。"""
    import sys as _sys
    def _clear(func, p, exc):
        try:
            # 给文件加上写权限（保留原有权限）
            os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE)
        except OSError:
            pass
        func(p)

    remove = lambda p: shutil.rmtree(p, onexc=_clear) if _sys.version_info >= (3, 12) else shutil.rmtree(p, onerror=_clear)

    for i in range(retries):
        try:
            remove(path)
            return True
        except OSError:
            if i == retries - 1:
                raise
            time.sleep(0.3)


def create_app():
    app = Flask(__name__, static_folder="../static", static_url_path="/")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(32))
    jwt_secret = os.environ.get("JWT_SECRET", "dev-secret-change-me")
    if jwt_secret == "dev-secret-change-me":
        # DESIGN 8.4：默认密钥意味着令牌可被任何人伪造
        msg = ("[安全警告] JWT_SECRET 使用默认值 dev-secret-change-me，"
               "令牌可被伪造，请设置强随机密钥（如: python -c \"import secrets; print(secrets.token_hex(32))\"）")
        if os.environ.get("VE_REQUIRE_SECRET") == "1":
            raise SystemExit("[启动失败] " + msg + " （VE_REQUIRE_SECRET=1，生产部署强制检查）")
        print("=" * 70)
        print(msg)
        print("=" * 70)
    app.config["JWT_SECRET"] = jwt_secret
    app.config["DATA_DIR"] = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
    app.config["PORT"] = int(os.environ.get("PORT", 58446))
    app.config["HOST"] = os.environ.get("HOST", "0.0.0.0")

    git_service = GitService(app.config["DATA_DIR"])

    # ── auth helpers ──────────────────────────────────────────

    def _users_path():
        return os.path.join(app.config["DATA_DIR"], "users.json")

    def _load_users():
        p = _users_path()
        if not os.path.exists(p):
            return {}
        import json
        try:
            with open(p, encoding="utf-8-sig") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_users(users):
        import json
        with open(_users_path(), "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

    def require_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                return jsonify({"error": "未登录"}), 401
            try:
                payload = jwt.decode(token, app.config["JWT_SECRET"], algorithms=["HS256"])
                # token_version 吊销校验：载荷 ver 与当前存储版本一致才有效
                users = _load_users()
                user = users.get(payload["sub"])
                if user is None:
                    return jsonify({"error": "用户不存在"}), 401
                if payload.get("ver", 1) != user.get("token_version", 1):
                    return jsonify({"error": "令牌已失效，请重新登录"}), 401
                g.username = payload["sub"]
                return f(*args, **kwargs)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token 已过期"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"error": "无效的 Token"}), 401
        return decorated

    # ── /api/auth ─────────────────────────────────────────────

    @app.route("/api/auth/init", methods=["POST"])
    def auth_init():
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
        if not username or not password:
            return jsonify({"error": "用户名和密码不能为空"}), 400
        users = _load_users()
        if username in users:
            return jsonify({"error": "用户名已存在"}), 409
        users[username] = {
            "username": username,
            "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_users(users)
        return jsonify({"message": "账号创建成功"}), 201

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
        access_code = data.get("access_code", "")
        if not username or not password:
            return jsonify({"error": "用户名和密码不能为空"}), 400
        # 远程访问开启时：远程来源必须携带访问码（本机来源豁免，DESIGN 4.5.1）
        ra = _load_remote_access()
        if ra.get("enabled") and not _is_local_request():
            if access_code != ra.get("access_code", ""):
                return jsonify({"error": "访问码错误或未填写"}), 401
        users = _load_users()
        user = users.get(username)
        if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return jsonify({"error": "用户名或密码错误"}), 401
        expire = datetime.now(timezone.utc) + timedelta(days=30)
        token = jwt.encode({"sub": username, "exp": expire, "ver": user.get("token_version", 1)}, app.config["JWT_SECRET"], algorithm="HS256")
        # Report login stat for this user
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            entries = _load_stats(username)
            found_login = False
            for e in entries:
                if e.get("date") == today_str:
                    e["login_count"] = e.get("login_count", 0) + 1
                    found_login = True
                    break
            if not found_login:
                entries.append({"date": today_str, "words_added": 0, "push_count": 0, "sync_count": 0, "login_count": 1})
            _save_stats(username, entries)
        except Exception:
            pass  # non-fatal
        return jsonify({"token": token, "username": username})

    @app.route("/api/auth/me", methods=["GET"])
    @require_auth
    def auth_me():
        cfg = _load_remote_access()
        return jsonify({
            "username": g.username,
            "access_url": f"http://{cfg.get('_ip', '127.0.0.1')}:{app.config['PORT']}" if cfg.get("enabled") else None,
            "auth2_enabled": cfg.get("auth2_enabled", True),
        })

    @app.route("/api/public/config", methods=["GET"])
    def public_config():
        """登录页可访问的公开配置（不含敏感信息）"""
        cfg = _load_remote_access()
        # 仅当远程访问开启且不是本地访问时才显示访问码字段
        enabled = cfg.get("enabled", False)
        return jsonify({"remote_access": enabled, "is_local": _is_local_request()})

    # ── /api/docs ─────────────────────────────────────────────

    @app.route("/api/docs", methods=["GET"])
    @require_auth
    def docs_list():
        username = g.username
        user_dir = os.path.join(app.config["DATA_DIR"], username)
        docs = []
        if os.path.isdir(user_dir):
            for item in sorted(os.listdir(user_dir)):
                item_path = os.path.join(user_dir, item)
                if os.path.isdir(item_path):
                    files = git_service.list_files(username, item)
                    sha = git_service.get_head_sha(username, item)
                    docs.append({
                        "id": item,
                        "name": item,
                        "type": "folder",
                        "file_count": len(files),
                        "sha": sha,
                        "children": files,
                    })
        return jsonify(docs)

    @app.route("/api/docs", methods=["POST"])
    @require_auth
    def docs_create():
        username = g.username
        data = request.get_json() or {}
        name = data.get("name", "untitled.md")
        content = data.get("content", "")
        doc_id = data.get("id") or name.replace(" ", "-").lower()
        is_folder = bool(data.get("folder"))
        repo_path = git_service.ensure_repo(username, doc_id)
        if not is_folder:
            git_service.write_file(username, doc_id, name, content)
            git_service.add_all(username, doc_id)
            git_service.commit(username, doc_id, f"init: {name}")
        return jsonify({"id": doc_id, "name": name, "path": name}), 201

    @app.route("/api/docs/<doc_id>", methods=["DELETE"])
    @require_auth
    def docs_delete(doc_id):
        username = g.username
        doc_path = os.path.normpath(os.path.join(app.config["DATA_DIR"], username, doc_id))
        base = os.path.normpath(os.path.join(app.config["DATA_DIR"], username))
        if not doc_path.startswith(base + os.sep):
            return jsonify({"error": "非法路径"}), 400
        if os.path.isdir(doc_path):
            try:
                _force_rmtree(doc_path)
            except OSError as e:
                return jsonify({"error": f"删除失败：{e}"}), 500
        return jsonify({"ok": True})

    # ── /api/files ────────────────────────────────────────────

    @app.route("/api/files/<doc_id>", methods=["GET"])
    @require_auth
    def files_list(doc_id):
        username = g.username
        return jsonify(git_service.list_files(username, doc_id))

    @app.route("/api/files/<doc_id>/<path:rel_path>", methods=["GET"])
    @require_auth
    def files_get(doc_id, rel_path):
        username = g.username
        content = git_service.read_file(username, doc_id, rel_path)
        sha = git_service.get_head_sha(username, doc_id)
        return jsonify({"content": content, "sha": sha})

    @app.route("/api/files/<doc_id>/<path:rel_path>", methods=["PUT"])
    @require_auth
    def files_put(doc_id, rel_path):
        username = g.username
        data = request.get_json() or {}
        content = data.get("content", "")
        # 原地模式：直接写入源目录中的文件
        repo_path = git_service._repo_path(username, doc_id)
        cfg = _read_workspace_config(repo_path)
        source_path = cfg.get("source_path", "")
        if source_path and os.path.isdir(source_path):
            target = os.path.normpath(os.path.join(source_path, rel_path))
            base = os.path.normpath(source_path)
            if target.startswith(base + os.sep) or target == base:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as f:
                    f.write(content)
        # 同时在 git 仓库中提交（用于版本历史和同步）；首次提交为 init: 前缀（DESIGN 4.4.2）
        git_service.write_file(username, doc_id, rel_path, content)
        git_service.add_all(username, doc_id)
        prefix = "init" if not git_service.get_head_sha(username, doc_id) else "update"
        git_service.commit(username, doc_id, f"{prefix}: {rel_path.split('/')[-1]}")
        changed = git_service.status(username, doc_id)
        return jsonify({"ok": True, "changed": changed})

    # ── /api/commit ───────────────────────────────────────────

    @app.route("/api/commit", methods=["POST"])
    @require_auth
    def commit_changes():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        message = data.get("message", "update")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        ok, sha = git_service.commit(username, doc_id, message)
        return jsonify({"ok": ok, "sha": sha})

    # ── /api/history ──────────────────────────────────────────

    @app.route("/api/history/<doc_id>", methods=["GET"])
    @require_auth
    def history_list(doc_id):
        username = g.username
        count = int(request.args.get("count", 20))
        return jsonify(git_service.log(username, doc_id, count))

    # ── /api/status ───────────────────────────────────────────

    @app.route("/api/status/<doc_id>", methods=["GET"])
    @require_auth
    def status_get(doc_id):
        username = g.username
        return jsonify({
            "changed": git_service.status(username, doc_id),
            "sha": git_service.get_head_sha(username, doc_id),
            "branch": git_service.current_branch(username, doc_id),
        })

    # ── /api/sync ─────────────────────────────────────────────

    @app.route("/api/sync/pull", methods=["POST"])
    @require_auth
    def sync_pull():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        ok, err = git_service.pull(username, doc_id)
        if ok: _report_sync_stat(username, "sync_count", 1)
        return jsonify({"ok": ok, "error": err})

    @app.route("/api/sync/push", methods=["POST"])
    @require_auth
    def sync_push():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        ok, err = git_service.push(username, doc_id)
        if ok: _report_sync_stat(username, "push_count", 1)
        return jsonify({"ok": ok, "error": err})

    @app.route("/api/sync/status", methods=["GET"])
    @require_auth
    def sync_status():
        """同步状态：分支、领先/落后、远端列表、是否有冲突/未提交"""
        username = g.username
        doc_id = request.args.get("doc_id", "")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        try:
            tracking = git_service.remote_tracking(username, doc_id)
            remotes = git_service.remote_list(username, doc_id)
            conflicts = git_service.unmerged_files(username, doc_id)
            dirty = git_service.has_uncommitted(username, doc_id)
            return jsonify({
                "tracking": tracking,
                "remotes": remotes,
                "conflicts": conflicts,
                "dirty": dirty,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/sync/fetch", methods=["POST"])
    @require_auth
    def sync_fetch():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        ok, err = git_service.fetch_all(username, doc_id)
        return jsonify({"ok": ok, "error": err})

    @app.route("/api/sync/pull/<remote>", methods=["POST"])
    @require_auth
    def sync_pull_remote(remote):
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        ok, err = git_service.pull_from(username, doc_id, remote)
        return jsonify({"ok": ok, "error": err})

    @app.route("/api/sync/push/<remote>", methods=["POST"])
    @require_auth
    def sync_push_remote(remote):
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        ok, err = git_service.push_to(username, doc_id, remote)
        return jsonify({"ok": ok, "error": err})

    @app.route("/api/sync/conflicts", methods=["GET"])
    @require_auth
    def sync_conflicts():
        username = g.username
        doc_id = request.args.get("doc_id", "")
        if not doc_id:
            return jsonify([])
        return jsonify(git_service.unmerged_files(username, doc_id))

    @app.route("/api/sync/remote", methods=["GET"])
    @require_auth
    def sync_remotes():
        username = g.username
        doc_id = request.args.get("doc_id", "")
        if not doc_id:
            return jsonify([])
        return jsonify(git_service.remote_list(username, doc_id))

    @app.route("/api/sync/remote", methods=["POST"])
    @require_auth
    def sync_add_remote():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        name = data.get("name", "origin")
        url = data.get("url")
        if not doc_id or not url:
            return jsonify({"error": "doc_id and url required"}), 400
        repo_path = git_service._repo_path(username, doc_id)
        code, out, err = git_service._git(repo_path, "remote", "add", name, url)
        if code != 0:
            return jsonify({"error": err}), 400
        return jsonify({"ok": True, "name": name, "url": url})

    @app.route("/api/sync/remote/<name>", methods=["DELETE"])
    @require_auth
    def sync_remove_remote(name):
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        repo_path = git_service._repo_path(username, doc_id)
        code, out, err = git_service._git(repo_path, "remote", "remove", name)
        return jsonify({"ok": code == 0})

    # ── /api/stats ──────────────────────────────────────────────
    # Stats persistence: JSON files under data/stats/<username>.json
    # Schema per entry: {date, words_added, push_count, sync_count, login_count}

    def _stats_path(username):
        import json as _json
        p = os.path.join(app.config["DATA_DIR"], "stats")
        os.makedirs(p, exist_ok=True)
        return os.path.join(p, f"{username}.json")

    def _load_stats(username):
        p = _stats_path(username)
        if not os.path.exists(p):
            return []
        try:
            with open(p, "r", encoding="utf-8") as f:
                return _json.load(f)
        except (_json.JSONDecodeError, OSError):
            return []

    def _save_stats(username, entries):
        p = _stats_path(username)
        with open(p, "w", encoding="utf-8") as f:
            _json.dump(entries, f, ensure_ascii=False, indent=2)

    def _report_sync_stat(username, field, delta):
        """Increment a stats counter for today."""
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            entries = _load_stats(username)
            found = False
            for e in entries:
                if e.get("date") == today_str:
                    e[field] = e.get(field, 0) + delta
                    found = True
                    break
            if not found:
                entries.append({"date": today_str, "words_added": 0, "push_count": 0, "sync_count": 0, "login_count": 0})
                entries[-1][field] = delta
            _save_stats(username, entries)
        except Exception:
            pass  # non-fatal

    @app.route("/api/stats/report", methods=["POST"])
    def stats_report():
        """Log a daily stats entry. Accepts auth token or no-auth (for ESP-32)."""
        data = request.get_json() or {}
        username = g.username if hasattr(g, 'username') and g.username else None
        date_str = data.get("date")
        if not date_str:
            return jsonify({"error": "date required"}), 400
        # Validate date format YYYY-MM-DD
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "invalid date format, use YYYY-MM-DD"}), 400
        if username is None:
            # No-auth call (e.g. from ESP-32): store under a default user or reject
            username = data.get("username", "guest")
        entries = _load_stats(username)
        # Find or create entry for this date
        found = False
        for e in entries:
            if e.get("date") == date_str:
                e["words_added"] = e.get("words_added", 0) + data.get("words_added", 0)
                e["push_count"] = e.get("push_count", 0) + data.get("push_count", 0)
                e["sync_count"] = e.get("sync_count", 0) + data.get("sync_count", 0)
                e["login_count"] = e.get("login_count", 0) + data.get("login_count", 0)
                found = True
                break
        if not found:
            entries.append({
                "date": date_str,
                "words_added": data.get("words_added", 0),
                "push_count": data.get("push_count", 0),
                "sync_count": data.get("sync_count", 0),
                "login_count": data.get("login_count", 0),
            })
        _save_stats(username, entries)
        return jsonify({"ok": True})

    @app.route("/api/stats", methods=["GET"])
    @require_auth
    def stats_list():
        """Return daily stats for the current user over the last N days."""
        username = g.username
        days = int(request.args.get("days", 365))
        entries = _load_stats(username)
        if not entries:
            return jsonify({"stats": []})
        from datetime import date as _date
        today = _date.today()
        cutoff = (today - timedelta(days=days)).isoformat()
        recent = [e for e in entries if e.get("date", "") >= cutoff]
        recent.sort(key=lambda e: e.get("date", ""), reverse=True)
        return jsonify({"stats": recent})

    @app.route("/api/stats/summary", methods=["GET"])
    @require_auth
    def stats_summary():
        """Return aggregated summary: totals and today's counts."""
        username = g.username
        entries = _load_stats(username)
        total_words = sum(e.get("words_added", 0) for e in entries)
        total_pushes = sum(e.get("push_count", 0) for e in entries)
        total_syncs = sum(e.get("sync_count", 0) for e in entries)
        total_logins = sum(e.get("login_count", 0) for e in entries)
        from datetime import date as _date
        today = _date.today().isoformat()
        today_entry = next((e for e in entries if e.get("date") == today), {})
        return jsonify({
            "total_words": total_words,
            "today_words": today_entry.get("words_added", 0),
            "total_pushes": total_pushes,
            "total_syncs": total_syncs,
            "total_logins": total_logins,
            "streak_days": 0,  # placeholder: compute consecutive days if needed
        })

    @app.route("/api/esp/sync", methods=["GET"])
    def esp_sync():
        """Public endpoint for ESP-32 to poll latest stats (no auth)."""
        # Use a shared namespace or the first available user's stats
        # For simplicity, aggregate across all users or require a device ID
        username = request.args.get("username", "")
        if not username:
            return jsonify({"error": "username required"}), 400
        entries = _load_stats(username)
        from datetime import date as _date
        today = _date.today().isoformat()
        today_entry = next((e for e in entries if e.get("date") == today), {})
        total_words = sum(e.get("words_added", 0) for e in entries)
        return jsonify({
            "words_today": today_entry.get("words_added", 0),
            "words_total": total_words,
            "last_updated": today,
        })

    # ── /api/git ─────────────────────────────────────────────

    @app.route("/api/git/config", methods=["GET"])
    @require_auth
    def git_config_get():
        username = g.username
        doc_id = request.args.get("doc_id", "")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        return jsonify(git_service.get_config(username, doc_id))

    @app.route("/api/git/config", methods=["POST"])
    @require_auth
    def git_config_set():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        ok = git_service.set_config(username, doc_id, data.get("name"), data.get("email"))
        return jsonify({"ok": ok})

    @app.route("/api/git/branches", methods=["GET"])
    @require_auth
    def git_branches():
        username = g.username
        doc_id = request.args.get("doc_id", "")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        return jsonify(git_service.branches(username, doc_id))

    @app.route("/api/git/branch", methods=["POST"])
    @require_auth
    def git_branch_op():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        name = data.get("name", "").strip()
        action = data.get("action", "switch")
        if not doc_id or not name:
            return jsonify({"error": "doc_id and name required"}), 400
        ok, err = git_service.checkout(username, doc_id, name, create=(action == "create"))
        return jsonify({"ok": ok, "error": err})

    @app.route("/api/git/merge", methods=["POST"])
    @require_auth
    def git_merge():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        branch = data.get("branch", "")
        if not doc_id or not branch:
            return jsonify({"error": "doc_id and branch required"}), 400
        ok, err = git_service.merge(username, doc_id, branch)
        return jsonify({"ok": ok, "error": err})

    @app.route("/api/git/reset", methods=["POST"])
    @require_auth
    def git_reset():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        sha = data.get("sha", "")
        if not doc_id or not sha:
            return jsonify({"error": "doc_id and sha required"}), 400
        ok, err = git_service.reset_hard(username, doc_id, sha)
        return jsonify({"ok": ok, "error": err})

    # ── /api/access ────────────────────────────────────────────
    # 远程访问配置（仅局域网可用，公网需额外配置防火墙）

    def _remote_access_path():
        return os.path.join(app.config["DATA_DIR"], "remote_access.json")

    def _load_remote_access():
        p = _remote_access_path()
        if not os.path.exists(p):
            return {"enabled": False, "allowed_ips": [], "access_code": "", "auth_code": ""}
        import json as _json
        try:
            with open(p, encoding="utf-8") as f:
                cfg = _json.load(f)
        except Exception:
            cfg = {}
        # v0.4.0：访问码（登录用）与认证口令（二次认证用）拆分，旧配置补默认值
        cfg.setdefault("enabled", False)
        cfg.setdefault("allowed_ips", [])
        cfg.setdefault("access_code", "")
        cfg.setdefault("auth_code", "")
        return cfg

    def _save_remote_access(cfg):
        import json as _json
        with open(_remote_access_path(), "w", encoding="utf-8") as f:
            _json.dump(cfg, f, ensure_ascii=False)

    _LOCAL_HEADERS = (
        "http://127.0.0.1", "http://localhost", "http://[::1]",
        "https://127.0.0.1", "https://localhost", "https://[::1]",
    )

    def _is_local_request():
        """本地请求判定（DESIGN 4.5.1）：来源 IP 为回环，或 Origin/Referer 指向本地，任一命中即本地。
        仅凭 Origin/Referer 判断不可靠——浏览器顶级导航 GET（地址栏/书签/start 命令）不携带这些头。"""
        if request.remote_addr in ("127.0.0.1", "::1", "localhost"):
            return True
        origin = request.headers.get("Origin", "")
        referer = request.headers.get("Referer", "")
        return (any(h in origin for h in _LOCAL_HEADERS)
                or any(h in referer for h in _LOCAL_HEADERS))

    def _get_lan_ip():
        """局域网 IP：UDP connect 路由探测（不实际发包，DESIGN 4.5.3）；
        失败回退主机名解析，再回退 127.0.0.1。不用 gethostbyname(hostname)——
        WSL 等环境主机名会解析到 127.0.1.1 等回环地址。"""
        import socket as _socket
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
            finally:
                s.close()
        except Exception:
            try:
                return _socket.gethostbyname(_socket.gethostname())
            except Exception:
                return "127.0.0.1"

    # ── 远程访问访问控制：关闭时仅允许本地请求 ───────────────────
    @app.before_request
    def _check_remote_access():
        """远程访问关闭时，拒绝非本地来源的请求（返回 403）"""
        cfg = _load_remote_access()
        if not cfg.get("enabled", False):
            # 允许公开接口（不检查来源）
            if request.endpoint == 'public_config':
                return None
            if not _is_local_request():
                return jsonify({"error": "远程访问已关闭，仅允许本地访问"}), 403
        return None

    @app.route("/api/auth/password", methods=["POST"])
    @require_auth
    def auth_password():
        data = request.get_json() or {}
        users = _load_users()
        user = users.get(g.username)
        if not user:
            return jsonify({"error": "用户不存在"}), 404
        old_pw = data.get("old_password", "")
        new_pw = data.get("new_password", "")
        if not bcrypt.checkpw(old_pw.encode(), user["password_hash"].encode()):
            return jsonify({"error": "旧密码错误"}), 401
        if len(new_pw) < 8:
            return jsonify({"error": "新密码长度至少 8 位"}), 400
        users[g.username]["password_hash"] = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
        users[g.username]["token_version"] = users[g.username].get("token_version", 1) + 1
        _save_users(users)
        return jsonify({"ok": True})

    @app.route("/api/auth/refresh", methods=["POST"])
    @require_auth
    def auth_refresh():
        user = _load_users().get(g.username)
        if not user:
            return jsonify({"error": "用户不存在"}), 404
        expire = datetime.now(timezone.utc) + timedelta(days=30)
        token = jwt.encode({"sub": g.username, "exp": expire, "ver": user.get("token_version", 1)}, app.config["JWT_SECRET"], algorithm="HS256")
        return jsonify({"token": token})

    @app.route("/api/access/status", methods=["GET"])
    @require_auth
    def access_status():
        cfg = _load_remote_access()
        ip = _get_lan_ip()
        return jsonify({
            "enabled": cfg.get("enabled", False),
            "access_code": cfg.get("access_code", ""),
            "local_ip": ip,
            "allowed_ips": cfg.get("allowed_ips", []),
            "url": f"http://{ip}:{app.config['PORT']}",
            "auth2_enabled": cfg.get("auth2_enabled", True),
            "has_auth_code": bool(cfg.get("auth_code")),
        })

    @app.route("/api/access/enable", methods=["POST"])
    @require_auth
    def access_enable():
        data = request.get_json() or {}
        cfg = _load_remote_access()
        # 二次认证校验（默认开启）：校验用户自定义认证口令（DESIGN 4.5.1）
        if cfg.get("auth2_enabled", True):
            if not cfg.get("auth_code"):
                return jsonify({"error": "请先设置认证口令（设置页 > 网络和安全）"}), 401
            auth_code = data.get("auth_code", "")
            if auth_code != cfg.get("auth_code", ""):
                return jsonify({"error": "认证口令错误"}), 401
        cfg["enabled"] = True
        # 仅重新生成登录访问码；认证口令独立存储，不受开启操作影响
        import random as _random, string as _string
        cfg["access_code"] = "".join(_random.choices(_string.ascii_letters + _string.digits, k=6))
        if "allowed_ips" in data:
            cfg["allowed_ips"] = data["allowed_ips"]
        _save_remote_access(cfg)
        return jsonify({
            "ok": True,
            "url": f"http://{_get_lan_ip()}:{app.config['PORT']}",
            "access_code": cfg["access_code"],
        })

    @app.route("/api/access/disable", methods=["POST"])
    @require_auth
    def access_disable():
        data = request.get_json() or {}
        cfg = _load_remote_access()
        # 二次认证校验（默认开启）：校验用户自定义认证口令
        if cfg.get("auth2_enabled", True):
            if not cfg.get("auth_code"):
                return jsonify({"error": "请先设置认证口令（设置页 > 网络和安全）"}), 401
            auth_code = data.get("auth_code", "")
            if auth_code != cfg.get("auth_code", ""):
                return jsonify({"error": "认证口令错误"}), 401
        cfg["enabled"] = False
        cfg["access_code"] = ""
        _save_remote_access(cfg)
        return jsonify({"ok": True})

    @app.route("/api/access/clients", methods=["GET"])
    @require_auth
    def access_clients():
        # 返回当前连接的设备列表（简化版：仅返回IP）
        return jsonify([])

    @app.route("/api/access/code", methods=["POST"])
    @require_auth
    def access_verify_code():
        data = request.get_json() or {}
        cfg = _load_remote_access()
        if not cfg.get("enabled"):
            return jsonify({"error": "远程访问未开启"}), 403
        if data.get("code") == cfg.get("access_code"):
            return jsonify({"ok": True})
        return jsonify({"error": "访问码错误"}), 401

    @app.route("/api/access/auth-code", methods=["PUT"])
    @require_auth
    def access_update_auth_code():
        data = request.get_json() or {}
        cfg = _load_remote_access()
        old_code = data.get("old_code", "")
        new_code = data.get("new_code", "")
        # 从未设置过口令（auth_code 为空）时免验旧口令，允许首次设置（DESIGN 4.5.1）
        if cfg.get("auth2_enabled", True) and cfg.get("auth_code"):
            if old_code != cfg.get("auth_code", ""):
                return jsonify({"error": "旧口令错误"}), 401
        if not new_code or len(new_code) < 4:
            return jsonify({"error": "口令长度至少 4 位"}), 400
        cfg["auth_code"] = new_code
        _save_remote_access(cfg)
        return jsonify({"ok": True})

    @app.route("/api/access/auth2-toggle", methods=["POST"])
    @require_auth
    def access_auth2_toggle():
        data = request.get_json() or {}
        cfg = _load_remote_access()
        cfg["auth2_enabled"] = bool(data.get("enabled", True))
        _save_remote_access(cfg)
        return jsonify({"ok": True})

    # ── /api/backup ─────────────────────────────────────────────
    # SMB/NAS backup support via pysmb
    # Config stored in data/backup_config.json (relative to DATA_DIR)

    def _backup_config_path():
        return os.path.join(app.config["DATA_DIR"], "backup_config.json")

    def _load_backup_config():
        p = _backup_config_path()
        if not os.path.exists(p):
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                import json
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_backup_config(cfg):
        p = _backup_config_path()
        with open(p, "w", encoding="utf-8") as f:
            import json
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    @app.route("/api/backup/smb", methods=["GET"])
    @require_auth
    def backup_smb_get():
        """Return SMB config without password."""
        cfg = _load_backup_config()
        return jsonify({
            "host": cfg.get("host", ""),
            "share": cfg.get("share", ""),
            "username": cfg.get("username", ""),
            "configured": bool(cfg.get("host")),
        })

    @app.route("/api/backup/smb", methods=["POST"])
    @require_auth
    def backup_smb_set():
        """Save SMB configuration."""
        username = g.username
        data = request.get_json() or {}
        host = data.get("host", "").strip()
        share = data.get("share", "").strip()
        smb_user = data.get("username", "").strip()
        password = data.get("password", "")
        if not host or not share:
            return jsonify({"error": "host and share required"}), 400
        cfg = {"host": host, "share": share, "username": smb_user, "password": password}
        _save_backup_config(cfg)
        return jsonify({"ok": True})

    @app.route("/api/backup/run", methods=["POST"])
    @require_auth
    def backup_run():
        """Trigger immediate backup: tar.gz + upload to SMB share."""
        username = g.username
        cfg = _load_backup_config()
        if not cfg.get("host"):
            return jsonify({"error": "SMB not configured"}), 400

        try:
            from datetime import datetime as _dt
            timestamp = _dt.now().strftime("%Y%m%d-%H%M%S")
            backup_name = f"ve-backup-{timestamp}.tar.gz"
            data_dir = app.config["DATA_DIR"]
            tar_path = os.path.join(data_dir, f".backup_{timestamp}.tar.gz")

            # Create tar.gz of data directory
            import tarfile
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(data_dir, arcname="data")

            # Upload via SMB
            from smb.SMBConnection import SMBConnection
            server = cfg["host"].rstrip("/")
            share = cfg["share"].lstrip("/")
            smb_user = cfg.get("username", "")
            smb_pass = cfg.get("password", "")
            conn = SMBConnection(smb_user, smb_pass, "vanilla-editor", server, use_ntlm_v2=True)
            if not conn.connect(server, 445):
                os.remove(tar_path)
                return jsonify({"error": "Could not connect to SMB server"}), 500

            with open(tar_path, "rb") as f:
                conn.storeFile(share, f"/{backup_name}", f)
            conn.close()
            os.remove(tar_path)

            return jsonify({"ok": True, "filename": backup_name})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── /api/workspaces ────────────────────────────────────────
    # 工作区配置保存在 <repo_path>/.ve/ve_workspace.json（原地模式）
    # 历史兼容：旧版使用 .ve_workspace 单文件，会自动迁移到新格式

    def _workspace_config_path(repo_path):
        return os.path.join(repo_path, ".ve", "ve_workspace.json")

    def _legacy_workspace_config_path(repo_path):
        return os.path.join(repo_path, ".ve_workspace")

    def _read_workspace_config(repo_path):
        p = _workspace_config_path(repo_path)
        if os.path.isfile(p):
            try:
                import json as _json
                with open(p, encoding="utf-8") as f:
                    return _json.load(f)
            except Exception:
                pass
        # 兼容旧格式 .ve_workspace
        legacy = _legacy_workspace_config_path(repo_path)
        if os.path.isfile(legacy):
            try:
                import json as _json
                cfg = _json.load(open(legacy, encoding="utf-8"))
                _migrate_workspace_config(repo_path, cfg)
                return cfg
            except Exception:
                pass
        return {"name": repo_path.split(os.sep)[-1], "source_path": ""}

    def _migrate_workspace_config(repo_path, cfg):
        """将旧的 .ve_workspace 迁移到 .ve/ve_workspace.json"""
        os.makedirs(os.path.join(repo_path, ".ve"), exist_ok=True)
        import json as _json
        with open(_workspace_config_path(repo_path), "w", encoding="utf-8") as f:
            _json.dump(cfg, f, ensure_ascii=False)

    def _migrate_legacy_workspaces(username):
        """惰性迁移：把旧复制模式留下的 data/<user>/ws_*/.ve/ve_workspace.json
        注册进 workspaces.json（原地模式注册表）。旧副本目录保留不动，避免误删数据。"""
        user_dir = os.path.join(app.config["DATA_DIR"], username)
        if not os.path.isdir(user_dir):
            return
        reg = git_service.load_registry(username)
        changed = False
        for item in os.listdir(user_dir):
            item_path = os.path.join(user_dir, item)
            if not item.startswith("ws_") or not os.path.isdir(item_path):
                continue
            if item in reg:
                continue
            cfg = _read_workspace_config(item_path)
            src = cfg.get("source_path", "")
            if src and os.path.isdir(src):
                reg[item] = {
                    "name": cfg.get("name", item),
                    "source_path": src,
                    "migrated_from": item_path,
                }
                changed = True
        if changed:
            git_service.save_registry(username, reg)

    @app.route("/api/workspaces", methods=["GET"])
    @require_auth
    def workspaces_list():
        username = g.username
        _migrate_legacy_workspaces(username)
        reg = git_service.load_registry(username)
        workspaces = []
        for item in sorted(reg.keys()):
            entry = reg[item]
            src = entry.get("source_path", "")
            workspaces.append({
                "id": item,
                "name": entry.get("name", item),
                "source_path": src,
                "type": "workspace",
                "available": os.path.isdir(src),
            })
        return jsonify(workspaces)

    @app.route("/api/workspaces", methods=["POST"])
    @require_auth
    def workspace_open():
        """原地模式（DESIGN 4.3.1）：直接在用户选定目录工作，
        已含 .git 则复用、否则在其中 git init；不复制任何数据到 data/。"""
        username = g.username
        data = request.get_json() or {}
        source_path = os.path.normpath(data.get("path", ""))
        if not source_path or not os.path.isdir(source_path):
            return jsonify({"error": "目录不存在"}), 400
        real = os.path.realpath(source_path)
        # data/ 自身不允许作为工作区（防止注册表/用户数据被当作工作区内容提交）
        data_real = os.path.realpath(app.config["DATA_DIR"])
        if real == data_real or real.startswith(data_real + os.sep):
            return jsonify({"error": "不能将 VE 数据目录本身作为工作区"}), 400
        doc_id = "ws_" + real.replace(os.sep, "_").replace(":", "_").replace(" ", "_").lower()
        # 在源目录内初始化/复用 Git 仓库（原地模式核心）
        git_service.save_registry(username, {**git_service.load_registry(username),
                                             doc_id: {"name": os.path.basename(real), "source_path": real}})
        git_service.ensure_repo(username, doc_id)
        # 写入工作区配置 .ve/ve_workspace.json（幂等：已存在则保留 UI 状态）
        import json as _json
        cfg_path = _workspace_config_path(real)
        if os.path.isfile(cfg_path):
            try:
                ws_cfg = _json.load(open(cfg_path, encoding="utf-8"))
            except Exception:
                ws_cfg = {}
        else:
            ws_cfg = {"ui": {}}
        ws_cfg.update({
            "name": os.path.basename(real),
            "source_path": real,
            "opened_by": username,
            "opened_at": ws_cfg.get("opened_at") or datetime.now(timezone.utc).isoformat(),
        })
        os.makedirs(os.path.join(real, ".ve"), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as f:
            _json.dump(ws_cfg, f, ensure_ascii=False, indent=2)
        # 历史兼容：源目录残留旧 .ve_workspace 单文件则迁移
        legacy = _legacy_workspace_config_path(real)
        if os.path.isfile(legacy):
            try:
                _migrate_workspace_config(real, _json.load(open(legacy, encoding="utf-8")))
                os.remove(legacy)
            except Exception:
                pass
        return jsonify({"id": doc_id, "name": os.path.basename(real), "source_path": real}), 201

    @app.route("/api/workspaces/<doc_id>", methods=["DELETE"])
    @require_auth
    def workspace_close(doc_id):
        """关闭工作区（DESIGN 4.3.3）：有未提交更改先自动 commit，
        然后仅删除注册记录与源目录中的 .ve 配置——绝不删除源目录本身。"""
        username = g.username
        reg = git_service.load_registry(username)
        entry = reg.get(doc_id)
        # 未提交更改先自动保存
        try:
            changed = git_service.status(username, doc_id)
            if changed:
                git_service.add_all(username, doc_id)
                git_service.commit(username, doc_id, "save before close")
        except Exception:
            pass
        # 删除源目录中的 .ve 配置（原地模式）
        if entry and entry.get("source_path"):
            ve_dir = os.path.join(entry["source_path"], ".ve")
            if os.path.isdir(ve_dir):
                try:
                    _force_rmtree(ve_dir)
                except OSError:
                    pass
        # 仅删除注册记录，源目录与其 .git 保持原样
        reg.pop(doc_id, None)
        git_service.save_registry(username, reg)
        return jsonify({"ok": True})

    @app.route("/api/workspace/save", methods=["POST"])
    @require_auth
    def workspace_save_state():
        """前端调用：保存工作区的 UI 状态（标签页、展开状态、布局、字号等）"""
        data = request.get_json() or {}
        doc_id = data.get("doc_id")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        username = g.username
        repo_path = git_service._repo_path(username, doc_id)
        cfg = _read_workspace_config(repo_path)
        cfg["ui"] = {
            "tabs": data.get("tabs", []),
            "activeTabId": data.get("activeTabId", ""),
            "expandedWorkspaces": data.get("expandedWorkspaces", {}),
            "expandedDocs": data.get("expandedDocs", {}),
            "sidebarW": data.get("sidebarW", 280),
            "editorPct": data.get("editorPct", 50),
            "layoutMode": data.get("layoutMode", "default"),
            "fontSize": data.get("fontSize", 14),
            "mobilePreview": data.get("mobilePreview", False),
            "autoSync": data.get("autoSync", False),
            "lastSavedAt": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.join(repo_path, ".ve"), exist_ok=True)
        import json as _json
        with open(_workspace_config_path(repo_path), "w", encoding="utf-8") as f:
            _json.dump(cfg, f, ensure_ascii=False, indent=2)
        # 同时 git add + commit 让状态变更可追溯
        git_service.write_file(username, doc_id, ".ve/ve_workspace.json",
                               _json.dumps(cfg, ensure_ascii=False, indent=2))
        git_service.add_all(username, doc_id)
        git_service.commit(username, doc_id, f"save workspace state: {cfg.get('name', doc_id)}")
        return jsonify({"ok": True})

    @app.route("/api/workspace/state", methods=["GET"])
    @require_auth
    def workspace_load_state():
        """前端调用：加载工作区的 UI 状态"""
        doc_id = request.args.get("doc_id", "")
        if not doc_id:
            return jsonify({"error": "doc_id required"}), 400
        username = g.username
        repo_path = git_service._repo_path(username, doc_id)
        cfg = _read_workspace_config(repo_path)
        ui = cfg.get("ui", {})
        return jsonify(ui)

    @app.route("/api/workspaces/scan", methods=["POST"])
    @require_auth
    def workspace_scan():
        data = request.get_json() or {}
        path = os.path.normpath(data.get("path", ""))
        if not path or not os.path.isdir(path):
            return jsonify({"error": "目录不存在"}), 400
        skip_dirs = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv", ".vscode", ".idea"}
        result = []
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted([d for d in dirs if d not in skip_dirs])
            rel = os.path.relpath(root, path)
            for fn in sorted(files):
                full_rel = os.path.join(rel, fn) if rel != "." else fn
                result.append({"path": full_rel.replace(os.sep, "/"), "name": fn, "size": os.path.getsize(os.path.join(root, fn))})
        return jsonify({"path": path, "files": result})

    @app.route("/api/fs/children", methods=["POST"])
    @require_auth
    def fs_children():
        data = request.get_json() or {}
        path = os.path.normpath(data.get("path", ""))
        if not path or not os.path.isdir(path):
            return jsonify({"error": "目录不存在"}), 400
        skip_dirs = {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
        real = os.path.realpath(path)
        result = {"path": path, "dirs": [], "files": []}
        try:
            entries = sorted(os.listdir(path), key=lambda x: x.lower())
            for entry in entries:
                full = os.path.join(path, entry)
                if os.path.isdir(full):
                    if entry not in skip_dirs and not entry.startswith('.'):
                        result["dirs"].append({"name": entry, "path": full.replace(os.sep, "/")})
                elif os.path.isfile(full):
                    result["files"].append({"name": entry, "path": full.replace(os.sep, "/"), "size": os.path.getsize(full)})
        except PermissionError:
            return jsonify({"error": "无权限访问该目录"}), 403
        return jsonify(result)

    # ── front-end fallback ────────────────────────────────────

    @app.route("/")
    def index():
        return app.send_static_file("index.html")

    return app, git_service


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from app import create_app as _ca
    app, git = _ca()
    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    port = pick_port(app.config["HOST"])
    print(f"VanillaEditor on http://{app.config['HOST']}:{port}")
    app.run(host=app.config["HOST"], port=port, debug=True)
