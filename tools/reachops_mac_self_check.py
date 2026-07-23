# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.reachops_client_acceptance_status import (
    DEFAULT_BASE_DIR,
    derive_acceptance,
    latest_batch,
    latest_profile_preflight,
    read_lines,
    write_remediation_report,
)
from tools.reachops_web_ui import WEB_UI_VERSION

DEFAULT_PORT = 8769
URL_PATH = DEFAULT_BASE_DIR / "reachops_web_ui_url.txt"
REQUIRED_WEB_UI_MARKERS = [
    "ReachOps 统一控制台",
    "ReachOps 本地客户端控制台",
    "客户端外壳",
    "ReachOpsApp.py",
    "127.0.0.1 控制台",
    "客户端 v20",
    "执行期 0 token",
    "未授权不提交",
    f'data-reachops-ui-version="{WEB_UI_VERSION}"',
    'id="volume"',
    'id="accountRepairConfirmed"',
    'id="applyAccountRepair"',
    'id="accountGateState"',
    "账号门禁已启用",
    'id="uiVersion"',
    "已修复账号，允许重新预检",
    "隔离坏账号",
    "/api/account-repair-apply",
    "applyAccountRepairPlan",
    "账号池无可执行账号，已禁止重复启动",
    "账号修复计划：",
    "accountRepairActionItems",
    "账号修复安全边界",
    "no_browser_started",
    "no_submit",
    "no_ai_token_used",
    "旧账号修复结果已失效",
    "account_repair_summary",
    "error_groups",
    "profile_ids_sample",
    'placeholder="输入产品链接、关键词、达人主页、视频链接、话题或直播间"',
    "客户端门禁",
    "client_delivery_summary",
    "最终交付门禁",
    'id="finalStatusState"',
    'id="finalStatusActions"',
    'id="finalStatusCommands"',
    "最终交付下一步",
    "最终复核命令",
    "fetch('/api/final-status')",
    "next_required_actions",
    "verification_commands",
    "final_delivery_ready",
    "failed_checks",
    "AI 信息沙漏",
    'id="infoHourglass"',
    'id="hourglassParticles"',
    "renderInfoHourglass",
    'id="previewPlan"',
    "执行计划",
    "execution_plan_schema",
    "run_session_state",
    "RUNNING${sessionState",
]


def check_python() -> dict:
    return {
        "ok": True,
        "executable": sys.executable,
        "version": sys.version.split()[0],
    }


