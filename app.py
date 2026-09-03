import os

from flask import Flask, Response, jsonify

app: Flask = Flask(__name__)


def add(a: int, b: int) -> int:
    """Simple utility function for demo/test purposes."""
    return a + b


@app.route("/")
def home() -> tuple[Response, int]:
    env = os.getenv("ENVIRONMENT", os.getenv("TAG", "")).lower()
    if env in ("staging", "stage"):
        msg = "hello from staging"
    elif env in ("production", "prod", "stable", "latest"):
        msg = "hello from production"
    else:
        msg = "Hello, CI/CD Pipeline! test"
    return jsonify(message=msg), 200


@app.route("/health")
def health() -> tuple[Response, int]:
    return jsonify(status="ok"), 200


@app.route("/add/<int:a>/<int:b>")
def add_route(a: int, b: int) -> tuple[Response, int]:
    result: int = add(a, b)
    return jsonify(a=a, b=b, result=result), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
