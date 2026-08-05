from v2app import create_app
from scripts.upgrade_v2 import upgrade

app = create_app()

if __name__ == "__main__":
    upgrade()
    app.run(debug=False, port=5001)
