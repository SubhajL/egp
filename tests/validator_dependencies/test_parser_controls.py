"""Real parser dependency controls, not hostile-resource validation acceptance."""

from __future__ import annotations

from importlib.metadata import version
import io
import zipfile

from defusedxml import ElementTree
from defusedxml.common import EntitiesForbidden
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
import pytest

from .parser_control_fixtures import valid_docx, valid_pdf, valid_zip


def test_exact_parser_dependencies_are_importable() -> None:
    assert version("pypdf") == "6.14.2"
    assert version("defusedxml") == "0.7.1"


def test_real_pdf_has_strict_catalog_page_tree_and_text_stream() -> None:
    reader = PdfReader(io.BytesIO(valid_pdf()), strict=True)
    assert reader.trailer["/Root"]["/Type"] == "/Catalog"
    assert len(reader.pages) == 1
    assert "procurement fixture" in reader.pages[0].extract_text()
    assert not reader.is_encrypted


def test_prefix_only_pdf_fails_for_structure_not_dependency_or_limits() -> None:
    with pytest.raises(PdfReadError):
        PdfReader(io.BytesIO(b"%PDF-1.7\n%%EOF"), strict=True)


def test_encrypted_pdf_is_a_distinct_control() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("fixture-only-password")
    buffer = io.BytesIO()
    writer.write(buffer)
    assert PdfReader(io.BytesIO(buffer.getvalue()), strict=True).is_encrypted


def test_zip_has_real_central_directory_and_streamed_crc() -> None:
    with zipfile.ZipFile(io.BytesIO(valid_zip())) as archive:
        assert archive.testzip() is None
        assert archive.read("readme.txt") == b"procurement fixture"


def test_corrupt_crc_fails_for_crc_not_resource_setup() -> None:
    original = valid_zip(b"CRC-fixture-marker")
    corrupt = original.replace(b"CRC-fixture-marker", b"BROKENture-marker!")
    assert len(corrupt) == len(original) and corrupt != original
    with zipfile.ZipFile(io.BytesIO(corrupt)) as archive:
        with pytest.raises(zipfile.BadZipFile, match="CRC"):
            archive.read("readme.txt")


def test_truncated_zip_fails_for_missing_directory() -> None:
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(b"PK\x03\x04"))


def test_docx_has_safe_parseable_package_parts() -> None:
    with zipfile.ZipFile(io.BytesIO(valid_docx())) as archive:
        assert archive.testzip() is None
        types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
        relationships = ElementTree.fromstring(archive.read("_rels/.rels"))
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        assert types.tag.endswith("}Types")
        assert relationships[0].attrib["Target"] == "word/document.xml"
        assert document.tag.endswith("}document")


def test_hostile_xml_fails_for_entity_expansion() -> None:
    hostile = b'<!DOCTYPE d [<!ENTITY x "fixture">]><d>&x;</d>'
    with pytest.raises(EntitiesForbidden):
        ElementTree.fromstring(hostile)
