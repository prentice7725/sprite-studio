# SPDX-License-Identifier: MIT
"""Translate engine JSON into operator-friendly QA records."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schemas import QaIssue


_FRAME_RE = re.compile(r"frame\s+(\d+)", re.IGNORECASE)


def _issue(state: str, text: str, severity: str) -> QaIssue:
    lowered = text.lower()
    if "sparse" in lowered:
        code, action = "SPARSE_FRAME", "원본을 재생성하거나 Row Normalize를 실행하세요."
    elif "larger than median" in lowered or "outlier" in lowered:
        code, action = "FRAME_SIZE_OUTLIER", "해당 프레임을 확인하고 필요하면 재생성하세요."
    elif "missing" in lowered:
        code, action = "MISSING_ROW", "Generate를 실행하세요."
    else:
        code, action = "EXTRACT_WARNING", "Review 탭에서 결과를 확인하세요."
    match = _FRAME_RE.search(text)
    return QaIssue(severity, state, int(match.group(1)) if match else None, code, text, action)


def load_qa(run_dir: Path, state: str | None = None) -> list[QaIssue]:
    manifest_path = run_dir / "frames" / "frames-manifest.json"
    failure_path = run_dir / "extract-failure.json"
    issues: list[QaIssue] = []
    payloads = []
    if manifest_path.is_file():
        try:
            payloads.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            issues.append(QaIssue("error", state or "", None, "INVALID_MANIFEST", "frames manifest를 읽을 수 없습니다.", "Extract를 다시 실행하세요."))
    if failure_path.is_file():
        try:
            payloads.append(json.loads(failure_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    for payload in payloads:
        for severity, key in (("error", "errors"), ("warning", "warnings")):
            for text in payload.get(key, []):
                text = str(text)
                row_state = state or text.split(":", 1)[0]
                if state and row_state != state and not text.startswith(f"{state}:"):
                    continue
                issues.append(_issue(row_state, text, severity))
    animation_dir = run_dir / "studio" / "qa"
    if animation_dir.is_dir():
        reports = [animation_dir / f"{state}.animation.json"] if state else sorted(animation_dir.glob("*.animation.json"))
        for report_path in reports:
            if not report_path.is_file():
                continue
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            row_state = str(payload.get("state") or report_path.stem.split(".", 1)[0])
            for warning in payload.get("warnings", []):
                if isinstance(warning, dict):
                    code = str(warning.get("code", "ANIMATION_QA"))
                    message = str(warning.get("message", code))
                    action = "Frame Refine 후 다시 검사하거나 Review에서 해당 프레임을 교체하세요."
                    issues.append(QaIssue("warning", row_state, warning.get("frame"), code, message, action))
    frames_dir = run_dir / "frames"
    if frames_dir.is_dir():
        for proposals_path in frames_dir.rglob("repair/repair.proposals.json"):
            try:
                proposals = json.loads(proposals_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            row_state = str(proposals.get("state") or "")
            if state and row_state != state:
                continue
            log_path = proposals_path.with_name("repair.log.json")
            try:
                repair_log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {}
            except json.JSONDecodeError:
                repair_log = {}
            decisions_path = proposals_path.with_name("repair.decisions.json")
            try:
                decisions = json.loads(decisions_path.read_text(encoding="utf-8")) if decisions_path.is_file() else {}
            except json.JSONDecodeError:
                decisions = {}
            applied = {str(change.get("candidate_id")) for change in repair_log.get("changes", [])}
            rejected = {str(candidate_id) for candidate_id in decisions.get("rejected", [])}
            thresholds = (proposals.get("profile") or {}).get("safe_thresholds") or {}
            for candidate in proposals.get("candidates", []):
                threshold = float(thresholds.get(str(candidate.get("type")), 1.01))
                candidate_id = str(candidate.get("id"))
                if candidate.get("protected") or float(candidate.get("confidence", 0)) < threshold:
                    continue
                if candidate_id in applied or candidate_id in rejected:
                    continue
                issues.append(QaIssue(
                    "warning", row_state, int(candidate.get("frame", 0)),
                    "UNRESOLVED_REPAIR_CANDIDATE",
                    f"{row_state} frame {candidate.get('frame')}: unresolved {candidate.get('type')} "
                    f"candidate ({float(candidate.get('confidence', 0)):.2f}).",
                    "Repair 탭에서 후보를 적용하거나 검토 후 거부하세요.",
                ))
    return issues


def summary(run_dir: Path, state: str | None = None) -> str:
    issues = load_qa(run_dir, state)
    if not issues:
        return "✓ QA PASS — 현재 보고된 문제가 없습니다."
    lines = [f"{'✕' if issue.severity == 'error' else '⚠'} {issue.message}" for issue in issues]
    return "\n".join(lines)
