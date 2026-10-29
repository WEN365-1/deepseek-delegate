#!/usr/bin/env python3
"""Run a bounded DeepSeek delegation inside one project directory.

Uses only the Python standard library. The API key is read exclusively from
DEEPSEEK_API_KEY and is never printed or written to the run record.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SENSITIVE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "secrets.json"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".pfx", ".p12"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delegate a bounded task to DeepSeek.")
    parser.add_argument("--project", required=True, help="Project root; all file tools stay inside it.")
    parser.add_argument("--instruction", required=True, help="UTF-8 instruction file inside the project.")
    parser.add_argument("--report", help="Write DeepSeek's final report to this file inside the project.")
    parser.add_argument("--json-output", help="Write the non-sensitive run record as JSON.")
    parser.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))
    parser.add_argument("--max-turns", type=int, default=24)
    parser.add_argument("--timeout", type=int, default=240, help="Overall wall-clock limit in seconds.")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--effort", choices=("low", "high", "max"), default="high")
    parser.add_argument("--write", action="store_true", help="Enable new-file creation inside the project.")
    parser.add_argument("--allow-overwrite", action="store_true", help="Allow overwriting existing files; requires --write.")
    parser.add_argument("--allow-python", action="store_true", help="Allow running project Python scripts; not a sandbox.")
    return parser.parse_args()


class DelegationError(RuntimeError):
    pass


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = Path(args.project).resolve()
        if not self.root.is_dir():
            raise DelegationError(f"Project directory does not exist: {self.root}")
        self.started = time.monotonic()
        self.deadline = self.started + args.timeout
        self.events: list[dict[str, Any]] = []
        self.usage_by_call: list[dict[str, Any]] = []

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def check_time(self) -> None:
        if self.remaining() <= 0:
            raise DelegationError(f"Overall timeout exceeded ({self.args.timeout}s). Split the task and retry.")

    def path(self, value: str, *, sensitive_ok: bool = False) -> Path:
        candidate = Path(value)
        resolved = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise DelegationError(f"Path escapes the project root: {value}") from exc
        if ".git" in resolved.parts:
            raise DelegationError("Access to .git is disabled.")
        if not sensitive_ok and (resolved.name.lower() in SENSITIVE_NAMES or resolved.suffix.lower() in SENSITIVE_SUFFIXES):
            raise DelegationError(f"Sensitive file access is disabled: {resolved.name}")
        return resolved

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root)).replace("\\", "/")

    def read_file(self, path: str, offset: int = 0, max_chars: int = 12000) -> dict[str, Any]:
        target = self.path(path)
        if not target.is_file():
            raise DelegationError(f"Not a file: {path}")
        if target.stat().st_size > 5 * 1024 * 1024:
            raise DelegationError("File exceeds 5 MB; use a more specific extraction tool outside this runner.")
        offset = max(0, min(int(offset), 10_000_000))
        max_chars = max(1, min(int(max_chars), 50_000))
        text = target.read_text(encoding="utf-8")
        chunk = text[offset : offset + max_chars]
        return {
            "path": self.relative(target),
            "offset": offset,
            "content": chunk,
            "truncated": offset + max_chars < len(text),
            "total_chars": len(text),
        }

    def list_files(self, path: str = ".", pattern: str = "**/*", max_results: int = 200) -> dict[str, Any]:
        base = self.path(path)
        if not base.is_dir():
            raise DelegationError(f"Not a directory: {path}")
        limit = max(1, min(int(max_results), 500))
        results: list[str] = []
        truncated = False
        for item in base.glob(pattern):
            try:
                resolved = self.path(str(item))
                if resolved.is_file() and ".git" not in resolved.parts:
                    results.append(self.relative(resolved))
                    if len(results) >= limit:
                        truncated = True
                        break
            except (DelegationError, OSError):
                continue
        return {"files": sorted(results), "truncated": truncated}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        if not self.args.write:
            raise DelegationError("Writing is disabled for this run.")
        if len(content) > 200_000:
            raise DelegationError("Single write exceeds 200,000 characters.")
        target = self.path(path)
        existed = target.exists()
        if existed and not self.args.allow_overwrite:
            raise DelegationError(f"Refusing to overwrite an existing file: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": self.relative(target), "characters_written": len(content), "overwritten": existed}

    def run_python(self, script: str, arguments: list[str] | None = None) -> dict[str, Any]:
        if not self.args.allow_python:
            raise DelegationError("Python execution is disabled for this run.")
        self.check_time()
        target = self.path(script)
        if target.suffix.lower() != ".py" or not target.is_file():
            raise DelegationError("Only existing .py files inside the project can be run.")
        arguments = arguments or []
        if len(arguments) > 20 or not all(isinstance(item, str) for item in arguments):
            raise DelegationError("Python arguments must be a list of at most 20 strings.")
        timeout = max(1, min(60, int(self.remaining())))
        env = os.environ.copy()
        env.pop("DEEPSEEK_API_KEY", None)
        env["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            [sys.executable, str(target), *arguments],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return {
            "script": self.relative(target),
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-20_000:],
            "stderr": completed.stderr[-20_000:],
        }

    def tools(self) -> list[dict[str, Any]]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a UTF-8 text file inside the project.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "offset": {"type": "integer", "minimum": 0},
                            "max_chars": {"type": "integer", "minimum": 1, "maximum": 50000},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List project files matching a glob pattern.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "pattern": {"type": "string"},
                            "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
                        },
                        "additionalProperties": False,
                    },
                },
            },
        ]
        if self.args.write:
            tools.append({
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Create a UTF-8 file inside the project. Existing files require explicit overwrite permission.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                },
            })
        if self.args.allow_python:
            tools.append({
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "Run a project Python script with string arguments. This is not a security sandbox.",
                    "parameters": {
                        "type": "object",
                        "properties": {"script": {"type": "string"}, "arguments": {"type": "array", "items": {"type": "string"}}},
                        "required": ["script"],
                        "additionalProperties": False,
                    },
                },
            })
        return tools

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "read_file":
            return self.read_file(**arguments)
        if name == "list_files":
            return self.list_files(**arguments)
        if name == "write_file":
            return self.write_file(**arguments)
        if name == "run_python":
            return self.run_python(**arguments)
        raise DelegationError(f"Unknown tool: {name}")

    def call_api(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.check_time()
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise DelegationError("DEEPSEEK_API_KEY is not configured. Configure it privately outside the chat.")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        payload = {
            "model": self.args.model,
            "messages": messages,
            "tools": self.tools(),
            "thinking": {"type": "enabled"},
            "reasoning_effort": self.args.effort,
            "max_tokens": self.args.max_tokens,
            "stream": False,
        }
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        timeout = max(1, min(120, int(self.remaining())))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:4000]
            raise DelegationError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DelegationError(f"DeepSeek API connection failed: {exc}") from exc
        if "error" in result:
            raise DelegationError(f"DeepSeek API error: {result['error']}")
        usage = result.get("usage")
        if isinstance(usage, dict):
            self.usage_by_call.append(usage)
        try:
            return result["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DelegationError("DeepSeek API returned no assistant message.") from exc

    def run(self, instruction: str) -> dict[str, Any]:
        system = (
            "你是 DeepSeek 执行方。严格按用户提供的指令文件工作，只做指令允许的事。"
            "所有文件操作必须留在项目根目录内；禁止读取凭据，禁止欺骗或伪造执行结果。"
            "需要工具时直接调用；工具失败就如实记录，不要绕过限制。"
            "最终用中文给出简洁回报：每步 PASS/FAIL、关键证据、改动文件、异常与不确定之处。"
        )
        user = f"项目根目录：{self.root}\n\n以下是指令文件全文：\n\n{instruction}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for _ in range(self.args.max_turns):
            self.check_time()
            message = self.call_api(messages)
            messages.append(message)
            calls = message.get("tool_calls") or []
            if calls:
                for call in calls:
                    self.check_time()
                    call_id = call.get("id", "")
                    function = call.get("function") or {}
                    name = function.get("name", "")
                    raw_arguments = function.get("arguments") or "{}"
                    try:
                        arguments = json.loads(raw_arguments)
                        if not isinstance(arguments, dict):
                            raise DelegationError("Tool arguments must be a JSON object.")
                        output = self.execute_tool(name, arguments)
                        self.events.append({"tool": name, "status": "ok", "arguments": self.safe_event_arguments(name, arguments)})
                    except Exception as exc:  # Return tool failures to the model without exposing secrets.
                        output = {"error": str(exc)}
                        self.events.append({"tool": name or "unknown", "status": "error", "error": str(exc)[:500]})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(output, ensure_ascii=False),
                    })
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return self.record("completed", content)
            raise DelegationError("DeepSeek returned neither tool calls nor a final report.")
        raise DelegationError(f"Maximum turns exceeded ({self.args.max_turns}).")

    @staticmethod
    def safe_event_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        safe = {key: value for key, value in arguments.items() if key not in {"content"}}
        if name == "write_file" and "content" in arguments:
            safe["content_characters"] = len(arguments["content"])
        return safe

    def totals(self) -> dict[str, int]:
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        return {key: sum(int(call.get(key, 0) or 0) for call in self.usage_by_call) for key in keys}

    def record(self, status: str, report: str) -> dict[str, Any]:
        return {
            "status": status,
            "model": self.args.model,
            "project": str(self.root),
            "duration_seconds": round(time.monotonic() - self.started, 3),
            "usage": self.totals(),
            "usage_by_call": self.usage_by_call,
            "tool_events": self.events,
            "report": report,
        }


def write_text_output(root: Path, value: str | None, content: str) -> None:
    if not value:
        return
    target = Path(value)
    target = (target if target.is_absolute() else root / target).resolve()
    target.relative_to(root)
    if ".git" in target.parts:
        raise DelegationError("Output inside .git is disabled.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.max_turns < 1 or args.timeout < 1 or args.max_tokens < 1:
        print(json.dumps({"status": "failed", "error": "max-turns, timeout and max-tokens must be positive."}, ensure_ascii=False))
        return 2
    runner: Runner | None = None
    try:
        runner = Runner(args)
        instruction_path = runner.path(args.instruction)
        if not instruction_path.is_file():
            raise DelegationError(f"Instruction file does not exist: {args.instruction}")
        instruction = instruction_path.read_text(encoding="utf-8")
        if len(instruction) > 200_000:
            raise DelegationError("Instruction file exceeds 200,000 characters.")
        result = runner.run(instruction)
        write_text_output(runner.root, args.report, result["report"] + "\n")
        write_text_output(runner.root, args.json_output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        error = str(exc)
        if runner is not None:
            result = runner.record("failed", f"FAIL：{error}")
            try:
                write_text_output(runner.root, args.report, result["report"] + "\n")
                write_text_output(runner.root, args.json_output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            except Exception:
                pass
        else:
            result = {"status": "failed", "error": error}
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
