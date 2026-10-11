import os
from flask import Flask, request, jsonify, g
from functools import wraps
import jwt
from datetime import datetime, timezone, timedelta
import bcrypt

from app.git.service import GitService


def create_app():
    app = Flask(__name__, static_folder="../static", static_url_path="/")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(32))
    app.config["JWT_SECRET"] = os.environ.get("JWT_SECRET", "dev-secret-change-me")
    app.config["DATA_DIR"] = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
    app.config["PORT"] = int(os.environ.get("PORT", 5000))
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
        if not username or not password:
            return jsonify({"error": "用户名和密码不能为空"}), 400
        users = _load_users()
        user = users.get(username)
        if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return jsonify({"error": "用户名或密码错误"}), 401
        expire = datetime.now(timezone.utc) + timedelta(hours=24)
        token = jwt.encode({"sub": username, "exp": expire}, app.config["JWT_SECRET"], algorithm="HS256")
        return jsonify({"token": token, "username": username})

    @app.route("/api/auth/me", methods=["GET"])
    @require_auth
    def auth_me():
        return jsonify({"username": g.username})

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
        repo_path = git_service.ensure_repo(username, doc_id)
        git_service.write_file(username, doc_id, name, content)
        git_service.add_all(username, doc_id)
        git_service.commit(username, doc_id, f"init: {name}")
        return jsonify({"id": doc_id, "name": name, "path": name}), 201

    @app.route("/api/docs/<doc_id>", methods=["DELETE"])
    @require_auth
    def docs_delete(doc_id):
        username = g.username
        import shutil
        doc_path = os.path.join(app.config["DATA_DIR"], username, doc_id)
        if os.path.isdir(doc_path):
            shutil.rmtree(doc_path)
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
        git_service.write_file(username, doc_id, rel_path, content)
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

    @app.route("/api/sync/remote", methods=["GET"])
    @require_auth
    def sync_remotes():
        username = g.username
        data = request.get_json() or {}
        doc_id = data.get("doc_id", "")
        if not doc_id:
            return jsonify([])
        repo_path = git_service._repo_path(username, doc_id)
        code, out, _ = git_service._git(repo_path, "remote", "-v")
        remotes = []
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                remotes.append({"name": parts[0], "url": parts[1]})
        return jsonify(remotes)

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
    print(f"VanillaEditor on http://{app.config['HOST']}:{app.config['PORT']}")
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=True)
