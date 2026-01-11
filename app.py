from flask import Flask, request, jsonify, send_from_directory
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import os, json

app = Flask(__name__, static_folder="static", static_url_path="/static")

DATA_FILE = "data.json"
contributions = defaultdict(Decimal)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

TEST_TOKEN = os.environ.get("TEST_TOKEN")

ADMIN_RESET_TOKEN = os.environ.get("ADMIN_RESET_TOKEN")

MAX_PER_SUBMISSION = Decimal("5.00")

total_received = Decimal("0.00")

@app.route("/admin/reset", methods=["POST"])
def reset_leaderboard():
    if not ADMIN_RESET_TOKEN:
        return jsonify({"error": "Reset not configured"}), 500

    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_RESET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
        
    global total_received
    total_received = Decimal("0.00")

    contributions.clear()
    save_data()
    return jsonify({"ok": True, "message": "Leaderboard reset"})


def load_data():
    """Load saved totals from disk into memory."""
    global total_received

    if not os.path.exists(DATA_FILE):
        return

    try:
        with open(DATA_FILE, "r") as f:
            raw = json.load(f)

        # Backward compatibility: old format was just { "Sarah": 9.0, ... }
        if "contributions" not in raw:
            for name, total in raw.items():
                contributions[name] = Decimal(str(total))
            total_received = Decimal("0.00")
            return

        # New format
        for name, total in raw.get("contributions", {}).items():
            contributions[name] = Decimal(str(total))

        total_received = Decimal(str(raw.get("total_received", 0)))

    except Exception as e:
        print("Failed loading leaderboard data:", e)


def save_data():
    """Persist current totals to disk."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({
                "contributions": {k: float(v) for k, v in contributions.items()},
                "total_received": float(total_received)
            }, f)
    except Exception as e:
        print("Failed saving leaderboard data:", e)



def normalize_label(note: str) -> str:
    # normalize names consistently
    label = note.strip()
    return label


# load stored totals on startup
load_data()

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

@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify({
        "total_received": float(total_received)
    })



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

submitted_amount = amount

total_received += submitted_amount

counted_amount = min(submitted_amount, MAX_PER_SUBMISSION)
contributions[label] += counted_amount
save_data()
    
    # Cap per submission
    amount = min(amount, MAX_PER_SUBMISSION)
    contributions[label] += amount
    save_data()

        return jsonify({
    "ok": True,
    "label": label,
    "submitted_amount": float(submitted_amount),
    "counted_amount": float(counted_amount),
    "new_total": float(contributions[label]),
    "total_received": float(total_received)
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

@app.route("/admin/test-payment", methods=["POST"])
def admin_test_payment():
    if not TEST_TOKEN:
        return jsonify({"error": "Test endpoint not configured"}), 500

    token = request.headers.get("X-Test-Token")
    if token != TEST_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True, silent=True)
    if not data or "amount" not in data or "message" not in data:
        return jsonify({"error": "Fields 'amount' and 'message' are required"}), 400

    try:
        amount = Decimal(str(data["amount"]))
    except (InvalidOperation, TypeError):
        return jsonify({"error": "Invalid 'amount'"}), 400

    amount = min(amount, MAX_PER_SUBMISSION)

    label = normalize_label(str(data["message"]))
    if not label:
        return jsonify({"error": "Empty or invalid 'message'"}), 400
        
    # Cap per submission
    amount = min(amount, MAX_PER_SUBMISSION)
    contributions[label] += amount
    save_data()

    return jsonify({"ok": True, "label": label, "new_total": float(contributions[label])})

