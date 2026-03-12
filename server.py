from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
from io import BytesIO
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import zeep
from pypdf import PdfReader
from zeep.helpers import serialize_object
from zeep.settings import Settings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

DEFAULT_WSDL = "https://gtc.nn.pl/gtc/services/GtcServiceHttpPort?wsdl"
DEFAULT_CACHE_DIR = ".cache/gtc"


def _normalize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if hasattr(value, "__values__"):
        return _normalize(value.__values__)
    return value


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _resolve_doc_id(document: dict[str, Any]) -> str | None:
    for key in ("idBodyDoc", "idHeadDoc", "id", "documentId", "docId", "gtcId"):
        value = document.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_transport_security(
    host: str,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> TransportSecuritySettings | None:
    if allowed_hosts or allowed_origins:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts or [],
            allowed_origins=allowed_origins or [],
        )

    if host in ("127.0.0.1", "localhost", "::1"):
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        )

    return None


class GtcClient:
    def __init__(self, wsdl: str | None = None) -> None:
        self.wsdl = wsdl or os.getenv("GTC_WSDL", DEFAULT_WSDL)
        cache_dir = os.getenv("GTC_CACHE_DIR", DEFAULT_CACHE_DIR)
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @lru_cache(maxsize=1)
    def _soap_client(self) -> zeep.Client:
        return zeep.Client(self.wsdl, settings=Settings(xml_huge_tree=True))

    def _doc_cache_dir(self, doc_id: str) -> Path:
        path = self.cache_dir / "documents" / str(doc_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _doc_cache_paths(self, doc_id: str) -> tuple[Path, Path]:
        cache_dir = self._doc_cache_dir(doc_id)
        return cache_dir / "body.json", cache_dir / "document.bin"

    def _load_cached_doc(self, doc_id: str) -> dict[str, Any] | None:
        metadata_path, binary_path = self._doc_cache_paths(doc_id)
        if not metadata_path.exists() or not binary_path.exists():
            return None

        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        document_bytes = binary_path.read_bytes()
        return {
            "docId": payload["docId"],
            "fileName": payload["fileName"],
            "fileExtension": payload["fileExtension"],
            "documentBytes": document_bytes,
            "text": payload["text"],
            "cacheHit": True,
        }

    def _store_cached_doc(self, document: dict[str, Any]) -> dict[str, Any]:
        metadata_path, binary_path = self._doc_cache_paths(document["docId"])
        binary_path.write_bytes(document["documentBytes"])
        metadata_path.write_text(
            json.dumps(
                {
                    "docId": document["docId"],
                    "fileName": document["fileName"],
                    "fileExtension": document["fileExtension"],
                    "text": document["text"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        document["cacheHit"] = False
        return document

    def get_all_documents_metadata(self) -> list[dict[str, Any]]:
        response = self._soap_client().service.getAllGtcDocuments()
        result = _normalize(serialize_object(response.body["return"]))

        if result is None:
            return []
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            return [result]

        raise TypeError(f"Unexpected metadata response type: {type(result)!r}")

    def get_doc_body(self, doc_id: str) -> dict[str, Any]:
        cached = self._load_cached_doc(doc_id)
        if cached is not None:
            return cached

        response = self._soap_client().service.getGtcDocumentBody(doc_id)
        result = _normalize(serialize_object(response.body["return"]))

        if result is None:
            return self._store_cached_doc({
                "docId": doc_id,
                "fileName": None,
                "fileExtension": None,
                "documentBytes": b"",
                "text": "",
            })
        if isinstance(result, dict):
            document_bytes = result.get("document") or b""
            if not isinstance(document_bytes, bytes):
                if isinstance(document_bytes, str):
                    document_bytes = base64.b64decode(document_bytes)
                else:
                    document_bytes = bytes(document_bytes)
            return self._store_cached_doc({
                "docId": str(result.get("idBodyDoc", doc_id)),
                "fileName": result.get("fileName"),
                "fileExtension": result.get("fileExtension"),
                "documentBytes": document_bytes,
                "text": _extract_document_text(
                    file_extension=result.get("fileExtension"),
                    document_bytes=document_bytes,
                ),
            })

        if isinstance(result, str):
            return self._store_cached_doc({
                "docId": doc_id,
                "fileName": None,
                "fileExtension": "txt",
                "documentBytes": result.encode("utf-8"),
                "text": result,
            })

        text = json.dumps(result, ensure_ascii=False, indent=2)
        return self._store_cached_doc({
            "docId": doc_id,
            "fileName": None,
            "fileExtension": "json",
            "documentBytes": text.encode("utf-8"),
            "text": text,
        })


def _extract_document_text(file_extension: Any, document_bytes: bytes) -> str:
    extension = _as_string(file_extension).strip().lower()
    if not document_bytes:
        return ""
    if extension == "pdf":
        reader = PdfReader(BytesIO(document_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(page.strip() for page in pages if page.strip())
    return document_bytes.decode("utf-8", errors="replace")


gtc = GtcClient()
_default_host = os.getenv("MCP_HOST", "127.0.0.1")
_default_port = int(os.getenv("MCP_PORT", "8000"))
_default_streamable_http_path = os.getenv("MCP_STREAMABLE_HTTP_PATH", "/mcp")
_default_allowed_hosts = _split_csv(os.getenv("MCP_ALLOWED_HOSTS"))
_default_allowed_origins = _split_csv(os.getenv("MCP_ALLOWED_ORIGINS"))
mcp = FastMCP(
    "gtc-documents",
    host=_default_host,
    port=_default_port,
    streamable_http_path=_default_streamable_http_path,
    transport_security=_build_transport_security(
        _default_host,
        allowed_hosts=_default_allowed_hosts,
        allowed_origins=_default_allowed_origins,
    ),
)


def _matches_filters(
    document: dict[str, Any],
    filters: dict[str, Any],
    contains_match: bool,
) -> bool:
    for field, expected in filters.items():
        actual = document.get(field)

        if isinstance(expected, list):
            actual_value = _as_string(actual).lower()
            expected_values = {_as_string(item).lower() for item in expected}
            if actual_value not in expected_values:
                return False
            continue

        actual_value = _as_string(actual).lower()
        expected_value = _as_string(expected).lower()

        if contains_match:
            if expected_value not in actual_value:
                return False
        elif actual_value != expected_value:
            return False

    return True


def _sort_documents(
    documents: list[dict[str, Any]],
    sort_by: str | None,
    descending: bool,
) -> list[dict[str, Any]]:
    if not sort_by:
        return documents

    return sorted(
        documents,
        key=lambda document: _as_string(document.get(sort_by)).lower(),
        reverse=descending,
    )


def _filter_by_date_range(
    documents: list[dict[str, Any]],
    field: str,
    start_date: str | None,
    end_date: str | None,
) -> list[dict[str, Any]]:
    start = _parse_date(start_date)
    end = _parse_date(end_date)

    if start is None and end is None:
        return documents

    filtered: list[dict[str, Any]] = []
    for document in documents:
        raw_value = document.get(field)
        if raw_value in (None, ""):
            continue

        try:
            current = _parse_date(_as_string(raw_value))
        except ValueError:
            continue

        if current is None:
            continue
        if start is not None and current < start:
            continue
        if end is not None and current > end:
            continue
        filtered.append(document)

    return filtered


@mcp.tool()
def list_gtc_documents(
    filters: dict[str, Any] | None = None,
    contains_match: bool = True,
    sort_by: str | None = None,
    descending: bool = False,
    limit: int = 25,
) -> dict[str, Any]:
    """
    List document metadata with arbitrary field filters.
    """
    documents = gtc.get_all_documents_metadata()
    active_filters = filters or {}

    filtered = [
        document
        for document in documents
        if _matches_filters(document, active_filters, contains_match)
    ]
    filtered = _sort_documents(filtered, sort_by, descending)
    limited = filtered[: max(limit, 0)]

    return {
        "count": len(limited),
        "totalMatched": len(filtered),
        "documents": limited,
        "availableFields": sorted(
            {key for document in documents for key in document.keys()}
        ),
    }


@mcp.tool()
def search_gtc_documents(
    prod_code: str | None = None,
    component_code: str | None = None,
    type_name: str | None = None,
    withdrawn: int | None = None,
    effective_from: str | None = None,
    effective_to: str | None = None,
    modified_from: str | None = None,
    modified_to: str | None = None,
    as_of_date: str | None = None,
    exact_match: bool = False,
    sort_by: str = "dateFrom",
    descending: bool = True,
    limit: int = 25,
) -> dict[str, Any]:
    """
    Search document metadata using common GTC filters.

    Dates use ISO format, for example 2026-03-11.
    If `as_of_date` is set, only documents active on that date are returned.
    """
    documents = gtc.get_all_documents_metadata()
    filters: dict[str, Any] = {}
    if prod_code is not None:
        filters["prodCode"] = prod_code
    if component_code is not None:
        filters["componentCode"] = component_code
    if type_name is not None:
        filters["typeName"] = type_name
    if withdrawn is not None:
        filters["withdrawn"] = withdrawn

    filtered = [
        document
        for document in documents
        if _matches_filters(document, filters, contains_match=not exact_match)
    ]
    filtered = _filter_by_date_range(filtered, "dateFrom", effective_from, effective_to)
    filtered = _filter_by_date_range(filtered, "modDate", modified_from, modified_to)

    target_date = _parse_date(as_of_date)
    if target_date is not None:
        active: list[dict[str, Any]] = []
        for document in filtered:
            date_from = _parse_date(_as_string(document.get("dateFrom")))
            date_to = _parse_date(_as_string(document.get("dateTo")))
            if date_from and target_date < date_from:
                continue
            if date_to and target_date > date_to:
                continue
            active.append(document)
        filtered = active

    filtered = _sort_documents(filtered, sort_by, descending=descending)
    limited = filtered[: max(limit, 0)]

    return {
        "count": len(limited),
        "totalMatched": len(filtered),
        "documents": limited,
        "availableFields": sorted(
            {key for document in documents for key in document.keys()}
        ),
        "asOfDate": target_date.isoformat() if target_date else None,
    }


@mcp.tool()
def get_gtc_document(doc_id: str) -> dict[str, Any]:
    """
    Fetch a single document body.
    """
    document = gtc.get_doc_body(doc_id)
    return {
        "docId": document["docId"],
        "fileName": document["fileName"],
        "fileExtension": document["fileExtension"],
        "text": document["text"],
        "bytesLength": len(document["documentBytes"]),
        "cacheHit": document["cacheHit"],
    }


@mcp.tool()
def find_gtc_document_context(
    filters: dict[str, Any] | None = None,
    contains_match: bool = True,
    sort_by: str | None = None,
    descending: bool = False,
    limit: int = 5,
) -> str:
    """
    Return metadata and bodies for matching documents in a context-friendly format.
    """
    result = list_gtc_documents(
        filters=filters,
        contains_match=contains_match,
        sort_by=sort_by,
        descending=descending,
        limit=limit,
    )

    lines = [
        f"Matched documents: {result['totalMatched']}",
        f"Returned documents: {result['count']}",
    ]

    for document in result["documents"]:
        lines.append("")
        lines.append("Metadata:")
        lines.append(json.dumps(document, ensure_ascii=False, indent=2))

        doc_id = _resolve_doc_id(document)
        if doc_id:
            body = gtc.get_doc_body(doc_id)
            lines.append("")
            lines.append(f"Document: {body['fileName'] or doc_id}")
            lines.append("Body:")
            lines.append(body["text"])

    return "\n".join(lines)


@mcp.tool()
def diff_gtc_documents(
    left_doc_id: str,
    right_doc_id: str,
    context_lines: int = 3,
    max_diff_lines: int = 400,
) -> dict[str, Any]:
    """
    Compare two documents and return a unified diff of their extracted text.
    """
    left = gtc.get_doc_body(left_doc_id)
    right = gtc.get_doc_body(right_doc_id)

    left_lines = left["text"].splitlines()
    right_lines = right["text"].splitlines()
    diff_lines = list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=left["fileName"] or left_doc_id,
            tofile=right["fileName"] or right_doc_id,
            n=max(context_lines, 0),
            lineterm="",
        )
    )

    truncated = len(diff_lines) > max(max_diff_lines, 0)
    visible_diff_lines = diff_lines[: max(max_diff_lines, 0)]

    return {
        "left": {
            "docId": left["docId"],
            "fileName": left["fileName"],
            "fileExtension": left["fileExtension"],
            "bytesLength": len(left["documentBytes"]),
            "cacheHit": left["cacheHit"],
        },
        "right": {
            "docId": right["docId"],
            "fileName": right["fileName"],
            "fileExtension": right["fileExtension"],
            "bytesLength": len(right["documentBytes"]),
            "cacheHit": right["cacheHit"],
        },
        "leftLineCount": len(left_lines),
        "rightLineCount": len(right_lines),
        "diffLineCount": len(diff_lines),
        "truncated": truncated,
        "diff": "\n".join(visible_diff_lines),
    }


@mcp.resource("gtc://documents/{doc_id}")
def gtc_document_resource(doc_id: str) -> str:
    """
    Resource for a document body that can be attached directly as agent context.
    """
    document = gtc.get_doc_body(doc_id)
    return document["text"]


@mcp.resource("gtc://documents/{doc_id}/full")
def gtc_document_full_resource(doc_id: str) -> str:
    """
    Resource that includes both document metadata and the body.
    """
    metadata = gtc.get_all_documents_metadata()
    metadata_document = next(
        (item for item in metadata if _resolve_doc_id(item) == doc_id),
        None,
    )
    body = gtc.get_doc_body(doc_id)

    return json.dumps(
        {
            "docId": body["docId"],
            "metadata": metadata_document,
            "body": {
                "fileName": body["fileName"],
                "fileExtension": body["fileExtension"],
                "text": body["text"],
                "bytesLength": len(body["documentBytes"]),
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GTC MCP server.")
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", mcp.settings.host),
        help="Host interface for HTTP transports.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", str(mcp.settings.port))),
        help="Port for HTTP transports.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="MCP transport to use.",
    )
    parser.add_argument(
        "--mount-path",
        default=os.getenv("MCP_MOUNT_PATH"),
        help="Optional mount path for the SSE transport.",
    )
    parser.add_argument(
        "--streamable-http-path",
        default=os.getenv("MCP_STREAMABLE_HTTP_PATH", mcp.settings.streamable_http_path),
        help="HTTP path used for the streamable HTTP transport.",
    )
    parser.add_argument(
        "--allowed-hosts",
        default=os.getenv("MCP_ALLOWED_HOSTS"),
        help="Comma-separated Host header allowlist for HTTP transports.",
    )
    parser.add_argument(
        "--allowed-origins",
        default=os.getenv("MCP_ALLOWED_ORIGINS"),
        help="Comma-separated Origin header allowlist for HTTP transports.",
    )
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    if args.mount_path:
        mcp.settings.mount_path = args.mount_path
    mcp.settings.streamable_http_path = args.streamable_http_path
    mcp.settings.transport_security = _build_transport_security(
        args.host,
        allowed_hosts=_split_csv(args.allowed_hosts),
        allowed_origins=_split_csv(args.allowed_origins),
    )
    mcp.run(transport=args.transport, mount_path=args.mount_path)


if __name__ == "__main__":
    main()
