"""Run/score the Minnesota Shirley calibration set against an investigation output."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.loop import run_investigation  # noqa: E402
from config import DATA_DIR, OUTPUT_DIR  # noqa: E402


CASE_PATH = DATA_DIR / "mn_shirley_cases.json"
OUTPUT_CALIBRATION_DIR = OUTPUT_DIR / "calibration"

FLAG_KEYWORDS = (
    "flag",
    "high",
    "alarming",
    "suspicious",
    "concern",
    "impossib",
    "urgent",
    "risk level",
    "ghost provider",
    "closed",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_mn_result() -> Path | None:
    candidates: List[Path] = []
    for run_dir in OUTPUT_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        result_path = run_dir / "result.json"
        if not result_path.exists():
            continue
        try:
            payload = _load_json(result_path)
        except Exception:
            continue
        query = str(payload.get("query", ""))
        if "Minnesota" in query and "55407" in query:
            candidates.append(result_path)
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.parent.name, reverse=True)[0]


def _join_report_text(payload: Dict[str, Any]) -> str:
    parts = [
        str(payload.get("report_text") or ""),
        str(payload.get("narration") or ""),
        str(payload.get("assistant_text") or ""),
    ]
    return "\n".join(part for part in parts if part.strip())


def _flagged_structured(payload: Dict[str, Any], provider_name: str, address: str) -> bool:
    normalized_name = _normalize(provider_name)
    normalized_address = _normalize(address)
    for entry in payload.get("flagged", []) or []:
        provider = entry.get("provider", {}) if isinstance(entry, dict) else {}
        candidate_name = str(
            provider.get("name")
            or entry.get("provider_name")
            or provider.get("provider_name")
            or ""
        )
        candidate_address = str(entry.get("address") or provider.get("address") or "")
        if normalized_name and normalized_name in _normalize(candidate_name):
            return True
        if normalized_address and normalized_address in _normalize(candidate_address):
            return True
    return False


def _narrative_flagged(report_text: str, provider_name: str, address: str) -> tuple[bool, str]:
    text_lower = report_text.lower()
    needles = [provider_name.lower(), address.lower()]
    for needle in needles:
        if not needle.strip():
            continue
        idx = text_lower.find(needle)
        if idx < 0:
            continue
        left = max(0, idx - 900)
        right = min(len(text_lower), idx + 900)
        window = text_lower[left:right]
        if any(keyword in window for keyword in FLAG_KEYWORDS):
            snippet = report_text[left:right].replace("\n", " ").strip()
            return True, snippet[:280]
    return False, ""


def _score_cases(payload: Dict[str, Any], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    report_text = _join_report_text(payload)
    case_results: List[Dict[str, Any]] = []

    expected_true = 0
    detected_true = 0

    for case in cases:
        provider_name = str(case.get("provider_name") or "")
        address = str(case.get("address") or "")
        expected_flag = bool(case.get("expected_flag", True))

        structured_hit = _flagged_structured(payload, provider_name, address)
        narrative_hit, snippet = _narrative_flagged(report_text, provider_name, address)
        detected = structured_hit or narrative_hit

        if expected_flag:
            expected_true += 1
            if detected:
                detected_true += 1

        reasons: List[str] = []
        if structured_hit:
            reasons.append("matched structured flagged[] payload")
        if narrative_hit:
            reasons.append("matched risk-context in report/narration")
        if not reasons:
            reasons.append("not found with risk context")

        case_results.append(
            {
                "id": case.get("id"),
                "provider_name": provider_name,
                "address": address,
                "expected_flag": expected_flag,
                "detected": detected,
                "reasons": reasons,
                "context_snippet": snippet,
            }
        )

    detection_rate = (detected_true / expected_true) if expected_true else 0.0
    return {
        "total_cases": len(cases),
        "expected_true_cases": expected_true,
        "detected_true_cases": detected_true,
        "detection_rate": detection_rate,
        "cases": case_results,
    }


def _write_outputs(report: Dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "mn_shirley_calibration_latest.json"
    md_path = output_dir / "mn_shirley_calibration_latest.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines: List[str] = [
        "# MN Shirley Calibration",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Source result: `{report['source_result']}`",
        f"- Query: `{report['query']}`",
        f"- Detection: **{report['detected_true_cases']}/{report['expected_true_cases']}**",
        f"- Detection rate: **{report['detection_rate']:.2%}**",
        f"- Target threshold: **{report['target_threshold']:.2%}**",
        f"- Passed: **{'YES' if report['passed'] else 'NO'}**",
        "",
        "| Case | Expected | Detected | Provider | Address |",
        "|---|---:|---:|---|---|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['id']} | {str(case['expected_flag']).upper()} | "
            f"{str(case['detected']).upper()} | {case['provider_name']} | {case['address']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score MN Shirley calibration cases.")
    parser.add_argument(
        "--source-result",
        default="",
        help="Path to a result.json file. If omitted, the latest Minnesota ZIP 55407 run is used.",
    )
    parser.add_argument(
        "--rerun-query",
        action="store_true",
        help="Run a fresh investigation query instead of reading an existing result file.",
    )
    parser.add_argument(
        "--query",
        default="Investigate Minnesota providers in ZIP 55407",
        help="Query used when --rerun-query is enabled.",
    )
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--threshold",
        type=float,
        default=(8 / 9),
        help="Minimum detection-rate threshold to consider calibration as passed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    calibration_cases = _load_json(CASE_PATH).get("cases", [])
    if not calibration_cases:
        raise RuntimeError(f"No calibration cases found in {CASE_PATH}")

    source_label = ""
    if args.rerun_query:
        result_payload = run_investigation(
            args.query,
            max_turns=args.max_turns,
            offline=args.offline,
        )
        source_label = f"run_investigation(query={args.query!r}, max_turns={args.max_turns}, offline={args.offline})"
    else:
        source_path = Path(args.source_result) if args.source_result else _latest_mn_result()
        if not source_path or not source_path.exists():
            raise RuntimeError(
                "No source result found. Provide --source-result or run with --rerun-query."
            )
        result_payload = _load_json(source_path)
        try:
            source_label = str(source_path.resolve().relative_to(ROOT_DIR.resolve()))
        except ValueError:
            source_label = str(source_path)

    scores = _score_cases(result_payload, calibration_cases)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_result": source_label,
        "query": result_payload.get("query", ""),
        "target_threshold": args.threshold,
        "passed": scores["detection_rate"] >= args.threshold,
        **scores,
    }

    json_path, md_path = _write_outputs(report, OUTPUT_CALIBRATION_DIR)
    print(f"Calibration report written: {json_path}")
    print(f"Calibration summary written: {md_path}")
    print(
        f"Detection: {report['detected_true_cases']}/{report['expected_true_cases']} "
        f"({report['detection_rate']:.2%}) | passed={report['passed']}"
    )


if __name__ == "__main__":
    main()