def check_tk() -> dict:
    script = (
        "import tkinter as tk\n"
        "root=tk.Tk()\n"
        "root.withdraw()\n"
        "print(root.tk.call('info','patchlevel'))\n"
        "root.destroy()\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode == 0:
        return {"ok": True, "version": output}
    message = error or output or f"Tk check failed returncode={completed.returncode}"
    payload = {"ok": False, "returncode": completed.returncode, "error": message}
    payload.update(classify_tk_failure(message, returncode=completed.returncode))
    return payload


def classify_tk_failure(error_text: str, returncode: int | None = None) -> dict:
    text = str(error_text or "")
    if returncode in {134, -6} or "abort" in text.lower() or "returncode=134" in text:
        return {
            "failure_code": "PYTHON_TK_ABORTED",
            "message": "当前 Python/Tk 在创建窗口时直接中止，原生 Tk 客户端不能使用这个解释器启动。",
            "operator_actions": [
                "安装带稳定 Tk 支持的 Python 3.11/3.12 后再运行“启动ReachOps原生MacUI.command”。",
                "当前先使用“启动ReachOps统一WebUI.command”进入本地客户端控制台验收执行链路。",
                "这类错误发生在 Python/Tk 图形运行时，不是 ReachOpsApp.py 入口逻辑错误。",
            ],
        }
    if "Can't find a usable tk.tcl" in text or "TclError" in text or "tk scaling" in text or "NaN" in text:
        return {
            "failure_code": "PYTHON_TK_UNUSABLE",
            "message": "当前 Python/Tk 运行环境不可用，原生 Tk 客户端无法在这个解释器里启动。",
            "operator_actions": [
                "优先双击“启动ReachOps原生MacUI.command”，使用本机桌面环境启动原客户端。",
                "如果仍失败，改用系统 Python 或重新安装带 Tk 支持的 Python 3.11 后再运行 python ReachOpsApp.py。",
                "这类错误不是 ReachOpsApp.py 入口分流问题；本地客户端控制台请单独运行“启动ReachOps统一WebUI.command”。",
            ],
        }
    if "no display name" in text or "DISPLAY" in text:
        return {
            "failure_code": "TK_DISPLAY_UNAVAILABLE",
            "message": "当前环境没有可用图形会话，不能启动原生 Tk 客户端。",
            "operator_actions": [
                "在 Mac 桌面会话中启动，不要在无图形会话或受限自动化沙箱里启动原生客户端。",
                "需要本地客户端控制台时，单独运行“启动ReachOps统一WebUI.command”。",
            ],
        }
    return {
        "failure_code": "TK_CHECK_FAILED",
        "message": "原生 Tk 客户端自检失败。",
        "operator_actions": [
            "先确认本机 Python 能执行 import tkinter 并创建 Tk 窗口。",
            "再运行 python ReachOpsApp.py 启动原客户端。",
        ],
    }


def evaluate_web_ui_body(body: str) -> dict:
    text = str(body or "")
    missing = [marker for marker in REQUIRED_WEB_UI_MARKERS if marker not in text]
    title = "ReachOps 统一控制台" if "ReachOps 统一控制台" in text else "unknown"
    return {
        "title": title,
        "missing_markers": missing,
        "ui_current": not missing,
        "ok": title == "ReachOps 统一控制台" and not missing,
    }


def is_port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def read_local_url(url: str, *, timeout: float = 3.0, attempts: int = 3) -> str:
    last_error = None
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = int(parsed.port or 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    for index in range(max(1, int(attempts or 1))):
        conn = None
        try:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            conn.request(
                "GET",
                path,
                headers={
                    "Host": f"{host}:{port}",
                    "User-Agent": "ReachOpsSelfCheck/1.0",
                    "Accept": "application/json,text/html,*/*",
                },
            )
            response = conn.getresponse()
            data = response.read()
            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status} {response.reason}")
            return data.decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if index + 1 < max(1, int(attempts or 1)):
                time.sleep(0.15)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    if last_error:
        raise last_error
    return ""


def read_local_json(url: str, *, timeout: float = 3.0, attempts: int = 3) -> dict:
    return json.loads(read_local_url(url, timeout=timeout, attempts=attempts))


def apply_version_payload(result: dict, version_payload: dict) -> None:
    result["version_api_ok"] = True
    result["version"] = str(version_payload.get("version") or "")
    result["display_version"] = str(version_payload.get("display_version") or "")
    result["client_surface"] = str(version_payload.get("client_surface") or "")
    result["display_name"] = str(version_payload.get("display_name") or "")
    result["loopback_host"] = str(version_payload.get("loopback_host") or "")
    result["version_current"] = result["version"] == WEB_UI_VERSION
    result["client_surface_current"] = result["client_surface"] == "local_client_console"
    result["display_version_current"] = result["display_version"] == "客户端 v20"
    result["loopback_host_current"] = result["loopback_host"] == "127.0.0.1"


def check_web_version_port(port: int) -> dict:
    result = {
        "ok": False,
        "port": port,
        "listening": False,
        "http_ok": False,
        "version_api_ok": False,
        "version": "",
        "display_version": "",
        "client_surface": "",
        "display_name": "",
        "loopback_host": "",
        "version_current": False,
        "client_surface_current": False,
        "display_version_current": False,
        "loopback_host_current": False,
        "title": "",
        "ui_current": False,
        "missing_markers": [],
    }
    result["listening"] = is_port_listening(port)
    if not result["listening"]:
        result["ok"] = True
        return result
    try:
        version_payload = read_local_json(f"http://127.0.0.1:{port}/api/version", timeout=2, attempts=3)
        result["http_ok"] = True
        apply_version_payload(result, version_payload)
        result["title"] = "ReachOps 统一控制台" if result["version_current"] else ""
        result["ui_current"] = bool(
            result["version_current"]
            and result["client_surface_current"]
            and result["display_version_current"]
            and result["loopback_host_current"]
        )
    except Exception as exc:
        result["version_error"] = f"{type(exc).__name__}: {exc}"
    result["ok"] = bool(result.get("version_api_ok") and result.get("ui_current"))
    return result


def check_port(port: int) -> dict:
    result = check_web_version_port(port)
    if not result["listening"]:
        return result
    try:
        body = read_local_url(f"http://127.0.0.1:{port}/", timeout=3, attempts=3)[:256000]
        result["http_ok"] = True
        result.update(evaluate_web_ui_body(body))
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    try:
        version_payload = read_local_json(f"http://127.0.0.1:{port}/api/version", timeout=3, attempts=3)
        apply_version_payload(result, version_payload)
    except Exception as exc:
        result["version_error"] = f"{type(exc).__name__}: {exc}"
    result["ok"] = bool(
        result.get("http_ok")
        and result.get("ui_current")
        and result.get("version_api_ok")
        and result.get("version_current")
        and result.get("client_surface_current")
        and result.get("display_version_current")
        and result.get("loopback_host_current")
    )
    return result


def find_available_port(start_port: int, end_port: int = 8789) -> int:
    for port in range(int(start_port), int(end_port) + 1):
        status = check_port(port)
        if not status.get("listening"):
            return port
    raise RuntimeError(f"No available local port in {start_port}-{end_port}")


def check_acceptance(base_dir: Path) -> dict:
    db_path = base_dir / "data/growth_intelligence/growth_intelligence.db"
    log_path = base_dir / "logs/growth_ops_runtime.log"
    batch = latest_batch(db_path)
    preflight = latest_profile_preflight(db_path)
    acceptance = derive_acceptance(batch, preflight, read_lines(log_path))
    remediation_report = write_remediation_report(
        base_dir,
        batch,
        acceptance.get("profile_preflight_details") or [],
        preflight_errors=(acceptance.get("profile_preflight_summary") or {}).get("errors") or {},
    )
    return {
        "ok": acceptance.get("readiness") in {"pass", "partial"},
        "readiness": acceptance.get("readiness"),
        "batch": {
            "id": batch.get("id", ""),
            "status": batch.get("status", ""),
            "group": batch.get("profile_group", ""),
        },
        "profile_preflight": {
            "checked": preflight.get("checked", 0),
            "available": preflight.get("available", 0),
            "errors": preflight.get("errors", {}),
        },
        "execution_context": acceptance.get("execution_context", {}),
        "profile_error_summary": acceptance.get("profile_error_summary", {}),
        "remediation_report": remediation_report,
        "blockers": acceptance.get("blockers", []),
        "next_actions": acceptance.get("next_actions", []),
    }


def check_client_delivery(base_dir: Path) -> dict:
    from tools.reachops_client_delivery_check import build_delivery_check

    payload = build_delivery_check(base_dir)
    return {
        "status": payload.get("status"),
        "ok": payload.get("ok"),
        "contract_ok": payload.get("contract_ok"),
        "acceptance_ready": payload.get("acceptance_ready"),
        "final_delivery_ready": payload.get("final_delivery_ready"),
        "readiness": payload.get("readiness"),
        "failed_checks": payload.get("failed_checks") or [],
        "blockers": payload.get("blockers") or [],
        "next_actions": payload.get("next_actions") or [],
    }


def start_web(port: int) -> dict:
    command = [
        sys.executable,
        str(ROOT_DIR / "tools" / "reachops_web_ui.py"),
        "--web",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-browser",
    ]
    log_dir = DEFAULT_BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "reachops_web_ui_launcher.log"
    fh = log_path.open("a", encoding="utf-8")
    fh.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} start {' '.join(command)}\n")
    fh.flush()
    env = os.environ.copy()
    env["REACHOPS_WEB_HOST"] = "127.0.0.1"
    env["REACHOPS_WEB_PORT"] = str(port)
    env["REACHOPS_WEB_NO_BROWSER"] = "1"
    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT_DIR),
            stdout=fh,
            stderr=subprocess.STDOUT,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
    except Exception as exc:
        fh.write(f"ERROR start_web_failed {type(exc).__name__}: {exc}\n")
        return {
            "ok": False,
            "pid": 0,
            "log": str(log_path),
            "port": int(port),
            "url": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        fh.close()
    url = f"http://127.0.0.1:{int(port)}/"
    return {"ok": True, "pid": process.pid, "log": str(log_path), "port": int(port), "url": url}


def wait_for_web_ui(port: int, process_pid: int, timeout_seconds: float = 10.0) -> dict:
    deadline = time.time() + float(timeout_seconds)
    latest = check_web_version_port(port)
    while time.time() < deadline:
        if latest.get("ok") and latest.get("listening"):
            return latest
        if process_pid:
            try:
                os.kill(int(process_pid), 0)
            except OSError:
                return latest
        time.sleep(0.5)
        latest = check_web_version_port(port)
    return latest


def process_is_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def classify_web_start_failure(log_tail: str) -> dict:
    text = str(log_tail or "")
    if "PermissionError" in text and "Operation not permitted" in text:
        return {
            "code": "LOCAL_PORT_BIND_BLOCKED",
            "message": "当前执行环境禁止监听 127.0.0.1 本地端口，本地客户端控制台后端未启动。",
            "operator_actions": [
                "在 Mac 桌面双击“启动ReachOps统一WebUI.command”，不要在受限沙箱里启动。",
                "如果仍失败，在系统终端执行：cd 项目目录 && .venv/bin/python tools/reachops_web_ui.py --web --host 127.0.0.1 --port 8769",
                "启动成功后以终端打印的实际地址为准，浏览器不要继续使用旧端口。",
            ],
        }
    if "Address already in use" in text:
        return {
            "code": "LOCAL_PORT_IN_USE",
            "message": "目标端口已被其他进程占用。",
            "operator_actions": [
                "关闭旧的 ReachOps 本地客户端控制台窗口后重试。",
                "或使用 --port 指定 8769-8789 之间的其他端口。",
            ],
        }
    return {
        "code": "WEB_UI_START_FAILED",
        "message": "本地客户端控制台后端启动失败，请查看启动日志。",
        "operator_actions": ["查看 reports/reachops/mac_gui/runtime/logs/reachops_web_ui_launcher.log 的最后错误。"],
    }


def write_url(url: str):
    URL_PATH.parent.mkdir(parents=True, exist_ok=True)
    URL_PATH.write_text(str(url or ""), encoding="utf-8")


def read_tail(path: str | Path, limit: int = 12) -> str:
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-limit:])
    except Exception:
        return ""


