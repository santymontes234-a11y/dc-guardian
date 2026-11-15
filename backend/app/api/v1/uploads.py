"""In-memory multipart parsing for biometric uploads.

Why not ``UploadFile``: FastAPI reads multipart bodies *before* resolving the auth dependencies,
and Starlette spools every file part larger than 1 MB to a temporary file on disk. That would
(1) let anonymous clients push large bodies to disk before getting a 401 and (2) write face
images to disk, which this module promises never to do.

Endpoints using this helper declare no body parameters, so authentication runs first; the
body is then streamed with hard limits and kept in memory only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Request
from python_multipart.multipart import MultipartParser, parse_options_header

from app.core.config import get_settings
from app.core.errors import DomainError

MAX_FIELD_BYTES = 1024
HEADER_ALLOWANCE = 64 * 1024  # boundaries, part headers, small text fields


@dataclass
class _Part:
    headers: dict[bytes, bytes] = field(default_factory=dict)
    name: str = ""
    filename: str | None = None
    data: bytearray = field(default_factory=bytearray)


@dataclass
class ParsedForm:
    files: list[tuple[str | None, bytes]]
    fields: dict[str, str]


def _too_large(limit: int) -> DomainError:
    return DomainError("PAYLOAD_TOO_LARGE", f"El envío supera el tamaño máximo ({limit // (1024 * 1024)} MB)", 413)


async def read_images(request: Request, file_field: str, max_files: int) -> ParsedForm:
    per_file = get_settings().image_max_bytes
    total_limit = max_files * per_file + HEADER_ALLOWANCE

    ctype, params = parse_options_header(request.headers.get("content-type", ""))
    boundary = params.get(b"boundary")
    if ctype != b"multipart/form-data" or not boundary:
        raise DomainError("MULTIPART_REQUIRED", "Se esperaba multipart/form-data", 415)
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            raise DomainError("BAD_REQUEST", "Content-Length inválido", 400)
        if int(declared) > total_limit:
            raise _too_large(total_limit)

    parts: list[_Part] = []
    current: dict = {}

    def on_part_begin():
        current["part"] = _Part()
        current["hf"] = bytearray()
        current["hv"] = bytearray()

    def on_header_field(data, start, end):
        current["hf"] += data[start:end]

    def on_header_value(data, start, end):
        current["hv"] += data[start:end]

    def on_header_end():
        current["part"].headers[bytes(current["hf"]).lower()] = bytes(current["hv"])
        current["hf"], current["hv"] = bytearray(), bytearray()

    def on_headers_finished():
        part = current["part"]
        _, disp = parse_options_header(part.headers.get(b"content-disposition", b""))
        part.name = disp.get(b"name", b"").decode("utf-8", "replace")
        fn = disp.get(b"filename")
        part.filename = fn.decode("utf-8", "replace")[:120] if fn is not None else None
        if part.filename is not None and part.name != file_field:
            raise DomainError("UNEXPECTED_FILE", "Campo de archivo no esperado", 422)
        if part.filename is not None and sum(p.filename is not None for p in parts) >= max_files:
            raise DomainError("TOO_MANY_IMAGES", f"Máximo {max_files} imágenes por envío", 422)
        if len(parts) >= max_files + 5:
            raise DomainError("TOO_MANY_FIELDS", "Demasiados campos en el formulario", 422)

    def on_part_data(data, start, end):
        part = current["part"]
        part.data += data[start:end]
        cap = per_file if part.filename is not None else MAX_FIELD_BYTES
        if len(part.data) > cap:
            if part.filename is not None:
                raise DomainError("IMAGE_TOO_LARGE", f"La imagen supera {per_file // (1024 * 1024)} MB", 413)
            raise DomainError("FIELD_TOO_LARGE", "Campo de formulario demasiado grande", 413)

    def on_part_end():
        parts.append(current.pop("part"))

    parser = MultipartParser(boundary, {
        "on_part_begin": on_part_begin, "on_header_field": on_header_field, "on_header_value": on_header_value,
        "on_header_end": on_header_end, "on_headers_finished": on_headers_finished,
        "on_part_data": on_part_data, "on_part_end": on_part_end,
    })
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > total_limit:  # also covers chunked bodies without Content-Length
                raise _too_large(total_limit)
            parser.write(chunk)
        parser.finalize()
    except DomainError:
        raise
    except Exception as exc:  # malformed multipart
        raise DomainError("BAD_MULTIPART", "Formulario multipart mal formado", 400) from exc

    files = [(p.filename, bytes(p.data)) for p in parts if p.filename is not None]
    fields = {p.name: p.data.decode("utf-8", "replace") for p in parts if p.filename is None}
    return ParsedForm(files=files, fields=fields)
