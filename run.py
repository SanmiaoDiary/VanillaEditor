import os

from app.routes import create_app, pick_port

app, git_service = create_app()

if __name__ == "__main__":
    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    host = app.config["HOST"]
    port = pick_port(host)
    print(f"VanillaEditor on http://{host}:{port}")
    app.run(host=host, port=port, debug=True)
