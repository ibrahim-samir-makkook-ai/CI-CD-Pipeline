from flask import Flask, Response, jsonify

app: Flask = Flask(__name__)


def add(a: int, b: int) -> int:
    """Simple utility function for demo/test purposes."""
    return a + b


@app.route("/")
def home() -> tuple[Response, int]:
    return jsonify(message="Hello, CI/CD Pipeline!"), 200


@app.route("/health")
def health() -> tuple[Response, int]:
    return jsonify(status="ok"), 200


@app.route("/add/<int:a>/<int:b>")
def add_route(a: int, b: int) -> tuple[Response, int]:
    result: int = add(a, b)
    return jsonify(a=a, b=b, result=result), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
