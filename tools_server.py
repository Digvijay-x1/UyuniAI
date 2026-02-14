"""
Flask server that wraps Salt LocalClient as HTTP endpoints.
Runs inside the Uyuni container.
Deploy with: python3 /opt/tools_server.py
"""

from flask import Flask, request, jsonify
import salt.client

app = Flask(__name__)
local = salt.client.LocalClient()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/run_command", methods=["POST"])
def run_command():
    """Run an arbitrary command on a minion via cmd.run."""
    data = request.get_json()
    minion_id = data.get("minion_id", "")
    cmd = data.get("cmd", "")

    if not minion_id or not cmd:
        return jsonify({"error": "minion_id and cmd required"}), 400

    try:
        result = local.cmd(minion_id, "cmd.run", [cmd])
        output = result.get(minion_id, "No response from minion")
        return jsonify({"result": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/disk_usage", methods=["GET"])
def disk_usage():
    """Get disk usage for a minion via disk.usage."""
    minion_id = request.args.get("minion_id", "")

    if not minion_id:
        return jsonify({"error": "minion_id required"}), 400

    try:
        result = local.cmd(minion_id, "disk.usage")
        output = result.get(minion_id, "No response from minion")
        return jsonify({"result": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/service_status", methods=["GET"])
def service_status():
    """Check if a service is running on a minion."""
    minion_id = request.args.get("minion_id", "")
    service = request.args.get("service", "")

    if not minion_id or not service:
        return jsonify({"error": "minion_id and service required"}), 400

    try:
        result = local.cmd(minion_id, "service.status", [service])
        status = result.get(minion_id, None)
        return jsonify({"result": status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/service_logs", methods=["GET"])
def service_logs():
    """Get recent journal logs for a service."""
    minion_id = request.args.get("minion_id", "")
    service = request.args.get("service", "")
    lines = request.args.get("lines", "50")

    if not minion_id or not service:
        return jsonify({"error": "minion_id and service required"}), 400

    cmd = "journalctl -u %s -n %s --no-pager" % (service, lines)
    try:
        result = local.cmd(minion_id, "cmd.run", [cmd])
        output = result.get(minion_id, "No response from minion")
        return jsonify({"result": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Starting Salt Tools Server on port 5000...")
    app.run(host="0.0.0.0", port=5000)
