#!/usr/bin/env python3
"""Run aesthetic-v4 scoring directly on an image file or directory."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import build_image_manifest


DEFAULT_CASE_IMAGE_NAME = "card.dsl.png"
DEFAULT_MODEL_PROVIDER = "minimax"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
            os.environ.setdefault(key, value)
    return values


def resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def run_command(command: list[str], *, cwd: Path) -> None:
    print(" ".join(shlex.quote(part) for part in command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def shell_quote(value: str | Path) -> str:
    text = str(value)
    if os.name == "nt":
        return subprocess.list2cmdline([text])
    return shlex.quote(text)


def provider_env_name(provider: str, suffix: str) -> str:
    normalized = provider.strip().upper().replace("-", "_")
    return f"{normalized}_{suffix}"


def resolve_model_provider(args: argparse.Namespace, env_path: Path) -> dict[str, str]:
    provider = args.model_provider.strip().lower().replace("-", "_")
    prefix = provider.upper()
    api_url_env = provider_env_name(provider, "API_URL")
    api_key_env = provider_env_name(provider, "API_KEY")
    model_env = provider_env_name(provider, "MODEL")
    api_url = os.environ.get(api_url_env)
    api_key = os.environ.get(api_key_env)
    model = os.environ.get(model_env)
    missing = [
        name
        for name, value in (
            (api_url_env, api_url),
            (api_key_env, api_key),
            (model_env, model),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            f"model provider '{provider}' is missing {', '.join(missing)}; add them to {env_path}"
        )
    return {
        "provider": provider,
        "prefix": prefix,
        "api_url": str(api_url),
        "api_key_env": api_key_env,
        "model": str(model),
    }


def build_judge_command(args: argparse.Namespace, scripts_dir: Path) -> str:
    provider_config = resolve_model_provider(args, Path(args._env_path))
    prompt_version = os.environ.get("PANGU_JUDGE_PROMPT_VERSION", "aesthetic-v4")
    output_mode = "score-only" if args.score_only else os.environ.get("PANGU_JUDGE_OUTPUT_MODE", "full")
    timeout = os.environ.get("PANGU_JUDGE_TIMEOUT", "240")
    max_tokens = os.environ.get("PANGU_JUDGE_MAX_TOKENS", "64" if output_mode == "score-only" else "1200")
    judge_script = scripts_dir / "pangu_rubric_judge.py"
    parts = [
        sys.executable,
        str(judge_script),
        "--base-url",
        provider_config["api_url"],
        "--api-key-env",
        provider_config["api_key_env"],
        "--model",
        provider_config["model"],
        "--prompt-version",
        prompt_version,
        "--output-mode",
        output_mode,
        "--timeout",
        timeout,
        "--max-tokens",
        max_tokens,
    ]
    return " ".join(shell_quote(part) for part in parts)


def write_summary(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    scripts_dir = Path(__file__).resolve().parent
    pipeline_dir = scripts_dir.parent
    repo_root = pipeline_dir.parent

    env_parser = argparse.ArgumentParser(add_help=False)
    env_parser.add_argument("--env-file", default="config/aesthetic-v4.env")
    env_args, _unknown = env_parser.parse_known_args()
    env_path = resolve_path(env_args.env_file, repo_root)
    load_env_file(env_path)

    parser = argparse.ArgumentParser(description=__doc__, parents=[env_parser])
    parser.add_argument("input", nargs="?", default="a2ui_png", help="Image file or directory.")
    parser.add_argument("--run-dir", default="runs/a2ui-images", help="Output run directory.")
    parser.add_argument(
        "--case-image-name",
        default=os.environ.get("AESTHETIC_V4_CASE_IMAGE_NAME", DEFAULT_CASE_IMAGE_NAME),
        help="Evaluate only this image file inside each direct case subdirectory.",
    )
    parser.add_argument("--all-images", action="store_true", help="Recursively evaluate all supported images.")
    parser.add_argument("--backend", choices=["model", "mock"], default=os.environ.get("AESTHETIC_V4_BACKEND", "model"))
    parser.add_argument(
        "--model-provider",
        default=os.environ.get("AESTHETIC_V4_MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER),
        help=(
            "OpenAI-compatible provider prefix from env, e.g. minimax reads "
            "MINIMAX_API_URL/MINIMAX_API_KEY/MINIMAX_MODEL; doubao reads "
            "DOUBAO_API_URL/DOUBAO_API_KEY/DOUBAO_MODEL."
        ),
    )
    parser.add_argument("--workers", type=int, default=int(os.environ.get("AESTHETIC_V4_WORKERS", "1")))
    parser.add_argument("--judge-retries", type=int, default=int(os.environ.get("AESTHETIC_JUDGE_RETRIES", "3")))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true", help="Skip ids already present in scores.jsonl.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached image scores.")
    parser.add_argument("--score-only", action="store_true", help="Ask the model for score-only JSON.")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("AESTHETIC_V4_SCORE_TIMEOUT", "300")))
    parser.add_argument(
        "--adaptive-viewports",
        choices=["off", "on", "auto"],
        default=os.environ.get("AESTHETIC_V4_ADAPTIVE_VIEWPORTS", "off"),
    )
    parser.add_argument(
        "--score-breakdown",
        choices=["off", "on"],
        default=os.environ.get("AESTHETIC_V4_SCORE_BREAKDOWN", "on"),
    )
    parser.add_argument(
        "--designer-review",
        choices=["off", "on"],
        default=os.environ.get("AESTHETIC_V4_DESIGNER_REVIEW", "off"),
    )
    args = parser.parse_args()
    args._env_path = str(env_path)

    input_path = resolve_path(args.input, Path.cwd())
    run_dir = resolve_path(args.run_dir, repo_root)
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = run_dir / "manifest.jsonl"
    manifest_summary_path = run_dir / "manifest.summary.json"
    scores_path = run_dir / "scores.jsonl"
    cache_path = run_dir / "score_cache.jsonl"
    report_path = run_dir / "report.html"
    csv_path = run_dir / "scores.csv"
    report_summary_path = run_dir / "report.summary.json"
    run_summary_path = run_dir / "run.summary.json"

    case_image_name = None if args.all_images else args.case_image_name
    records = build_image_manifest.build_records(input_path, case_image_name=case_image_name)
    if not records:
        raise SystemExit("no supported images found")
    build_image_manifest.write_jsonl(records, manifest_path)
    write_summary(
        manifest_summary_path,
        {
            "profile": "aesthetic-v4",
            "input": str(input_path),
            "out": str(manifest_path),
            "records": len(records),
            "case_image_name": case_image_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if scores_path.exists() and not args.resume:
        scores_path.unlink()

    score_cmd = [
        sys.executable,
        str(scripts_dir / "score_images_streaming.py"),
        "--input",
        str(manifest_path),
        "--out",
        str(scores_path),
        "--cache",
        str(cache_path),
        "--anchors",
        str(pipeline_dir / "anchors" / "anchors.jsonl"),
        "--workers",
        str(args.workers),
        "--adaptive-viewports",
        args.adaptive_viewports,
        "--score-breakdown",
        args.score_breakdown,
        "--designer-review",
        args.designer_review,
        "--timeout",
        str(args.timeout),
        "--judge-retries",
        str(args.judge_retries),
    ]
    if args.limit > 0:
        score_cmd.extend(["--limit", str(args.limit)])
    if args.resume:
        score_cmd.append("--resume")
    if args.refresh:
        score_cmd.append("--refresh")
    if args.backend == "mock":
        score_cmd.extend(["--backend", "mock"])
    else:
        provider_config = resolve_model_provider(args, env_path)
        score_cmd.extend(["--backend", "command", "--judge-command", build_judge_command(args, scripts_dir)])

    run_command(score_cmd, cwd=repo_root)

    report_cmd = [
        sys.executable,
        str(scripts_dir / "build_aesthetic_v4_report.py"),
        "--scores",
        str(scores_path),
        "--out",
        str(report_path),
        "--csv",
        str(csv_path),
        "--summary",
        str(report_summary_path),
    ]
    run_command(report_cmd, cwd=repo_root)

    write_summary(
        run_summary_path,
        {
            "profile": "aesthetic-v4",
            "input": str(input_path),
            "run_dir": str(run_dir),
            "backend": args.backend,
            "model_provider": provider_config["provider"] if args.backend == "model" else "mock",
            "model": provider_config["model"] if args.backend == "model" else "mock",
            "records": len(records),
            "case_image_name": case_image_name,
            "manifest": str(manifest_path),
            "scores": str(scores_path),
            "csv": str(csv_path),
            "report": str(report_path),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    print(json.dumps({"report": str(report_path), "csv": str(csv_path), "scores": str(scores_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
