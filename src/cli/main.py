"""CLI entry point for the agent orchestrator."""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml

from src.common.logging import configure_logging
from src.sdk.client import OrchestratorClient

EXAMPLE_MANIFEST = """\
# Agent manifest — deploy with: ao deploy <this file>
name: hello-agent
type: demo.hello
config:
  greeting: "Hello from Agent Orchestration"
  # Optional: launch the agent as a real process when it is started.
  # The command runs relative to the orchestrator server's working directory;
  # stdout/stderr are captured and available via `ao logs <agent-id>`.
  # command: "python3 -u my_agent.py"
"""

# ANSI styling — honors NO_COLOR (https://no-color.org) and non-TTY output.
_COLOR = sys.stdout.isatty() and not os.getenv("NO_COLOR")

# one meaning per color, matching the dashboard: blue = active, green = success,
# yellow = waiting/retrying, red = failure, dim = idle
_STATUS_STYLE = {
    "running": "34", "queued": "34",
    "completed": "32",
    "paused": "33", "retrying": "33",
    "failed": "31", "terminated": "31",
    "pending": "2", "stopped": "2",
}


def _style(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _status(status: str, pad: int = 0) -> str:
    text = status.ljust(pad) if pad else status
    return _style(_STATUS_STYLE.get(status, "2"), text)


def _ok(message: str) -> None:
    print(f"{_style('32', '✓')} {message}")


def _client(args) -> OrchestratorClient:
    return OrchestratorClient(base_url=args.api_url, api_key=args.api_key)


def _fail(message: str) -> None:
    print(f"{_style('31', '✗')} {message}", file=sys.stderr)
    sys.exit(1)


def _check(result: dict) -> dict:
    # The client signals request failures with an {"error": ..., "message": ...}
    # envelope; task records may carry their own "error" field, so require both keys.
    if isinstance(result, dict) and result.get("error") is not None and "message" in result:
        _fail(f"{result['error']}: {result['message']}")
    return result


def cmd_serve(args) -> None:
    import uvicorn

    if args.db:
        os.environ["AO_DB_PATH"] = args.db
    uvicorn.run(
        "src.api.server:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def cmd_init(args) -> None:
    project = Path(args.name)
    if project.exists():
        _fail(f"Directory already exists: {project}")
    (project / "agents").mkdir(parents=True)
    (project / "agents" / "hello-agent.yaml").write_text(EXAMPLE_MANIFEST)
    _ok(f"Initialized project: {_style('1', str(project))}")
    print(f"  Deploy the example agent with: ao deploy {project}/agents/hello-agent.yaml")


def cmd_deploy(args) -> None:
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        _fail(f"Manifest not found: {manifest_path}")

    try:
        manifest = yaml.safe_load(manifest_path.read_text())
    except yaml.YAMLError as e:
        _fail(f"Invalid YAML in {manifest_path}: {e}")

    if not isinstance(manifest, dict) or "name" not in manifest or "type" not in manifest:
        _fail(f"Manifest must define 'name' and 'type': {manifest_path}")

    result = _check(_client(args).register_agent(
        manifest["name"],
        manifest["type"],
        manifest.get("config") or {},
    ))
    _ok(f"Deployed agent {_style('1', manifest['name'])} (id: {result['agent_id']})")


def _print_agents(agents: list) -> None:
    if not agents:
        print("No agents registered.")
        return
    header = f"{'ID':<38} {'NAME':<20} {'TYPE':<20} {'STATUS':<10} {'TASKS':>5} {'ERRORS':>6}"
    print(_style("1", header))
    print(_style("2", "-" * len(header)))
    for a in agents:
        m = a.get("metrics", {})
        errors = m.get("errors", 0)
        agent_id = "{:<38}".format(a["id"])
        errors_col = "{:>6}".format(errors)
        print(f"{_style('2', agent_id)} {a['name']:<20} {a['type']:<20} "
              f"{_status(a['status'], 10)} {m.get('tasks_completed', 0):>5} "
              f"{_style('31', errors_col) if errors else errors_col}")


def cmd_status(args) -> None:
    client = _client(args)
    while True:
        result = _check(client.list_agents())
        if args.watch:
            print("\033[2J\033[H", end="")  # clear screen
        _print_agents(result.get("agents", []))
        if not args.watch:
            break
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            break


def cmd_info(args) -> None:
    agent = _check(_client(args).get_agent(args.agent_id))
    print(json.dumps(agent, indent=2, default=str))


def cmd_submit(args) -> None:
    try:
        payload = json.loads(args.payload) if args.payload else {}
    except json.JSONDecodeError as e:
        _fail(f"Invalid JSON payload: {e}")

    client = _client(args)
    result = _check(client.submit_task(args.agent_id, payload=payload, priority=args.priority))
    task_id = result["task_id"]
    _ok(f"Submitted task: {task_id}")

    if args.wait:
        task = result
        deadline = time.time() + args.wait
        while time.time() < deadline:
            task = _check(client.get_task(task_id))
            if task["status"] in ("completed", "failed"):
                print(f"  status: {_status(task['status'])}")
                print(json.dumps(task, indent=2, default=str))
                return
            time.sleep(0.2)
        print(f"Task still {_status(task.get('status', 'queued'))} after {args.wait}s — "
              f"check later with: ao task {task_id}")


def cmd_task(args) -> None:
    task = _check(_client(args).get_task(args.task_id))
    print(json.dumps(task, indent=2, default=str))


def cmd_logs(args) -> None:
    result = _check(_client(args).get_agent_logs(args.agent_id, tail=args.tail))
    if result.get("log"):
        print(result["log"])
    else:
        print("No process logs for this agent — it may not have a `command` configured "
              "or has not been started yet.")


def cli() -> None:
    parser = argparse.ArgumentParser(prog="ao", description="Agent Orchestrator CLI")
    parser.add_argument("--api-url", default=None,
                        help="Orchestrator API URL (default: $AO_API_URL or http://127.0.0.1:8000)")
    parser.add_argument("--api-key", default=None, help="API key (default: $AO_API_KEY)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    serve_parser = subparsers.add_parser("serve", help="Run the orchestrator API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    serve_parser.add_argument("--db", default=None, metavar="PATH",
                              help="SQLite file for persistent state (default: $AO_DB_PATH, or in-memory)")
    serve_parser.set_defaults(func=cmd_serve)

    init_parser = subparsers.add_parser("init", help="Initialize a new project")
    init_parser.add_argument("name", help="Project name")
    init_parser.set_defaults(func=cmd_init)

    deploy_parser = subparsers.add_parser("deploy", help="Deploy an agent from a YAML manifest")
    deploy_parser.add_argument("manifest", help="Path to agent manifest file")
    deploy_parser.set_defaults(func=cmd_deploy)

    status_parser = subparsers.add_parser("status", help="Show agent status")
    status_parser.add_argument("--watch", "-w", action="store_true", help="Refresh every 2 seconds")
    status_parser.set_defaults(func=cmd_status)

    info_parser = subparsers.add_parser("info", help="Show details for an agent")
    info_parser.add_argument("agent_id", help="Agent ID")
    info_parser.set_defaults(func=cmd_info)

    submit_parser = subparsers.add_parser("submit", help="Submit a task to an agent")
    submit_parser.add_argument("agent_id", help="Target agent ID")
    submit_parser.add_argument("--payload", "-p", default="", help="Task payload as JSON")
    submit_parser.add_argument("--priority", type=int, default=0)
    submit_parser.add_argument("--wait", type=float, default=10.0, metavar="SECONDS",
                               help="Wait up to SECONDS for the result (0 = don't wait)")
    submit_parser.set_defaults(func=cmd_submit)

    task_parser = subparsers.add_parser("task", help="Show status/result of a task")
    task_parser.add_argument("task_id", help="Task ID")
    task_parser.set_defaults(func=cmd_task)

    logs_parser = subparsers.add_parser("logs", help="Show an agent's process logs")
    logs_parser.add_argument("agent_id", help="Agent ID")
    logs_parser.add_argument("--tail", "-t", type=int, default=50, help="Number of lines")
    logs_parser.set_defaults(func=cmd_logs)

    args = parser.parse_args()
    configure_logging("DEBUG" if args.verbose else "INFO", json_output=False)
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)

    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    cli()