def format_human(payload: dict) -> str:
    lines = []
    lines.append("ReachOps Mac 自检")
    lines.append(f"项目目录: {ROOT_DIR}")
    py = payload["python"]
    lines.append(f"Python: {'OK' if py['ok'] else 'FAIL'} {py.get('version', '')} {py.get('executable', '')}")
    tk = payload["tk"]
    tk_detail = tk.get("version") if tk.get("ok") else (tk.get("message") or first_line(tk.get("error", "")) or "")
    lines.append(f"Tk 原生 UI: {'OK' if tk['ok'] else 'FAIL'} {tk_detail}")
    if not tk.get("ok") and tk.get("failure_code"):
        lines.append(f"Tk 失败类型: {tk.get('failure_code')} - {tk.get('message', '')}")
        for item in tk.get("operator_actions") or []:
            lines.append(f"Tk 恢复: {item}")
    port = payload["port"]
    lines.append(
        f"本地客户端控制台端口 {port['port']}: listening={port['listening']} "
        f"http_ok={port['http_ok']} title={port.get('title') or '-'} current={port.get('ui_current', False)} "
        f"surface={port.get('client_surface') or '-'} display={port.get('display_version') or '-'}"
    )
    if port.get("missing_markers"):
        lines.append(f"本地客户端控制台版本检查: 旧页面/不完整 missing={port.get('missing_markers')}")
    if payload.get("stale_web_port"):
        stale = payload["stale_web_port"]
        lines.append(
            f"旧本地客户端控制台端口: {stale.get('port')} current={stale.get('ui_current', False)} "
            f"version={stale.get('version') or '-'}；已改用新的实际地址"
        )
    if payload.get("started_web"):
        started = payload["started_web"]
        if started.get("ok"):
            lines.append(f"已启动本地客户端控制台: {started.get('url', '-')} pid={started.get('pid')} log={started.get('log')}")
        else:
            lines.append(f"本地客户端控制台启动失败: {started.get('error', '-')} log={started.get('log', '-')}")
    if payload.get("web_start_error"):
        lines.append(f"本地客户端控制台启动异常: {payload['web_start_error']}")
    if payload.get("web_start_failure"):
        failure = payload["web_start_failure"]
        lines.append(f"本地客户端控制台启动失败类型: {failure.get('code')} - {failure.get('message')}")
        for item in failure.get("operator_actions") or []:
            lines.append(f"本地客户端控制台恢复: {item}")
    if payload.get("web_url"):
        lines.append(f"本地客户端控制台地址: {payload['web_url']}")
    acc = payload["acceptance"]
    preflight = acc["profile_preflight"]
    lines.append(f"验收状态: {acc.get('readiness')}")
    lines.append(
        f"最新批次: {acc['batch'].get('id') or '-'} status={acc['batch'].get('status') or '-'} "
        f"group={acc['batch'].get('group') or '-'}"
    )
    lines.append(
        f"账号预检: checked={preflight.get('checked', 0)} "
        f"available={preflight.get('available', 0)} errors={preflight.get('errors', {})}"
    )
    for error, item in (acc.get("profile_error_summary") or {}).items():
        ids = ",".join((item.get("profile_ids") or [])[:16])
        lines.append(f"账号修复: error={error} count={item.get('count', 0)} profiles={ids or '-'}")
    if acc.get("remediation_report"):
        report = acc["remediation_report"]
        lines.append(
            "账号修复文件: "
            f"csv={report.get('csv_path')} "
            f"json={report.get('json_path')} "
            f"markdown={report.get('markdown_path')} "
            f"guide={report.get('guide_path')} "
            f"index={report.get('index_path')} "
            f"manifest={report.get('manifest_path')} "
            f"latest_csv={report.get('latest_csv_path')} "
            f"latest_json={report.get('latest_json_path')} "
            f"latest_markdown={report.get('latest_markdown_path')} "
            f"latest_guide={report.get('latest_guide_path')} "
            f"latest_index={report.get('latest_index_path')} "
            f"latest_manifest={report.get('latest_manifest_path')} "
            f"account_plan_md={report.get('account_plan_markdown_path')} "
            f"account_plan_json={report.get('account_plan_json_path')} "
            f"latest_account_plan_md={report.get('latest_account_plan_markdown_path')} "
            f"latest_account_plan_json={report.get('latest_account_plan_json_path')}"
        )
    for item in acc.get("blockers") or []:
        lines.append(f"阻断: {item}")
    for item in acc.get("next_actions") or []:
        lines.append(f"下一步: {item}")
    client_delivery = payload.get("client_delivery") or {}
    if client_delivery:
        lines.append(
            f"客户端门禁: status={client_delivery.get('status')} "
            f"final_delivery_ready={client_delivery.get('final_delivery_ready')} "
            f"contract_ok={client_delivery.get('contract_ok')} "
            f"acceptance_ready={client_delivery.get('acceptance_ready')}"
        )
        if client_delivery.get("failed_checks"):
            lines.append(f"客户端门禁失败: {','.join(client_delivery.get('failed_checks') or [])}")
    return "\n".join(lines)


