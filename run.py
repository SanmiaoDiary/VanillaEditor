from app.routes import create_app
import os

app, git_service = create_app()

if __name__ == "__main__":
    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    print(f"VanillaEditor on http://{app.config['HOST']}:{app.config['PORT']}")
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=True)
