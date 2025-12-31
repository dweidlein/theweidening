from flask import Flask, request, jsonify, send_from_directory
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import os

app = Flask(__name__, static_folder="static", static_url_path="/static")

# In-memory store: { "Sarah": Decimal("9.00"), ... }
contributions = defaultdict(Decimal)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")


def normalize_label(note: str) -> str:
    """
    Map Venmo note → leaderboard label.
    For now: just strip whitespace.
    You can customize this if needed.
    """
    return note.strip()


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    leaderboard = sorted(
        [{"name": name, "total": float(total)} for name, total in contributions.items()],
        key=lambda x: x["total"],
        reverse=True
    )
    return jsonify(leaderboard)


@app.route("/api/payment", methods=["POST"])
def add_payment():
    # Optional shared-secret header
    if WEBHOOK_SECRET:
        token = request.headers.get("X-Webhook-Token")
        if token != WEBHOOK_SECRET:
            return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "amount" not in data or "message" not in data:
        return jsonify({"error": "Fields 'amount' and 'message' are required"}), 400

    try:
        amount = Decimal(str(data["amount"]))
    except (InvalidOperation, TypeError):
        return jsonify({"error": "Invalid 'amount'"}), 400

    label = normalize_label(str(data["message"]))
    if not label:
        return jsonify({"error": "Empty 'message' not allowed"}), 400

    contributions[label] += amount

    return jsonify({
        "ok": True,
        "label": label,
        "new_total": float(contributions[label])
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
