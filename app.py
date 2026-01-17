from flask import Flask, request, jsonify, send_from_directory
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import os, json
import re

app = Flask(__name__, static_folder="static", static_url_path="/static")

DATA_FILE = "data.json"
contributions = defaultdict(Decimal)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
TEST_TOKEN = os.environ.get("TEST_TOKEN")
ADMIN_RESET_TOKEN = os.environ.get("ADMIN_RESET_TOKEN")

MAX_PER_SUBMISSION = Decimal("5.00")
total_received = Decimal("0.00")


def normalize_label(note: str) -> str:
    """
    Normalize Venmo note -> leaderboard key so capitalization/punctuation doesn't split entries.

    - trims whitespace
    - collapses internal whitespace
    - strips leading/trailing punctuation (commas, periods, etc.)
    - case-insensitive (casefold)
    """
    if note is None:
        return ""

    s = str(note).strip()

    # Collapse tabs/newlines/multiple spaces into single spaces
    s = re.sub(r"\s+", " ", s)

    # Strip common punctuation at the edges only:
    # "Daniel," -> "Daniel", "  (Daniel) " -> "Daniel"
    # Leaves inside punctuation alone, e.g. "O'Neil"
    s = re.sub(r"^[\s\.,;:!?\-–—_(){}\[\]\"'`]+", "", s)
    s = re.sub(r"[\s\.,;:!?\-–—_(){}\[\]\"'`]+$", "", s)

    # Case-insensitive key
    s = s.casefold()

    return s


def display_label(key: str) -> str:
    """
    Convert normalized key back into a nicer display label.
    Simple rule: title-case each word.
    """
    s = str(key or "").strip()
    if not s:
        return ""
    return " ".join(w.capitalize() for w in s.split())


def load_data():
    """Load saved totals from disk into memory, merging duplicates using normalization."""
    global total_received

    if not os.path.exists(DATA_FILE):
        return

    try:
        with open(DATA_FILE, "r") as f:
            raw = json.load(f)

        contributions.clear()

        # Backward compatibility: old format was just { "Sarah": 9.0, ... }
        if "contributions" not in raw:
            for name, total in raw.items():
                key = normalize_label(name)
                if not key:
                    continue
                contributions[key] += Decimal(str(total))
            total_received = Decimal("0.00")
            return

        # New format
        for name, total in raw.get("contributions", {}).items():
            key = normalize_label(name)
            if not key:
                continue
            contributions[key] += Decimal(str(total))

        total_received = Decimal(str(raw.get("total_received", 0)))

    except Exception as e:
        print("Failed loading leaderboard data:", e)


def save_data():
    """Persist current totals to disk."""
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(
                {
                    "contributions": {k: float(v) for k, v in contributions.items()},
                    "total_received": float(total_received),
                },
                f,
            )
    except Exception as e:
        print("Failed saving leaderboard data:", e)


# load stored totals on startup
load_data()


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify({"total_received": float(total_received)})


@app.route("/api/leaderboard", methods=["GET"])
def get_leaderboard():
    leaderboard = sorted(
        [{"name": display_label(name), "total": float(total)} for name, total in contributions.items()],
        key=lambda x: x["total"],
        reverse=True,
    )
    return jsonify(leaderboard)


@app.route("/api/payment", methods=["POST"])
def add_payment():
    global total_received

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

    label_key = normalize_label(str(data["message"]))
    if not label_key:
        return jsonify({"error": "Empty 'message' not allowed"}), 400

    submitted_amount = amount
    if submitted_amount <= 0:
        return jsonify({"error": "Amount must be greater than 0"}), 400

    total_received += submitted_amount

    counted_amount = min(submitted_amount, MAX_PER_SUBMISSION)
    contributions[label_key] += counted_amount
    save_data()

    return jsonify(
        {
            "ok": True,
            "label": display_label(label_key),
            "submitted_amount": float(submitted_amount),
            "counted_amount": float(counted_amount),
            "new_total": float(contributions[label_key]),
            "total_received": float(total_received),
        }
    )


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

    # Cap per submission
    amount = min(amount, MAX_PER_SUBMISSION)

    label_key = normalize_label(str(data["message"]))
    if not label_key:
        return jsonify({"error": "Empty or invalid 'message'"}), 400

    contributions[label_key] += amount
    save_data()

    return jsonify({"ok": True, "label": display_label(label_key), "new_total": float(contributions[label_key])})

@app.route("/admin/rename", methods=["POST"])
def admin_rename_entry():
    if not ADMIN_RESET_TOKEN:
        return jsonify({"error": "Admin not configured"}), 500

    token = request.headers.get("X-Admin-Token")
    if token != ADMIN_RESET_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    old_name = data.get("old_name", "")
    new_name = data.get("new_name", "")

    old_key = normalize_label(str(old_name))
    new_key = normalize_label(str(new_name))

    if not old_key or not new_key:
        return jsonify({"error": "Both 'old_name' and 'new_name' are required"}), 400

    if old_key not in contributions:
        return jsonify({"error": f"'{display_label(old_key)}' not found"}), 404

    if old_key == new_key:
        return jsonify({"ok": True, "message": "No change (same normalized name)"}), 200

    moved_amount = contributions[old_key]

    # Merge into destination if it already exists
    contributions[new_key] += moved_amount

    # Remove old key
    del contributions[old_key]

    save_data()

    return jsonify(
        {
            "ok": True,
            "from": display_label(old_key),
            "to": display_label(new_key),
            "moved_amount": float(moved_amount),
            "new_total": float(contributions[new_key]),
        }
    )



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
