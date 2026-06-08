from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingestion.legacy.gemini_ingestion import run_gemini_ingestion as legacy_gemini_ingestion
from ingestion.legacy.local_ingestion import run_ingestion as legacy_local_ingestion
from ingestion.run_folder import run_folder_ingestion
from ingestion.hybrid.pipeline import run_hybrid_ingestion
from ingestion.hybrid.strategies import (
    PdfPageStats,
    choose_ingestion_strategy,
    select_pdf_strategy,
)
from ingestion.models import FileInfo, IngestionError
from ingestion.run_ingestion import run_ingestion


class HybridIngestionTests(unittest.TestCase):
    def test_auto_strategy_selects_local_for_docx(self) -> None:
        file_info = FileInfo(
            file_path=Path("policy.docx"),
            file_name="policy.docx",
            file_extension=".docx",
            file_size=100,
            file_type="docx",
        )

        decision = choose_ingestion_strategy(file_info, "auto")

        self.assertEqual(decision.selected_strategy, "local")
        self.assertEqual(decision.reason, "docx_text_first")

    def test_pdf_stats_select_gemini_for_image_heavy_low_text_pdf(self) -> None:
        stats = PdfPageStats(
            pages=10,
            total_text_chars=200,
            pages_with_images=10,
            low_text_pages=10,
            low_text_image_pages=10,
        )

        strategy, reason = select_pdf_strategy(stats)

        self.assertEqual(strategy, "gemini")
        self.assertIn("pdf_", reason)

    def test_invalid_strategy_raises_ingestion_error(self) -> None:
        file_info = FileInfo(
            file_path=Path("policy.docx"),
            file_name="policy.docx",
            file_extension=".docx",
            file_size=100,
            file_type="docx",
        )

        with self.assertRaises(IngestionError):
            choose_ingestion_strategy(file_info, "unknown")

    def test_local_no_db_hybrid_ingestion_chunks_docx(self) -> None:
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx is not installed")

        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "hybrid_policy.docx"
            document = Document()
            document.add_heading("資料共享管理辦法", level=1)
            document.add_paragraph(
                "第一條 客戶資料共享應載明於客戶已簽署之契據文件及官網個資應告知事項。"
            )
            document.add_paragraph(
                "第二條 涉及負面資訊或風險類資料時，應確認必要查證程序與保護措施。"
            )
            document.save(docx_path)

            result = run_hybrid_ingestion(
                {
                    "file_path": str(docx_path),
                    "internal_code": "HYBRID-TEST-001",
                    "document_type": "internal_rule",
                    "title": "資料共享管理辦法",
                    "source_system": "unit_test",
                    "language": "zh-TW",
                },
                strategy="local",
                no_db=True,
            )

        self.assertEqual(result["status"], "parsed_no_db")
        self.assertEqual(result["selected_strategy"], "local")
        self.assertGreaterEqual(result["total_chunks"], 1)
        self.assertTrue(result["summary_generated"])

    def test_public_legacy_wrappers_reexport_legacy_implementations(self) -> None:
        self.assertIs(run_ingestion, legacy_local_ingestion)
        self.assertTrue(callable(legacy_gemini_ingestion))

    def test_folder_ingestion_uses_hybrid_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            docx_path = Path(temp_dir) / "hybrid_policy.docx"
            docx_path.write_bytes(b"placeholder")

            with patch("ingestion.run_folder.run_hybrid_ingestion") as runner:
                runner.return_value = {
                    "status": "parsed_no_db",
                    "stage": "local_chunking",
                    "selected_strategy": "local",
                    "total_chunks": 3,
                }
                results = run_folder_ingestion(
                    temp_dir,
                    source_system="unit_test",
                    language="zh-TW",
                    internal_code_prefix="HYBRID",
                    strategy="auto",
                    no_db=True,
                )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].selected_strategy, "local")
        self.assertEqual(results[0].total_chunks, 3)
        runner.assert_called_once()


if __name__ == "__main__":
    unittest.main()
