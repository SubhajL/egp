"""e-GP Intelligence Platform — Document Processor.

Handles document hashing (SHA-256), text extraction,
type/phase classification, and diff generation.
"""

from egp_doc_processor.processor import build_document_processor


def main() -> None:
    processor = build_document_processor()
    print(f"e-GP Document Processor starting with {processor.__class__.__name__}...")
    # TODO: Initialize SQS consumer and processing pipeline


if __name__ == "__main__":
    main()
