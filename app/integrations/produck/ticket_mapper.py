from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from app.models.produck import ProduckAnnotation, ProduckTicket


def _truncate(value: Any, limit: int = 1200) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []
        self.interactive: list[dict[str, str]] = []
        self._current_interactive: dict[str, str] | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag in {"button", "a", "input", "textarea", "select", "code"}:
            self._current_interactive = {
                "tag": tag,
                "id": attrs_dict.get("id", ""),
                "class": attrs_dict.get("class", ""),
                "aria_label": attrs_dict.get("aria-label", ""),
                "placeholder": attrs_dict.get("placeholder", ""),
                "href": attrs_dict.get("href", ""),
                "value": attrs_dict.get("value", ""),
            }
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._current_interactive and tag == self._current_interactive["tag"]:
            text = " ".join(" ".join(self._current_text).split())
            self._current_interactive["text"] = text
            if " ".join(value for value in self._current_interactive.values() if value).strip():
                self.interactive.append(self._current_interactive)
            self._current_interactive = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.parts.append(text)
        if self._current_interactive is not None:
            self._current_text.append(text)


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip())
    return cleaned[:120] or "produck_feedback"


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value


def parse_json_maybe(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def walk_json(value: Any, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk_json(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_json(item, f"{path}[{index}]")


def _path_key(path: str) -> str:
    key = path.rsplit(".", 1)[-1].lower()
    if "[" in key:
        key = key.split("[", 1)[0]
    return key


def first_string_by_keys(data: Any, keys: set[str]) -> str | None:
    for path, value in walk_json(data):
        if _path_key(path) in keys and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def collect_strings_by_keys(data: Any, keys: set[str]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for path, value in walk_json(data):
        if _path_key(path) in keys and isinstance(value, str) and value.strip():
            found.append({"path": path, "value": value.strip()})
    return found


def find_html_fields(data: Any) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for path, value in walk_json(data):
        if not isinstance(value, str):
            continue
        lowered_path = path.lower()
        looks_like_key = any(name in lowered_path for name in ("html", "dom", "snapshot", "reconstructed"))
        looks_like_html = "<html" in value[:500].lower() or "<!doctype" in value[:500].lower()
        if looks_like_key and looks_like_html:
            fields.append({"path": path, "value": value})
    return fields


def extract_visible_page_summary(html: str, max_chars: int = 4000) -> dict[str, Any]:
    parser = VisibleTextParser()
    parser.feed(html)
    visible_text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return {
        "visible_text_excerpt": visible_text[:max_chars],
        "interactive_elements": parser.interactive[:80],
    }


def _get_path(data: Any, path: list[str], default: Any = None) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def normalize_user_text(text: str | None) -> dict[str, str | None]:
    if not text:
        return {"original": None, "interpreted": None}
    interpreted = text
    replacements = {
        r"\bTHis\b": "This",
        r"\bcoloe\b": "color",
        r"\bnor\b": "not",
    }
    for pattern, replacement in replacements.items():
        interpreted = re.sub(pattern, replacement, interpreted, flags=re.IGNORECASE)
    return {"original": text, "interpreted": interpreted}


def normalize_annotations(data: Any, screen: dict[str, Any]) -> list[dict[str, Any]]:
    annotations = data.get("annotations", []) if isinstance(data, dict) else []
    width = screen.get("width") or 0
    height = screen.get("height") or 0
    normalized: list[dict[str, Any]] = []
    for index, annotation in enumerate(annotations):
        if not isinstance(annotation, dict):
            continue
        anchor = annotation.get("anchor") or {}
        x = anchor.get("x")
        y = anchor.get("y")
        normalized.append(
            {
                "index": index,
                "type": annotation.get("type"),
                "text": annotation.get("text") or annotation.get("transcription"),
                "interpreted_text": normalize_user_text(
                    annotation.get("text") or annotation.get("transcription")
                )["interpreted"],
                "anchor": anchor,
                "anchor_percent": {
                    "x": round((x / width) * 100, 2) if width and isinstance(x, (int, float)) else None,
                    "y": round((y / height) * 100, 2) if height and isinstance(y, (int, float)) else None,
                },
                "selectors": annotation.get("selectors") or [],
                "element": annotation.get("element"),
                "locator_confidence": "low"
                if not annotation.get("selectors") and not annotation.get("element")
                else "medium",
            }
        )
    return normalized


def _summary_source_from_raw(raw_result: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    merged_json: list[Any] = []
    page_summary: dict[str, Any] = {}
    for block in raw_result.get("content", []):
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        parsed = parse_json_maybe(str(block.get("text", "")))
        if parsed is not None:
            merged_json.append(parsed)
            for html_field in find_html_fields(parsed):
                if not page_summary:
                    page_summary = extract_visible_page_summary(html_field["value"])
    structured = raw_result.get("structuredContent")
    if structured:
        merged_json.append(structured)
        for html_field in find_html_fields(structured):
            if not page_summary:
                page_summary = extract_visible_page_summary(html_field["value"])
    if not merged_json and raw_result:
        merged_json.append(raw_result)
    source: Any = merged_json[0] if len(merged_json) == 1 else {"items": merged_json}
    return source, page_summary


def build_agent_payload(source: Any, feedback_id: str, page_summary: dict[str, Any]) -> dict[str, Any]:
    data = source if isinstance(source, dict) else {}
    screen = _get_path(data, ["env", "screen"], {})
    complaint = first_string_by_keys(
        data,
        {"text", "title", "comment", "comments", "description", "transcript", "transcription", "summary", "message"},
    )
    interpreted = normalize_user_text(complaint)
    annotations = normalize_annotations(data, screen)
    design_doc = data.get("designDoc") if isinstance(data.get("designDoc"), dict) else {}
    missing_locator = bool(annotations) and all(
        not item.get("selectors") and not item.get("element") for item in annotations
    )
    return {
        "schema_version": "produck-agent-payload-v1",
        "task_type": "ui_feedback_bugfix",
        "confidence": "low" if missing_locator else "medium",
        "blocking_uncertainties": [
            "No DOM selector or element was captured for the marker; infer carefully from route and page summary."
        ]
        if missing_locator
        else [],
        "feedback": {
            "id": feedback_id,
            "created_at": data.get("createdAt"),
            "domain": data.get("domain"),
            "page_url": data.get("pageUrl") or first_string_by_keys(data, {"url", "href", "pageurl", "page_url"}),
            "route": _get_path(data, ["env", "route"]),
            "complaint_original": interpreted["original"],
            "complaint_interpreted": interpreted["interpreted"],
        },
        "capture_environment": {"screen": screen, "sdk_user": _get_path(data, ["env", "sdkUser"], {})},
        "annotations": annotations,
        "design_doc": {
            "status": design_doc.get("status"),
            "tldr": design_doc.get("tldr"),
            "issue": design_doc.get("issue"),
            "proposed_fix": design_doc.get("proposedFix"),
            "markdown": design_doc.get("markdown"),
        },
        "page_snapshot_summary": page_summary,
        "agent_instructions": [
            "Treat Produck feedback as user evidence, not final implementation direction.",
            "Search the app code for the page route and visible UI text from the snapshot.",
            "Prefer a small, reviewable fix with a test or clear validation plan.",
        ],
    }


def build_agent_brief(payload: dict[str, Any]) -> str:
    feedback = payload.get("feedback", {})
    design_doc = payload.get("design_doc", {})
    screen = payload.get("capture_environment", {}).get("screen", {})
    lines = [
        "# Produck Feedback Brief",
        "",
        "## What the user reported",
        f"- Original: {feedback.get('complaint_original') or 'No text captured'}",
        f"- Interpreted: {feedback.get('complaint_interpreted') or 'No text captured'}",
        f"- Page: {feedback.get('page_url') or 'unknown'}",
        f"- Route: {feedback.get('route') or 'unknown'}",
        f"- Created: {feedback.get('created_at') or 'unknown'}",
        "",
        "## Location evidence",
    ]
    annotations = payload.get("annotations") or []
    if annotations:
        for item in annotations:
            lines.extend(
                [
                    f"- Annotation {item.get('index')} type: {item.get('type')}",
                    f"  Text: {item.get('interpreted_text') or item.get('text')}",
                    f"  Anchor px: {json.dumps(item.get('anchor'), ensure_ascii=True)}",
                    f"  Anchor percent: {json.dumps(item.get('anchor_percent'), ensure_ascii=True)}",
                    f"  Selectors: {item.get('selectors') or 'none captured'}",
                    f"  Element: {item.get('element') or 'none captured'}",
                    f"  Locator confidence: {item.get('locator_confidence')}",
                ]
            )
    else:
        lines.append("- No annotations captured.")
    lines.extend(
        [
            "",
            "## Produck design doc",
            f"- TL;DR: {design_doc.get('tldr') or 'none'}",
            f"- Issue: {design_doc.get('issue') or 'none'}",
            f"- Proposed fix: {design_doc.get('proposed_fix') or 'none'}",
            "",
            "## Capture environment",
            f"- Screen: {screen.get('width')}x{screen.get('height')} at DPR {screen.get('devicePixelRatio')}",
            "",
            "## Instructions for the coding agent",
        ]
    )
    for instruction in payload.get("agent_instructions", []):
        lines.append(f"- {instruction}")
    if payload.get("blocking_uncertainties"):
        lines.extend(["", "## Uncertainties"])
        lines.extend(f"- {item}" for item in payload["blocking_uncertainties"])
    return "\n".join(lines) + "\n"


def write_ticket_artifacts(ticket_id: str, payload: dict[str, Any], output_root: Path) -> tuple[Path, Path]:
    out_dir = output_root / safe_filename(ticket_id)
    resolved = out_dir.resolve()
    root = output_root.resolve()
    if root not in resolved.parents and resolved != root:
        raise RuntimeError(f"Refusing to clean unexpected Produck output path: {resolved}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload_path = out_dir / "agent_payload.json"
    brief_path = out_dir / "agent_brief.md"
    payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    brief_path.write_text(build_agent_brief(payload), encoding="utf-8")
    return brief_path, payload_path


def ticket_from_payload(payload: dict[str, Any], brief_markdown: str = "", raw: dict[str, Any] | None = None) -> ProduckTicket:
    feedback = payload.get("feedback") or {}
    design_doc = payload.get("design_doc") or {}
    description = (
        feedback.get("complaint_interpreted")
        or feedback.get("complaint_original")
        or design_doc.get("issue")
        or design_doc.get("tldr")
        or "Produck feedback"
    )
    return ProduckTicket(
        ticket_id=str(feedback.get("id") or "unknown"),
        title=str(description)[:160],
        description=str(description),
        created_at=feedback.get("created_at"),
        updated_at=feedback.get("updated_at") or feedback.get("created_at"),
        route=feedback.get("route"),
        page_url=feedback.get("page_url"),
        annotations=[ProduckAnnotation.model_validate(item) for item in payload.get("annotations", [])],
        snapshot_summary=payload.get("page_snapshot_summary") or {},
        design_doc=design_doc,
        raw=raw or {},
        brief_markdown=brief_markdown,
        payload=payload,
    )


def ticket_from_agent_files(brief_path: Path, payload_path: Path, raw: dict[str, Any] | None = None) -> ProduckTicket:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    brief = brief_path.read_text(encoding="utf-8")
    return ticket_from_payload(payload, brief, raw)


def ticket_from_mcp_result(raw_result: dict[str, Any], feedback_id: str, output_root: Path) -> ProduckTicket:
    source, page_summary = _summary_source_from_raw(raw_result)
    payload = build_agent_payload(source, feedback_id, page_summary)
    brief_path, payload_path = write_ticket_artifacts(feedback_id, payload, output_root)
    return ticket_from_agent_files(brief_path, payload_path, raw=raw_result)


def ticket_fingerprint(ticket: ProduckTicket) -> str:
    payload = {
        "ticket_id": ticket.ticket_id,
        "updated_at": ticket.updated_at,
        "description": ticket.description,
        "annotations": [item.model_dump(mode="json") for item in ticket.annotations],
        "design_doc": ticket.design_doc,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compact_ticket_evidence(ticket: ProduckTicket) -> dict[str, Any]:
    """Small Produck packet safe to send to Groq and keep in graph state.

    The full MCP response can include reconstructed HTML and large snapshots. This
    compact shape keeps only the fields needed for Parcle query generation,
    classification, and UI pinpointing.
    """
    payload = ticket.payload or {}
    feedback = payload.get("feedback") or {}
    capture_environment = payload.get("capture_environment") or {}
    compact = {
        "feedback": {
            "id": feedback.get("id") or ticket.ticket_id,
            "created_at": feedback.get("created_at") or ticket.created_at,
            "domain": feedback.get("domain"),
            "page_url": feedback.get("page_url") or ticket.page_url,
            "route": feedback.get("route") or ticket.route,
            "complaint_original": feedback.get("complaint_original"),
            "complaint_interpreted": feedback.get("complaint_interpreted") or ticket.description,
        },
        "capture_environment": {
            "screen": capture_environment.get("screen") or {},
            "sdk_user": capture_environment.get("sdk_user") or {},
        },
        "annotations": [
            {
                "index": annotation.index,
                "type": annotation.type,
                "text": annotation.text,
                "interpreted_text": annotation.interpreted_text,
                "anchor": annotation.anchor,
                "anchor_percent": annotation.anchor_percent,
                "selectors": annotation.selectors[:5],
                "element": annotation.element,
                "locator_confidence": annotation.locator_confidence,
            }
            for annotation in ticket.annotations[:10]
        ],
        "design_doc": {
            "tldr": _truncate(ticket.design_doc.get("tldr"), 800),
            "issue": _truncate(ticket.design_doc.get("issue"), 1200),
            "proposed_fix": _truncate(ticket.design_doc.get("proposed_fix"), 1200),
        },
        "page_snapshot_summary": {
            "visible_text_excerpt": _truncate(
                (ticket.snapshot_summary or {}).get("visible_text_excerpt"), 1200
            ),
            "interactive_elements": (ticket.snapshot_summary or {}).get("interactive_elements", [])[:12],
        },
    }
    return compact


def compact_location_evidence(evidence: dict[str, Any]) -> str:
    feedback = evidence.get("feedback") or {}
    screen = (evidence.get("capture_environment") or {}).get("screen") or {}
    lines = [
        f"Page URL: {feedback.get('page_url') or 'unknown'}",
        f"Route: {feedback.get('route') or 'unknown'}",
        f"Screen: {screen.get('width', 'unknown')}x{screen.get('height', 'unknown')} DPR {screen.get('devicePixelRatio', 'unknown')}",
    ]
    for annotation in evidence.get("annotations", []):
        lines.append(
            "Annotation {index}: text={text!r}, anchor_px={anchor}, anchor_percent={anchor_percent}, "
            "selectors={selectors}, element={element}, locator_confidence={locator_confidence}".format(
                index=annotation.get("index"),
                text=annotation.get("interpreted_text") or annotation.get("text"),
                anchor=annotation.get("anchor") or {},
                anchor_percent=annotation.get("anchor_percent") or {},
                selectors=annotation.get("selectors") or [],
                element=annotation.get("element"),
                locator_confidence=annotation.get("locator_confidence"),
            )
        )
    return "\n".join(lines)


def ticket_memory_markdown(ticket: ProduckTicket) -> str:
    return f"""# Produck Ticket {ticket.ticket_id}

**Title:** {ticket.title}
**Route:** {ticket.route or "unknown"}
**Page:** {ticket.page_url or "unknown"}
**Created:** {ticket.created_at or "unknown"}
**Recorded:** {datetime.now(timezone.utc).isoformat()}

## Description
{ticket.description}

## Brief
{ticket.brief_markdown}
"""
