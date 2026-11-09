#!/usr/bin/env python3
"""Unified local server for ClipScribe static assets and clip preparation API."""
from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "clips" / "manifest.json"
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov"}
MAX_CONCURRENT_REQUESTS = 16


def bootstrap_venv() -> None:
    """Run this server with project dependencies even when launched as python3."""
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file() and Path(sys.executable).absolute() != venv_python.absolute():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


def project_python() -> str:
    venv_python = ROOT / ".venv" / "bin" / "python"
    return str(venv_python if venv_python.is_file() else Path(sys.executable))


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "clip"


def log_step(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] [ClipScribe] {message}", flush=True)


def run_streaming(command: list[str]) -> list[str]:
    """Forward child output immediately while retaining a concise error tail."""
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        lines.append(line.rstrip())
        if len(lines) > 40:
            lines.pop(0)
    return_code = process.wait()
    if return_code:
        detail = next((line for line in reversed(lines) if line.strip()), f"Processo falhou ({return_code})")
        raise RuntimeError(detail)
    return lines


class ClipScribeHandler(SimpleHTTPRequestHandler):
    """Static handler with byte-range video delivery and two same-origin APIs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args):
        sys.stderr.write("[ClipScribe] " + (format % args) + "\n")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/clips":
            return self.send_manifest()
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            return None
        return super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/api/update-segment":
            return self.update_segment()
        if route == "/api/slice-episode":
            return self.slice_episode()
        if route != "/api/prepare-clip":
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint não encontrado")
            return
        try:
            fields, uploaded = self.read_request_data()
            title = str(fields.get("title", "")).strip()
            if not title:
                if uploaded: uploaded[1].unlink(missing_ok=True)
                raise ValueError("title é obrigatório")
            input_path, temporary_path = self.resolve_input(fields, uploaded)
            try:
                entry = self.prepare_clip(input_path, fields, title)
            finally:
                if temporary_path:
                    temporary_path.unlink(missing_ok=True)
            self.send_json(HTTPStatus.CREATED, {"clip": entry})
        except (ValueError, RuntimeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:  # Keeps expensive tool failures from returning HTML traces.
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Falha inesperada: {error}"})

    def update_segment(self):
        """Atomically rewrite a clip's subtitle pair from edited segment data."""
        try:
            fields, uploaded = self.read_request_data()
            if uploaded:
                raise ValueError("A edição de legendas aceita apenas JSON.")
            clip_id = str(fields.get("clipId", "")).strip()
            segments = fields.get("segments")
            if not clip_id or not isinstance(segments, list):
                raise ValueError("clipId e segments são obrigatórios.")
            subtitle_path = self.subtitle_path_for_clip(clip_id)
            clean_segments = self.validate_segments(segments)
            self.write_subtitle_pair(subtitle_path, clean_segments)
            self.send_json(HTTPStatus.OK, {"ok": True, "segments": clean_segments})
        except (ValueError, RuntimeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Falha ao salvar correção: {error}"})

    def slice_episode(self):
        try:
            fields, uploaded = self.read_request_data(); title = str(fields.get("seriesTitle") or fields.get("title") or "").strip()
            if not title:
                if uploaded: uploaded[1].unlink(missing_ok=True)
                raise ValueError("seriesTitle é obrigatório")
            input_path, temporary_video = self.resolve_input(fields, uploaded); transcript = str(fields.get("referenceTranscript") or "")
            temporary_transcript = None
            try:
                if transcript.strip():
                    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as handle:
                        handle.write(transcript); temporary_transcript = Path(handle.name)
                command = [project_python(), str(ROOT / "scripts" / "slice_episode.py"), "--input", str(input_path), "--title", title, "--target-seconds", str(fields.get("targetChunkSeconds") or "120"), "--model", str(fields.get("model") or "base.en")]
                if temporary_transcript: command += ["--transcript-file", str(temporary_transcript)]
                run_streaming(command)
            finally:
                if temporary_video: temporary_video.unlink(missing_ok=True)
                if temporary_transcript: temporary_transcript.unlink(missing_ok=True)
            group_id = slugify(title); data = json.loads(MANIFEST.read_text(encoding="utf-8")); clips = [clip for clip in data.get("clips", []) if clip.get("groupId") == group_id]
            self.send_json(HTTPStatus.CREATED, {"clips": clips, "groupId": group_id})
        except (ValueError, RuntimeError) as error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Falha ao fatiar episódio: {error}"})

    def send_manifest(self):
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"clips": []}
        except json.JSONDecodeError as error:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Manifest inválido: {error}"})
            return
        self.send_json(HTTPStatus.OK, data)

    def subtitle_path_for_clip(self, clip_id: str) -> Path:
        try:
            clips = json.loads(MANIFEST.read_text(encoding="utf-8")).get("clips", [])
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise RuntimeError("Manifesto não disponível.") from error
        clip = next((item for item in clips if item.get("id") == clip_id), None)
        if not clip:
            raise ValueError("Clipe não encontrado no manifesto.")
        relative = Path(str(clip.get("subtitleUrl", "")))
        path = (ROOT / relative).resolve()
        clips_root = (ROOT / "clips").resolve()
        if path.suffix.lower() != ".vtt" or clips_root not in path.parents:
            raise ValueError("Somente arquivos VTT dentro de clips/ podem ser editados.")
        return path

    def validate_segments(self, segments: list[object]) -> list[dict[str, object]]:
        clean: list[dict[str, object]] = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise ValueError(f"Segmento {index + 1} inválido.")
            text = str(segment.get("text", "")).strip()
            try:
                start = float(segment.get("startTime")); end = float(segment.get("endTime"))
            except (TypeError, ValueError) as error:
                raise ValueError(f"Timestamps inválidos no segmento {index + 1}.") from error
            if not text or start < 0 or end <= start:
                raise ValueError(f"Dados inválidos no segmento {index + 1}.")
            clean.append({"id": index + 1, "startTime": round(start, 3), "endTime": round(end, 3), "text": text})
        if not clean:
            raise ValueError("A legenda precisa ter ao menos um segmento.")
        return clean

    @staticmethod
    def subtitle_timestamp(seconds: float, separator: str = ".") -> str:
        total = max(0, round(seconds * 1000)); hours, total = divmod(total, 3_600_000); minutes, total = divmod(total, 60_000); secs, milliseconds = divmod(total, 1000)
        return f"{hours:02}:{minutes:02}:{secs:02}{separator}{milliseconds:03}"

    def write_subtitle_pair(self, vtt_path: Path, segments: list[dict[str, object]]) -> None:
        vtt_lines = ["WEBVTT", ""]
        srt_lines: list[str] = []
        for index, segment in enumerate(segments, start=1):
            start = float(segment["startTime"]); end = float(segment["endTime"]); text = str(segment["text"])
            vtt_lines += [f"{self.subtitle_timestamp(start)} --> {self.subtitle_timestamp(end)}", text, ""]
            srt_lines += [str(index), f"{self.subtitle_timestamp(start, ',')} --> {self.subtitle_timestamp(end, ',')}", text, ""]
        self.atomic_write(vtt_path, "\n".join(vtt_lines))
        srt_path = vtt_path.with_suffix(".srt")
        if srt_path.exists():
            self.atomic_write(srt_path, "\n".join(srt_lines))

    @staticmethod
    def atomic_write(path: Path, content: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=path.suffix) as handle:
            handle.write(content); temporary = Path(handle.name)
        temporary.replace(path)

    def send_json(self, status: HTTPStatus, data: object):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_request_data(self) -> tuple[dict[str, object], tuple[str, Path] | None]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_UPLOAD_BYTES:
            raise ValueError("Envie um corpo JSON ou vídeo com até 4 GB.")
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            if length > MAX_JSON_BYTES:
                raise ValueError("O JSON deve ter no máximo 16 MB; para vídeos, use multipart/form-data.")
            body = self.rfile.read(length)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("JSON inválido") from error
            if not isinstance(payload, dict):
                raise ValueError("O JSON deve ser um objeto")
            return payload, None
        if content_type.startswith("multipart/form-data"):
            fields: dict[str, object] = {}
            upload: tuple[str, Path] | None = None
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(length)},
                keep_blank_values=True,
            )
            for part in form.list or []:
                if not part.name:
                    continue
                if part.filename:
                    suffix = Path(part.filename).suffix.lower()
                    if suffix not in VIDEO_SUFFIXES:
                        raise ValueError("O upload precisa ser um vídeo suportado (.mp4, .webm, .mkv ou .mov).")
                    descriptor, temporary_name = tempfile.mkstemp(prefix="clipscribe-upload-", suffix=suffix)
                    temporary = Path(temporary_name)
                    with os.fdopen(descriptor, "wb") as destination:
                        shutil.copyfileobj(part.file, destination, length=1024 * 1024)
                    if upload:
                        upload[1].unlink(missing_ok=True)
                    upload = (part.filename, temporary)
                else:
                    fields[part.name] = part.value
            return fields, upload
        raise ValueError("Use application/json ou multipart/form-data.")

    def resolve_input(self, fields: dict[str, object], uploaded: tuple[str, Path] | None) -> tuple[Path, Path | None]:
        if uploaded:
            _filename, temporary = uploaded
            return temporary, temporary
        value = str(fields.get("inputPath", "")).strip()
        source = Path(value).expanduser()
        if not value or not source.is_file():
            raise ValueError("Informe um caminho local válido ou envie um arquivo de vídeo.")
        return source.resolve(), None

    def prepare_clip(self, source: Path, fields: dict[str, object], title: str) -> dict[str, object]:
        model = str(fields.get("model") or "base.en")
        max_words = str(fields.get("maxWords") or "18")
        try:
            if int(max_words) < 1:
                raise ValueError
        except ValueError as error:
            raise ValueError("maxWords deve ser um número positivo") from error
        command = [project_python(), str(ROOT / "scripts" / "prepare_clip.py"), "--input", str(source), "--title", title, "--model", model, "--max-words", max_words]
        for request_name, argument in (("start", "--start"), ("end", "--end")):
            value = str(fields.get(request_name) or "").strip()
            if value:
                command += [argument, value]
        run_streaming(command)
        try:
            clips = json.loads(MANIFEST.read_text(encoding="utf-8")).get("clips", [])
        except (FileNotFoundError, json.JSONDecodeError) as error:
            raise RuntimeError("O processamento terminou sem um manifesto válido.") from error
        clip_id = slugify(title)
        entry = next((clip for clip in clips if clip.get("id") == clip_id), None)
        if not entry:
            raise RuntimeError("O novo clipe não foi encontrado no manifesto.")
        return entry

    def send_head(self):
        """Implement RFC 7233 single-range responses for browser video seeking."""
        path = self.translate_path(self.path)
        if Path(path).suffix.lower() not in VIDEO_SUFFIXES or not os.path.isfile(path):
            return super().send_head()
        file = open(path, "rb")
        size = os.fstat(file.fileno()).st_size
        range_header = self.headers.get("Range")
        if not range_header:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers(); self._range_length = None
            return file
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match:
            file.close(); self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE); return None
        start_text, end_text = match.groups()
        if not start_text and not end_text:
            file.close(); self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE); return None
        if start_text:
            start = int(start_text); end = int(end_text) if end_text else size - 1
        else:
            suffix = int(end_text); start = max(0, size - suffix); end = size - 1
        if start >= size or end < start:
            file.close(); self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return None
        end = min(end, size - 1); length = end - start + 1; file.seek(start)
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.end_headers(); self._range_length = length
        return file

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_range_length", None)
        try:
            if remaining is None:
                return shutil.copyfileobj(source, outputfile)
            while remaining > 0:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            # Browsers routinely cancel an obsolete byte-range request after a
            # seek or metadata probe. The next 206 request continues playback.
            return None


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Prevent rapid Range cancellations from creating unbounded threads."""

    daemon_threads = True

    def __init__(self, *args, max_workers: int = MAX_CONCURRENT_REQUESTS, **kwargs):
        self._request_slots = threading.BoundedSemaphore(max_workers)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        self._request_slots.acquire()
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor local unificado do ClipScribe")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = BoundedThreadingHTTPServer((args.host, args.port), ClipScribeHandler)
    log_step(f"ClipScribe em http://{args.host}:{args.port} — Ctrl+C para encerrar")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    bootstrap_venv()
    main()
