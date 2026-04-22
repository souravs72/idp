# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Unit tests for :mod:`idp.core.security` (Phase 14)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _reload_security(monkeypatch, frappe_stub):  # noqa: ARG001
	import idp.core.security as security

	importlib.reload(security)
	return security


# ---------------------------------------------------------------------------
# detect_mime_by_magic
# ---------------------------------------------------------------------------


def test_detect_pdf_magic(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert sec.detect_mime_by_magic(b"%PDF-1.7\n...") == "application/pdf"


def test_detect_png_magic(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	png_head = b"\x89PNG\r\n\x1a\n" + b"more-payload"
	assert sec.detect_mime_by_magic(png_head) == "image/png"


def test_detect_jpeg_variants(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert sec.detect_mime_by_magic(b"\xff\xd8\xff\xe0junk") == "image/jpeg"
	assert sec.detect_mime_by_magic(b"\xff\xd8\xff\xe1junk") == "image/jpeg"


def test_detect_unknown_returns_none(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert sec.detect_mime_by_magic(b"garbage bytes") is None
	assert sec.detect_mime_by_magic(b"") is None


# ---------------------------------------------------------------------------
# verify_file_type
# ---------------------------------------------------------------------------


def test_verify_file_type_happy_path(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert sec.verify_file_type(b"%PDF-1.7") == "application/pdf"


def test_verify_file_type_mismatch_raises(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	from idp.core.exceptions import SecurityError

	with pytest.raises(SecurityError):
		sec.verify_file_type(b"%PDF-1.7", expected_mime="image/png")


def test_verify_file_type_unknown_raises(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	from idp.core.exceptions import SecurityError

	with pytest.raises(SecurityError):
		sec.verify_file_type(b"\x00\x01\x02\x03\x04")


def test_verify_file_type_unsupported_mime(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	from idp.core.exceptions import SecurityError

	# GIF is recognised but not in SUPPORTED_MIME_TYPES → should raise.
	with pytest.raises(SecurityError):
		sec.verify_file_type(b"GIF89a" + b"\x00" * 10)


# ---------------------------------------------------------------------------
# assert_safe_file_url / is_safe_file_url
# ---------------------------------------------------------------------------


def _stub_site_path(monkeypatch, tmp_path):
	"""Make ``frappe.get_site_path`` return *tmp_path*."""
	import idp.core.security as security

	monkeypatch.setattr(security.frappe, "get_site_path", lambda: str(tmp_path))
	return tmp_path


def test_is_safe_accepts_private_and_public(frappe_stub, monkeypatch, tmp_path):
	sec = _reload_security(monkeypatch, frappe_stub)
	root = _stub_site_path(monkeypatch, tmp_path)
	(root / "private" / "files").mkdir(parents=True)
	(root / "public" / "files").mkdir(parents=True)
	assert sec.is_safe_file_url("/private/files/invoice.pdf") is True
	assert sec.is_safe_file_url("/files/public-invoice.pdf") is True


def test_is_safe_rejects_traversal(frappe_stub, monkeypatch, tmp_path):
	sec = _reload_security(monkeypatch, frappe_stub)
	_stub_site_path(monkeypatch, tmp_path)
	assert sec.is_safe_file_url("/private/files/../../../etc/passwd") is False


def test_is_safe_rejects_unknown_root(frappe_stub, monkeypatch, tmp_path):
	sec = _reload_security(monkeypatch, frappe_stub)
	_stub_site_path(monkeypatch, tmp_path)
	assert sec.is_safe_file_url("/random/path.pdf") is False
	assert sec.is_safe_file_url("") is False
	assert sec.is_safe_file_url(None) is False  # type: ignore[arg-type]


def test_assert_safe_returns_resolved_path(frappe_stub, monkeypatch, tmp_path):
	sec = _reload_security(monkeypatch, frappe_stub)
	root = _stub_site_path(monkeypatch, tmp_path)
	(root / "private" / "files").mkdir(parents=True)
	resolved = sec.assert_safe_file_url("/private/files/inv.pdf")
	assert Path(resolved).is_relative_to(root / "private" / "files")


# ---------------------------------------------------------------------------
# assert_user_can_read
# ---------------------------------------------------------------------------


def test_permission_allowed(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	monkeypatch.setattr(sec.frappe, "has_permission", lambda **_k: True)
	# Should not raise.
	sec.assert_user_can_read("Purchase Invoice")


def test_permission_denied(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	from idp.core.exceptions import SecurityError

	monkeypatch.setattr(sec.frappe, "has_permission", lambda **_k: False)
	with pytest.raises(SecurityError):
		sec.assert_user_can_read("Purchase Invoice")


def test_permission_exception_is_wrapped(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	from idp.core.exceptions import SecurityError

	def boom(**_k):
		raise RuntimeError("db broken")

	monkeypatch.setattr(sec.frappe, "has_permission", boom)
	with pytest.raises(SecurityError):
		sec.assert_user_can_read("Purchase Invoice")


# ---------------------------------------------------------------------------
# sanitize_string
# ---------------------------------------------------------------------------


def test_sanitize_string_strips_controls(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert sec.sanitize_string("hi\x00there") == "hithere"


def test_sanitize_string_preserves_tab_newline(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert sec.sanitize_string("a\tb\nc") == "a\tb\nc"


def test_sanitize_string_truncates(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert len(sec.sanitize_string("x" * 1000, max_length=10)) == 10


def test_sanitize_string_none(frappe_stub, monkeypatch):
	sec = _reload_security(monkeypatch, frappe_stub)
	assert sec.sanitize_string(None) == ""
