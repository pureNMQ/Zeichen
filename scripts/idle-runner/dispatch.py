#!/usr/bin/env python3
"""Zeichen 闲时调度器：按准入规则选出下一个需求并产出工单。

准入规则（用户确认）：
  1. status=in_progress 的需求优先（按最近活跃 updated_at 倒序，取首个）；
  2. 否则取 status=backlog 的需求（同样最近活跃在前）；
  3. pending（待确认）永不准入；已在 state 中记录 done/failed/dispatched 的不再准入。

设计要点：
  - 直连 Zeichen MCP 的无会话 HTTP 端点（配置取自 ~/.zcode/cli/config.json 的 zeichen 服务器），
    因此本脚本不依赖任何 ZCode 会话即可选单，可挂 cron 做状态巡检；
  - 文件锁（fcntl）保证同一时刻只有一个调度实例；
  - 工单写入 state 目录（仓库外），执行侧由 ZCode 会话按工单派生全新子代理实施，
    完成后用 `mark` 回报结果，串行推进。

用法：
  dispatch.py next [--dry-run]     选出下一个需求并出工单（--dry-run 只打印不落盘）
  dispatch.py status               打印队列与已处理状态
  dispatch.py mark <REQ_ID> <done|failed> [--note "..."]   回报某需求处理结果
  dispatch.py reset <REQ_ID>       清除某需求的处理记录，重新准入

退出码：0=出票/成功；1=队列空；2=锁被占用；3=配置或 MCP 错误；4=用法错误。
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".zcode" / "cli" / "config.json"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "zeichen-idle-runner"
STATE_FILE = STATE_DIR / "state.json"
TICKET_DIR = STATE_DIR / "tickets"
LOCK_FILE = STATE_DIR / "lock"
MCP_TIMEOUT = int(os.environ.get("ZEICHEN_MCP_TIMEOUT", "30"))

EXIT_OK, EXIT_EMPTY, EXIT_LOCKED, EXIT_ERROR, EXIT_USAGE = 0, 1, 2, 3, 4


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def die(code: int, msg: str) -> None:
    print(f"dispatch: {msg}", file=sys.stderr)
    sys.exit(code)


def load_mcp_endpoint() -> tuple[str, dict[str, str]]:
    """从 ZCode CLI 配置读取 zeichen MCP 的 URL 与请求头。"""
    cfg_path = Path(os.environ.get("ZCODE_CLI_CONFIG", DEFAULT_CONFIG))
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        server = cfg["mcp"]["servers"]["zeichen"]
        url = server["url"]
        headers = dict(server.get("headers", {}))
    except (OSError, KeyError, ValueError) as exc:
        die(EXIT_ERROR, f"读取 MCP 配置失败（{cfg_path}）: {exc}")
    headers.setdefault("Content-Type", "application/json")
    headers["Accept"] = "application/json, text/event-stream"
    return url, headers


def mcp_call(url: str, headers: dict[str, str], tool: str, arguments: dict) -> object:
    """调用一个 MCP 工具并解析结果（兼容纯 JSON 与 SSE 两种响应）。"""
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": tool, "arguments": arguments}},
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=MCP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        die(EXIT_ERROR, f"MCP 请求失败（{tool}）: {exc}")
    # SSE 响应形如 "event: message\ndata: {...}"，取最后一个 data: 行
    data_lines = [ln[6:] for ln in body.splitlines() if ln.startswith("data: ")]
    raw = data_lines[-1] if data_lines else body
    try:
        rpc = json.loads(raw)
    except ValueError:
        die(EXIT_ERROR, f"MCP 响应不是 JSON（{tool}）: {raw[:200]}")
    if "error" in rpc:
        die(EXIT_ERROR, f"MCP 调用出错（{tool}）: {rpc['error']}")
    result = rpc.get("result", {})
    if result.get("isError"):
        text = result.get("content", [{}])[0].get("text", "")
        die(EXIT_ERROR, f"MCP 工具报错（{tool}）: {text[:300]}")
    # 优先 structuredContent（列表/对象结构可靠）；退化解析 text
    if "structuredContent" in result:
        return result["structuredContent"]
    text = result.get("content", [{}])[0].get("text", "")
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def resolve_project(mcp) -> dict:
    res = mcp("project.list", {})
    if isinstance(res, list):
        projects = res
    elif isinstance(res, dict):
        projects = res.get("result") or res.get("items") or []
    else:
        projects = []
    wanted = os.environ.get("ZEICHEN_PROJECT_ID")
    if wanted:
        for p in projects:
            if p.get("id") == wanted:
                return p
        die(EXIT_ERROR, f"ZEICHEN_PROJECT_ID={wanted} 不在可访问项目列表中")
    if len(projects) == 1:
        return projects[0]
    names = ", ".join(f"{p['name']}({p['id']})" for p in projects) or "无"
    die(EXIT_ERROR, f"可访问多个项目，请用 ZEICHEN_PROJECT_ID 指定: {names}")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except ValueError:
            pass  # 损坏则视为空状态，锁内重建
    return {"processed": {}}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def admissible(requirement: dict, processed: dict) -> bool:
    if requirement.get("status") not in ("in_progress", "backlog"):
        return False
    return requirement.get("id") not in processed


def pick_next(mcp, project_id: str, processed: dict) -> tuple[dict, list]:
    """in_progress 优先 → backlog；两者都按列表默认的 updated_at 倒序取首个未处理项。"""
    for status in ("in_progress", "backlog"):
        res = mcp("requirements.list", {"project_id": project_id, "status": status, "limit": 100})
        items = res.get("items", []) if isinstance(res, dict) else []
        for req in items:
            if admissible(req, processed):
                tasks_res = mcp("tasks.list", {"project_id": project_id,
                                               "requirement_id": req["id"], "limit": 100})
                tasks = tasks_res.get("items", []) if isinstance(tasks_res, dict) else []
                return req, tasks
    return {}, []


def cmd_next(mcp, project_id: str, dry_run: bool) -> int:
    state = load_state()
    req, tasks = pick_next(mcp, project_id, state["processed"])
    if not req:
        print("队列空：没有可准入的需求（in_progress/backlog 且未处理过）。")
        return EXIT_EMPTY

    short_id = req["id"].split("-")[0]
    ticket = {
        "generated_at": now_iso(),
        "project_id": project_id,
        "requirement": req,
        "tasks": tasks,
        "rules": {
            "admission": "in_progress 优先（最近活跃在前），否则 backlog；pending 永不准入",
            "worker": "ZCode 独立子代理，一需求一会话，串行执行；完成后 dispatch.py mark 回报",
            "constraints": "不 push、不部署；已验证的任务可置 done，证据写入关联需求时间轴并注明来源任务",
        },
    }
    ticket_path = None
    if not dry_run:
        TICKET_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        ticket_path = TICKET_DIR / f"{stamp}-{short_id}.json"
        ticket_path.write_text(json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8")
        state["processed"][req["id"]] = {
            "outcome": "dispatched", "at": now_iso(),
            "title": req.get("title", ""), "ticket": str(ticket_path),
        }
        save_state(state)

    summary = {
        "ticket": str(ticket_path) if ticket_path else "(dry-run)",
        "requirement_id": req["id"],
        "title": req.get("title", ""),
        "status": req.get("status", ""),
        "task_count": len(tasks),
        "updated_at": req.get("updated_at", ""),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return EXIT_OK


def cmd_status(mcp, project_id: str) -> int:
    state = load_state()
    processed = state["processed"]
    print("== 已处理 ==")
    if not processed:
        print("  （无）")
    for rid, info in processed.items():
        print(f"  [{info.get('outcome')}] {info.get('at')} {rid[:8]} {info.get('title', '')}"
              + (f" — {info['note']}" if info.get("note") else ""))
    print("== 待准入队列（按准入顺序） ==")
    seen_any = False
    for status in ("in_progress", "backlog"):
        res = mcp("requirements.list", {"project_id": project_id, "status": status, "limit": 100})
        items = res.get("items", []) if isinstance(res, dict) else []
        for req in items:
            if admissible(req, processed):
                seen_any = True
                print(f"  [{req['status']}] {req['id'][:8]} {req['title']}")
    if not seen_any:
        print("  （空）")
    return EXIT_OK


def cmd_mark(req_id: str, outcome: str, note: str) -> int:
    state = load_state()
    entry = state["processed"].get(req_id)
    if entry is None:
        # 未经过 next 出票也能 mark（如手工补救），补一条记录防止重复准入
        entry = {"outcome": "dispatched", "at": now_iso(), "title": ""}
    entry.update({"outcome": outcome, "at": now_iso(), "note": note})
    state["processed"][req_id] = entry
    save_state(state)
    print(f"已记录 {req_id[:8]} → {outcome}" + (f"（{note}）" if note else ""))
    return EXIT_OK


def cmd_reset(req_id: str) -> int:
    state = load_state()
    if state["processed"].pop(req_id, None) is None:
        die(EXIT_USAGE, f"{req_id} 不在处理记录中")
    save_state(state)
    print(f"已清除 {req_id[:8]} 的处理记录，重新准入")
    return EXIT_OK


def acquire_lock() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        die(EXIT_LOCKED, f"另一个调度实例正在运行（{LOCK_FILE}）")
    fh.truncate(0)
    fh.write(f"{os.getpid()} {now_iso()}\n")
    fh.flush()
    return fh.fileno()  # 持有引用防 GC；进程退出自动释放


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd")
    p_next = sub.add_parser("next", help="选出下一个需求并出工单")
    p_next.add_argument("--dry-run", action="store_true", help="只打印不落盘")
    sub.add_parser("status", help="打印队列与处理状态")
    p_mark = sub.add_parser("mark", help="回报处理结果")
    p_mark.add_argument("req_id")
    p_mark.add_argument("outcome", choices=["done", "failed"])
    p_mark.add_argument("--note", default="")
    p_reset = sub.add_parser("reset", help="清除处理记录，重新准入")
    p_reset.add_argument("req_id")
    args = parser.parse_args()

    cmd = args.cmd or "next"
    if cmd in ("next", "status"):
        lock_fd = acquire_lock()
        assert lock_fd >= 0  # noqa: F641 — 仅保持文件句柄存活
        url, headers = load_mcp_endpoint()

        def mcp(tool: str, arguments: dict):
            return mcp_call(url, headers, tool, arguments)

        project = resolve_project(mcp)
        if cmd == "next":
            return cmd_next(mcp, project["id"], getattr(args, "dry_run", False))
        return cmd_status(mcp, project["id"])
    if cmd == "mark":
        lock_fd = acquire_lock()
        assert lock_fd >= 0
        return cmd_mark(args.req_id, args.outcome, args.note)
    return cmd_reset(args.req_id)


if __name__ == "__main__":
    sys.exit(main())