def first_line(value: str) -> str:
    for line in str(value or "").splitlines():
        text = line.strip()
        if text:
            return text[:220]
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ReachOps Mac client self-check.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--start-web", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.start_web:
        try:
            URL_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    payload = {
        "root_dir": str(ROOT_DIR),
        "python": check_python(),
        "tk": check_tk(),
        "port": check_web_version_port(args.port) if args.start_web else check_port(args.port),
        "acceptance": check_acceptance(Path(args.base_dir)),
        "client_delivery": check_client_delivery(Path(args.base_dir)),
    }
    if args.start_web and payload["port"].get("ok") and payload["port"].get("listening"):
        payload["web_url"] = f"http://127.0.0.1:{int(args.port)}/"
        write_url(payload["web_url"])
    elif args.start_web:
        if payload["port"].get("listening") and not payload["port"].get("ok"):
            payload["stale_web_port"] = dict(payload["port"])
        selected_port = args.port if not payload["port"].get("listening") else find_available_port(args.port + 1)
        payload["started_web"] = start_web(selected_port)
        if payload["started_web"].get("ok"):
            started_pid = int(payload["started_web"].get("pid") or 0)
            payload["port"] = wait_for_web_ui(selected_port, started_pid)
            if process_is_alive(started_pid):
                payload["web_url"] = payload["started_web"]["url"]
                write_url(payload["web_url"])
            else:
                payload["started_web"]["ok"] = False
                log_tail = read_tail(payload["started_web"]["log"])
                if log_tail:
                    payload["web_start_error"] = log_tail.splitlines()[-1]
                    payload["web_start_failure"] = classify_web_start_failure(log_tail)
        else:
            payload["web_start_error"] = payload["started_web"].get("error")
            payload["web_start_failure"] = classify_web_start_failure(payload["web_start_error"])

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_human(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
