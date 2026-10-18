import io
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image


class PageStore:
	def __init__(self, database_path):
		self.database_path = Path(database_path)
		self.database_path.parent.mkdir(parents=True, exist_ok=True)
		with self._connect() as connection:
			connection.executescript(
				"""
				CREATE TABLE IF NOT EXISTS documents (
					session_id TEXT PRIMARY KEY,
					source_pdf BLOB NOT NULL,
					updated_at REAL NOT NULL
				);
				CREATE TABLE IF NOT EXISTS pages (
					session_id TEXT NOT NULL,
					page_index INTEGER NOT NULL,
					original BLOB NOT NULL,
					edited BLOB NOT NULL,
					PRIMARY KEY (session_id, page_index),
					FOREIGN KEY (session_id) REFERENCES documents(session_id)
						ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS history (
					session_id TEXT NOT NULL,
					page_index INTEGER NOT NULL,
					kind TEXT NOT NULL,
					position INTEGER NOT NULL,
					image BLOB NOT NULL,
					PRIMARY KEY (session_id, page_index, kind, position),
					FOREIGN KEY (session_id, page_index)
						REFERENCES pages(session_id, page_index) ON DELETE CASCADE
				);
				CREATE TABLE IF NOT EXISTS settings (
					key TEXT PRIMARY KEY,
					value TEXT NOT NULL
				);
				"""
			)

	def get_or_create_secret_key(self):
		with self._connect() as connection:
			connection.execute(
				"INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
				("flask_secret_key", secrets.token_hex(32)),
			)
			row = connection.execute(
				"SELECT value FROM settings WHERE key = ?", ("flask_secret_key",)
			).fetchone()
		return row[0]

	@contextmanager
	def _connect(self):
		connection = sqlite3.connect(self.database_path, timeout=30)
		connection.execute("PRAGMA foreign_keys = ON")
		try:
			yield connection
			connection.commit()
		except Exception:
			connection.rollback()
			raise
		finally:
			connection.close()

	@staticmethod
	def _encode_image(image):
		buffer = io.BytesIO()
		image.save(buffer, format="PNG")
		return buffer.getvalue()

	@staticmethod
	def _decode_image(image_bytes):
		with Image.open(io.BytesIO(image_bytes)) as image:
			return image.convert("RGB")

	def reset(self, session_id, source_pdf, pages):
		encoded_pages = [self._encode_image(page) for page in pages]
		now = time.time()
		with self._connect() as connection:
			connection.execute(
				"DELETE FROM documents WHERE updated_at < ?", (now - 7 * 86400,)
			)
			connection.execute(
				"""INSERT INTO documents (session_id, source_pdf, updated_at)
				   VALUES (?, ?, ?)
				   ON CONFLICT(session_id) DO UPDATE SET
					   source_pdf = excluded.source_pdf,
					   updated_at = excluded.updated_at""",
				(session_id, source_pdf, now),
			)
			connection.execute("DELETE FROM pages WHERE session_id = ?", (session_id,))
			connection.executemany(
				"""INSERT INTO pages (session_id, page_index, original, edited)
				   VALUES (?, ?, ?, ?)""",
				[
					(session_id, index, image, image)
					for index, image in enumerate(encoded_pages)
				],
			)

	def source_pdf(self, session_id):
		with self._connect() as connection:
			row = connection.execute(
				"SELECT source_pdf FROM documents WHERE session_id = ?",
				(session_id,),
			).fetchone()
		if row is None:
			raise KeyError("No PDF is loaded for this session.")
		return row[0]

	def pages(self, session_id, kind="edited"):
		if kind not in {"original", "edited"}:
			raise ValueError("Unknown page collection.")
		with self._connect() as connection:
			rows = connection.execute(
				f"SELECT {kind} FROM pages WHERE session_id = ? ORDER BY page_index",
				(session_id,),
			).fetchall()
		return [self._decode_image(row[0]) for row in rows]

	def page(self, session_id, page_index, kind="edited"):
		if kind not in {"original", "edited"}:
			raise ValueError("Unknown page collection.")
		with self._connect() as connection:
			row = connection.execute(
				f"SELECT {kind} FROM pages WHERE session_id = ? AND page_index = ?",
				(session_id, page_index),
			).fetchone()
		if row is None:
			raise IndexError("Page does not exist.")
		return self._decode_image(row[0])

	def set_page(self, session_id, page_index, image):
		with self._connect() as connection:
			result = connection.execute(
				"""UPDATE pages SET edited = ?
				   WHERE session_id = ? AND page_index = ?""",
				(self._encode_image(image), session_id, page_index),
			)
			if result.rowcount == 0:
				raise IndexError("Page does not exist.")
			connection.execute(
				"UPDATE documents SET updated_at = ? WHERE session_id = ?",
				(time.time(), session_id),
			)

	def _push_history(self, connection, session_id, page_index, kind, image, limit):
		row = connection.execute(
			"""SELECT COALESCE(MAX(position), -1) + 1 FROM history
			   WHERE session_id = ? AND page_index = ? AND kind = ?""",
			(session_id, page_index, kind),
		).fetchone()
		connection.execute(
			"""INSERT INTO history (session_id, page_index, kind, position, image)
			   VALUES (?, ?, ?, ?, ?)""",
			(session_id, page_index, kind, row[0], self._encode_image(image)),
		)
		excess = connection.execute(
			"""SELECT position FROM history
			   WHERE session_id = ? AND page_index = ? AND kind = ?
			   ORDER BY position DESC LIMIT -1 OFFSET ?""",
			(session_id, page_index, kind, limit),
		).fetchall()
		if excess:
			connection.executemany(
				"""DELETE FROM history
				   WHERE session_id = ? AND page_index = ? AND kind = ? AND position = ?""",
				[(session_id, page_index, kind, item[0]) for item in excess],
			)

	def push_undo(self, session_id, page_index, limit):
		with self._connect() as connection:
			row = connection.execute(
				"SELECT edited FROM pages WHERE session_id = ? AND page_index = ?",
				(session_id, page_index),
			).fetchone()
			if row is None:
				raise IndexError("Page does not exist.")
			self._push_history(connection, session_id, page_index, "undo", self._decode_image(row[0]), limit)
			connection.execute(
				"DELETE FROM history WHERE session_id = ? AND page_index = ? AND kind = 'redo'",
				(session_id, page_index),
			)

	def _restore(self, session_id, page_index, source_kind, target_kind, limit):
		with self._connect() as connection:
			current = connection.execute(
				"SELECT edited FROM pages WHERE session_id = ? AND page_index = ?",
				(session_id, page_index),
			).fetchone()
			if current is None:
				raise IndexError("Page does not exist.")
			previous = connection.execute(
				"""SELECT position, image FROM history
				   WHERE session_id = ? AND page_index = ? AND kind = ?
				   ORDER BY position DESC LIMIT 1""",
				(session_id, page_index, source_kind),
			).fetchone()
			if previous is None:
				return self._decode_image(current[0])
			self._push_history(
				connection, session_id, page_index, target_kind,
				self._decode_image(current[0]), limit,
			)
			connection.execute(
				"UPDATE pages SET edited = ? WHERE session_id = ? AND page_index = ?",
				(previous[1], session_id, page_index),
			)
			connection.execute(
				"""DELETE FROM history
				   WHERE session_id = ? AND page_index = ? AND kind = ? AND position = ?""",
				(session_id, page_index, source_kind, previous[0]),
			)
			connection.execute(
				"UPDATE documents SET updated_at = ? WHERE session_id = ?",
				(time.time(), session_id),
			)
			return self._decode_image(previous[1])

	def undo(self, session_id, page_index, limit):
		return self._restore(session_id, page_index, "undo", "redo", limit)

	def redo(self, session_id, page_index, limit):
		return self._restore(session_id, page_index, "redo", "undo", limit)
