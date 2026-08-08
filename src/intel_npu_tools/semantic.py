"""Private local semantic indexing backed by OpenVINO's NPU embedding pipeline."""

import argparse
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import openvino_genai as ov_genai

from .paths import EMBEDDING_MODEL, SEMANTIC_DB


TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".css", ".csv", ".go", ".h", ".hpp", ".html",
    ".ini", ".java", ".js", ".json", ".jsx", ".log", ".md", ".php",
    ".py", ".rb", ".rs", ".rst", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".txt", ".xml", ".yaml", ".yml",
}
SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
    "dist", "build", "models",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
QUERY_INSTRUCTION = "Given a search query, retrieve relevant passages from the user's local files"

_pipeline = None
_pipeline_lock = threading.RLock()


def embedding_pipeline():
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            if not EMBEDDING_MODEL.is_dir():
                raise FileNotFoundError(
                    f"Embedding model not found at {EMBEDDING_MODEL}; run scripts/download-models.py"
                )
            config = ov_genai.TextEmbeddingPipeline.Config()
            config.max_length = 512
            config.pad_to_max_length = True
            config.batch_size = 1
            config.pooling_type = ov_genai.TextEmbeddingPipeline.PoolingType.LAST_TOKEN
            config.normalize = True
            config.padding_side = "left"
            config.query_instruction = f"Instruct: {QUERY_INSTRUCTION}\nQuery:"
            # The Ubuntu NPU packages provide the compiler through the driver.
            _pipeline = ov_genai.TextEmbeddingPipeline(
                str(EMBEDDING_MODEL), "NPU", config, NPU_COMPILER_TYPE="DRIVER"
            )
    return _pipeline


def chunk_text(text: str, target_chars: int = 1600, overlap_lines: int = 2) -> list[tuple[int, int, str]]:
    """Split text on line boundaries and return (start_line, end_line, content)."""
    lines = text.splitlines()
    chunks = []
    start = 0
    while start < len(lines):
        end = start
        size = 0
        while end < len(lines) and (size < target_chars or end == start):
            size += len(lines[end]) + 1
            end += 1
        content = "\n".join(lines[start:end]).strip()
        if content:
            chunks.append((start + 1, end, content))
        if end >= len(lines):
            break
        start = max(start + 1, end - overlap_lines)
    return chunks


def iter_text_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        candidates = [root]
    else:
        candidates = root.rglob("*")
    for path in candidates:
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.parts):
            continue
        try:
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= MAX_FILE_BYTES:
                yield path.resolve()
        except OSError:
            continue


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY, root TEXT NOT NULL, mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL, digest TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL, start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL, content TEXT NOT NULL, vector BLOB NOT NULL,
            dimensions INTEGER NOT NULL, FOREIGN KEY(path) REFERENCES files(path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
        """
    )
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


class SemanticIndex:
    def __init__(self, db_path: Path = SEMANTIC_DB, pipeline_factory: Callable = embedding_pipeline):
        self.db_path = Path(db_path)
        self.pipeline_factory = pipeline_factory

    def index(self, value: str) -> dict:
        root = Path(value).expanduser().resolve()
        if not root.exists():
            raise ValueError(f"Path does not exist: {root}")
        files = list(iter_text_files(root))
        updated = skipped = chunks_added = 0
        with _connect(self.db_path) as db:
            for path in files:
                stat = path.stat()
                row = db.execute("SELECT mtime_ns, size FROM files WHERE path=?", (str(path),)).fetchone()
                if row == (stat.st_mtime_ns, stat.st_size):
                    skipped += 1
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                pieces = chunk_text(text)
                if not pieces:
                    continue
                vectors = []
                pipe = self.pipeline_factory()
                for _, _, content in pieces:
                    vector = np.asarray(pipe.embed_documents([content])[0], dtype=np.float32)
                    vectors.append(vector)
                digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
                db.execute("DELETE FROM chunks WHERE path=?", (str(path),))
                db.execute(
                    "INSERT OR REPLACE INTO files(path,root,mtime_ns,size,digest) VALUES(?,?,?,?,?)",
                    (str(path), str(root), stat.st_mtime_ns, stat.st_size, digest),
                )
                db.executemany(
                    "INSERT INTO chunks(path,start_line,end_line,content,vector,dimensions) VALUES(?,?,?,?,?,?)",
                    [
                        (str(path), start, end, content, vector.tobytes(), vector.size)
                        for (start, end, content), vector in zip(pieces, vectors)
                    ],
                )
                updated += 1
                chunks_added += len(pieces)
        return {
            "root": str(root), "files_seen": len(files), "files_updated": updated,
            "files_unchanged": skipped, "chunks_added": chunks_added, "device": "NPU",
        }

    def search(self, query: str, limit: int = 5, root: str | None = None) -> list[dict]:
        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty")
        limit = max(1, min(int(limit), 20))
        vector = np.asarray(self.pipeline_factory().embed_query(query), dtype=np.float32)
        sql = "SELECT path,start_line,end_line,content,vector,dimensions FROM chunks"
        params = []
        if root:
            resolved = str(Path(root).expanduser().resolve())
            sql += " WHERE path=? OR path LIKE ?"
            params.extend((resolved, resolved.rstrip("/") + "/%"))
        results = []
        with _connect(self.db_path) as db:
            for path, start, end, content, blob, dimensions in db.execute(sql, params):
                candidate = np.frombuffer(blob, dtype=np.float32, count=dimensions)
                if candidate.size != vector.size:
                    continue
                score = float(np.dot(vector, candidate))
                results.append({
                    "score": round(score, 6), "path": path, "start_line": start,
                    "end_line": end, "text": content,
                })
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def status(self) -> dict:
        with _connect(self.db_path) as db:
            files = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            roots = [row[0] for row in db.execute("SELECT DISTINCT root FROM files ORDER BY root")]
        return {"database": str(self.db_path), "files": files, "chunks": chunks, "roots": roots}


def main():
    parser = argparse.ArgumentParser(description="Private semantic search using Intel AI Boost")
    sub = parser.add_subparsers(dest="command", required=True)
    index_parser = sub.add_parser("index", help="Index a text file or directory")
    index_parser.add_argument("path")
    search_parser = sub.add_parser("search", help="Search indexed text")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=5)
    search_parser.add_argument("--root")
    sub.add_parser("status", help="Show index statistics")
    args = parser.parse_args()
    index = SemanticIndex()
    if args.command == "index":
        result = index.index(args.path)
    elif args.command == "search":
        result = index.search(args.query, args.limit, args.root)
    else:
        result = index.status()
    print(json.dumps(result, indent=2, ensure_ascii=False))
