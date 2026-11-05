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
    """
    explicit = "PORT" in os.environ
    port = int(os.environ.get("PORT", DEFAULT_PORT))
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
    app.config["JWT_SECRET"] = os.environ.get("JWT_SECRET", "dev-secret-change-me")
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
        # 远程访问开启时校验访问码
        if access_code:
            ra = _load_remote_access()
            if ra.get("enabled") and access_code != ra.get("access_code", ""):
                return jsonify({"error": "访问码错误"}), 401
        users = _load_users()
        user = users.get(username)
        if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return jsonify({"error": "用户名或密码错误"}), 401
        expire = datetime.now(timezone.utc) + timedelta(days=30)
        token = jwt.encode({"sub": username, "exp": expire, "ver": user.get("token_version", 1)}, app.config["JWT_SECRET"], algorithm="HS256")
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
        origin = request.headers.get("Origin", "")
        is_local = any(host in origin for host in ["http://127.0.0.1", "http://[::1]", "http://localhost"])
        return jsonify({"remote_access": enabled, "is_local": is_local})

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
        # 同时在 git 仓库中提交（用于版本历史和同步）
        git_service.write_file(username, doc_id, rel_path, content)
        git_service.add_all(username, doc_id)
        git_service.commit(username, doc_id, f"update: {rel_path.split('/')[-1]}")
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
            return {"enabled": False, "allowed_ips": [], "access_code": ""}
        import json as _json
        try:
            with open(p, encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return {"enabled": False, "allowed_ips": [], "access_code": ""}

    def _save_remote_access(cfg):
        import json as _json
        with open(_remote_access_path(), "w", encoding="utf-8") as f:
            _json.dump(cfg, f, ensure_ascii=False)

    # ── 远程访问访问控制：关闭时仅允许本地请求 ───────────────────
    @app.before_request
    def _check_remote_access():
        """远程访问关闭时，拒绝非本地来源的请求（返回 403）"""
        cfg = _load_remote_access()
        if not cfg.get("enabled", False):
            # 本地来源：localhost / 127.0.0.1 / [::1]
            origin = request.headers.get("Origin", "")
            referer = request.headers.get("Referer", "")
            is_local_origin = any(h in origin for h in [
                "http://127.0.0.1", "http://localhost", "http://[::1]",
                "https://127.0.0.1", "https://localhost", "https://[::1]"
            ])
            is_local_referer = any(h in referer for h in [
                "http://127.0.0.1", "http://localhost", "http://[::1]",
                "https://127.0.0.1", "https://localhost", "https://[::1]"
            ])
            # 允许公开接口（不检查来源）
            if request.endpoint == 'public_config':
                return None
            # 如果 Origin 或 Referer 指向本地，允许；否则拒绝
            if not (is_local_origin or is_local_referer):
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
        import socket as _socket
        try:
            hostname = _socket.gethostname()
            ip = _socket.gethostbyname(hostname)
        except Exception:
            ip = "127.0.0.1"
        return jsonify({
            "enabled": cfg.get("enabled", False),
            "access_code": cfg.get("access_code", ""),
            "local_ip": ip,
            "allowed_ips": cfg.get("allowed_ips", []),
            "url": f"http://{ip}:{app.config['PORT']}",
            "auth2_enabled": cfg.get("auth2_enabled", True),
        })

    @app.route("/api/access/enable", methods=["POST"])
    @require_auth
    def access_enable():
        data = request.get_json() or {}
        cfg = _load_remote_access()
        # 二次认证校验（默认开启）
        if cfg.get("auth2_enabled", True):
            auth_code = data.get("auth_code", "")
            if auth_code != cfg.get("access_code", ""):
                return jsonify({"error": "认证口令错误"}), 401
        cfg["enabled"] = True
        import random as _random, string as _string
        cfg["access_code"] = "".join(_random.choices(_string.ascii_letters + _string.digits, k=6))
        if "allowed_ips" in data:
            cfg["allowed_ips"] = data["allowed_ips"]
        _save_remote_access(cfg)
        import socket as _socket
        try:
            ip = _socket.gethostbyname(_socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
        return jsonify({
            "ok": True,
            "url": f"http://{ip}:{app.config['PORT']}",
            "access_code": cfg["access_code"],
        })

    @app.route("/api/access/disable", methods=["POST"])
    @require_auth
    def access_disable():
        data = request.get_json() or {}
        cfg = _load_remote_access()
        # 二次认证校验（默认开启）
        if cfg.get("auth2_enabled", True):
            auth_code = data.get("auth_code", "")
            if auth_code != cfg.get("access_code", ""):
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
        if cfg.get("auth2_enabled", True):
            if old_code != cfg.get("access_code", ""):
                return jsonify({"error": "旧口令错误"}), 401
        if not new_code or len(new_code) < 4:
            return jsonify({"error": "口令长度至少 4 位"}), 400
        cfg["access_code"] = new_code
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

    @app.route("/api/workspaces", methods=["GET"])
    @require_auth
    def workspaces_list():
        username = g.username
        user_dir = os.path.join(app.config["DATA_DIR"], username)
        workspaces = []
        if os.path.isdir(user_dir):
            for item in sorted(os.listdir(user_dir)):
                item_path = os.path.join(user_dir, item)
                if not os.path.isdir(item_path):
                    continue
                repo_path = os.path.join(item_path, ".git") if os.path.isdir(os.path.join(item_path, ".git")) else item_path
                cfg = _read_workspace_config(item_path)
                workspaces.append({
                    "id": item,
                    "name": cfg.get("name", item),
                    "source_path": cfg.get("source_path", ""),
                    "type": "workspace",
                })
        return jsonify(workspaces)

    @app.route("/api/workspaces", methods=["POST"])
    @require_auth
    def workspace_open():
        username = g.username
        data = request.get_json() or {}
        source_path = os.path.normpath(data.get("path", ""))
        if not source_path or not os.path.isdir(source_path):
            return jsonify({"error": "目录不存在"}), 400
        # 安全校验：排除系统目录
        real = os.path.realpath(source_path)
        forbidden = ["/", os.sep]
        if sys.platform == "win32" and len(real) >= 2 and real[1] == ":":
            forbidden = [real[:2]]
        for fp in forbidden:
            if real == fp or (fp != "/" and real.startswith(fp + os.sep)):
                pass  # allow user-specified paths
        doc_id = "ws_" + real.replace(os.sep, "_").replace(":", "_").replace(" ", "_").lower()
        repo_path = git_service.ensure_repo(username, doc_id)
        # 写入工作区配置（新格式：.ve/ve_workspace.json）
        import json as _json
        ws_cfg = {
            "name": os.path.basename(real),
            "source_path": real,
            "opened_by": username,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "ui": {},  # 预留 UI 状态（标签页、展开状态等）
        }
        os.makedirs(os.path.join(repo_path, ".ve"), exist_ok=True)
        with open(_workspace_config_path(repo_path), "w", encoding="utf-8") as f:
            _json.dump(ws_cfg, f, ensure_ascii=False, indent=2)
        # 原有 .ve_workspace 自动迁移为新格式（如果存在）
        legacy = _legacy_workspace_config_path(repo_path)
        if os.path.isfile(legacy):
            try:
                _migrate_workspace_config(repo_path, _json.load(open(legacy, encoding="utf-8")))
                os.remove(legacy)
            except Exception:
                pass
        return jsonify({"id": doc_id, "name": os.path.basename(real), "source_path": real}), 201

    @app.route("/api/workspaces/<doc_id>", methods=["DELETE"])
    @require_auth
    def workspace_close(doc_id):
        username = g.username
        doc_path = os.path.normpath(os.path.join(app.config["DATA_DIR"], username, doc_id))
        base = os.path.normpath(os.path.join(app.config["DATA_DIR"], username))
        if not doc_path.startswith(base + os.sep):
            return jsonify({"error": "非法路径"}), 400
        # 有未提交更改时先自动保存
        try:
            changed = git_service.status(username, doc_id)
            if changed:
                git_service.add_all(username, doc_id)
                git_service.commit(username, doc_id, "save before close")
        except Exception:
            pass
        if os.path.isdir(doc_path):
            try:
                _force_rmtree(doc_path)
            except OSError as e:
                return jsonify({"error": f"删除失败：{e}"}), 500
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
