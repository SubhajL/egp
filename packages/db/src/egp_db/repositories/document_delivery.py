"""Document artifact delivery and read operations."""

from __future__ import annotations

from collections.abc import Iterator

from egp_db.artifact_store import ArtifactStore, DEFAULT_DOWNLOAD_CHUNK_SIZE
from egp_db.tenant_storage_resolver import (
    ResolvedArtifactStore,
    ResolvedDocumentWritePlan,
)

from .document_models import (
    DocumentArtifactReadError,
    DocumentContentResult,
    DocumentContentStream,
    DocumentRecord,
)
from .document_utils import _guess_content_type


class DocumentDeliveryMixin:
    def _resolve_artifact_store_for_write(
        self, *, tenant_id: str
    ) -> ResolvedArtifactStore:
        if self._artifact_store_resolver is None:
            return ResolvedArtifactStore(provider="managed", store=self._artifact_store)
        return self._artifact_store_resolver.resolve_for_write(tenant_id=tenant_id)

    def _resolve_document_write_plan(
        self, *, tenant_id: str
    ) -> ResolvedDocumentWritePlan:
        if self._artifact_store_resolver is None:
            primary = ResolvedArtifactStore(
                provider="managed", store=self._artifact_store
            )
            return ResolvedDocumentWritePlan(primary=primary, managed_backup=None)
        return self._artifact_store_resolver.resolve_write_plan(tenant_id=tenant_id)

    def _resolve_artifact_store_for_storage_key(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> ResolvedArtifactStore:
        if self._artifact_store_resolver is None:
            return ResolvedArtifactStore(provider="managed", store=self._artifact_store)
        return self._artifact_store_resolver.resolve_for_storage_key(
            tenant_id=tenant_id,
            storage_key=storage_key,
        )

    def _build_document_read_error(
        self,
        *,
        document: DocumentRecord,
        provider: str,
        cause: Exception,
    ) -> DocumentArtifactReadError:
        return DocumentArtifactReadError(
            document_id=document.id,
            storage_key=document.storage_key,
            managed_backup_storage_key=document.managed_backup_storage_key,
            provider=provider,
            cause=cause,
        )

    def _get_document_bytes(self, *, tenant_id: str, document: DocumentRecord) -> bytes:
        if document.managed_backup_storage_key is not None:
            try:
                return self._artifact_store.get_bytes(
                    document.managed_backup_storage_key
                )
            except Exception as exc:
                raise self._build_document_read_error(
                    document=document,
                    provider="managed",
                    cause=exc,
                ) from exc
        try:
            resolved_artifact_store = self._resolve_artifact_store_for_storage_key(
                tenant_id=tenant_id,
                storage_key=document.storage_key,
            )
            return resolved_artifact_store.store.get_bytes(
                resolved_artifact_store.decode_storage_key(document.storage_key)
            )
        except Exception as exc:
            raise self._build_document_read_error(
                document=document,
                provider=(
                    resolved_artifact_store.provider
                    if "resolved_artifact_store" in locals()
                    else "unresolved"
                ),
                cause=exc,
            ) from exc

    def get_download_url(
        self, *, tenant_id: str, document_id: str, expires_in: int = 300
    ) -> str:
        document = self.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise KeyError(document_id)
        try:
            resolved_artifact_store = self._resolve_artifact_store_for_storage_key(
                tenant_id=tenant_id,
                storage_key=document.storage_key,
            )
            return resolved_artifact_store.store.download_url(
                resolved_artifact_store.decode_storage_key(document.storage_key),
                expires_in=expires_in,
            )
        except Exception:
            if document.managed_backup_storage_key is None:
                raise
            return self._artifact_store.download_url(
                document.managed_backup_storage_key,
                expires_in=expires_in,
            )

    def get_document_content(
        self, *, tenant_id: str, document_id: str
    ) -> DocumentContentResult:
        document = self.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise KeyError(document_id)
        try:
            resolved_artifact_store = self._resolve_artifact_store_for_storage_key(
                tenant_id=tenant_id,
                storage_key=document.storage_key,
            )
            file_bytes = resolved_artifact_store.store.get_bytes(
                resolved_artifact_store.decode_storage_key(document.storage_key)
            )
        except Exception as exc:
            primary_error = self._build_document_read_error(
                document=document,
                provider=(
                    resolved_artifact_store.provider
                    if "resolved_artifact_store" in locals()
                    else "unresolved"
                ),
                cause=exc,
            )
            if document.managed_backup_storage_key is None:
                raise primary_error from exc
            try:
                file_bytes = self._artifact_store.get_bytes(
                    document.managed_backup_storage_key
                )
            except Exception as backup_exc:
                raise self._build_document_read_error(
                    document=document,
                    provider="managed",
                    cause=backup_exc,
                ) from backup_exc
        return DocumentContentResult(
            document=document,
            file_bytes=file_bytes,
            content_type=_guess_content_type(document.file_name),
        )

    def iter_document_bytes(
        self,
        *,
        tenant_id: str,
        document_id: str,
        chunk_size: int = DEFAULT_DOWNLOAD_CHUNK_SIZE,
    ) -> DocumentContentStream:
        """Return a streaming view of a document's bytes.

        Resolves the artifact store the same way :meth:`get_document_content`
        does, but yields bytes in ``chunk_size`` chunks via
        :func:`iter_artifact_bytes`. Stores that natively support chunked
        reads (local filesystem, S3 boto3 ``StreamingBody``) get true
        streaming. Stores that don't fall back to a single chunk so behaviour
        is unchanged for them.

        On primary-store failure with a managed backup configured, the backup
        is used (mirroring :meth:`get_document_content`).
        """
        document = self.get_document(tenant_id=tenant_id, document_id=document_id)
        if document is None:
            raise KeyError(document_id)
        content_type = _guess_content_type(document.file_name)
        try:
            resolved_artifact_store = self._resolve_artifact_store_for_storage_key(
                tenant_id=tenant_id,
                storage_key=document.storage_key,
            )
            decoded_key = resolved_artifact_store.decode_storage_key(
                document.storage_key
            )
            chunks = self._open_chunk_stream(
                resolved_artifact_store.store,
                decoded_key,
                chunk_size=chunk_size,
            )
        except Exception as exc:
            primary_error = self._build_document_read_error(
                document=document,
                provider=(
                    resolved_artifact_store.provider
                    if "resolved_artifact_store" in locals()
                    else "unresolved"
                ),
                cause=exc,
            )
            if document.managed_backup_storage_key is None:
                raise primary_error from exc
            try:
                chunks = self._open_chunk_stream(
                    self._artifact_store,
                    document.managed_backup_storage_key,
                    chunk_size=chunk_size,
                )
            except Exception as backup_exc:
                raise self._build_document_read_error(
                    document=document,
                    provider="managed",
                    cause=backup_exc,
                ) from backup_exc
        return DocumentContentStream(
            document=document,
            chunks=chunks,
            content_type=content_type,
        )

    @staticmethod
    def _open_chunk_stream(
        store: ArtifactStore,
        key: str,
        *,
        chunk_size: int,
    ) -> Iterator[bytes]:
        """Open a chunk iterator over ``key`` from ``store`` *eagerly*.

        Opening eagerly is important: if the underlying store can't satisfy
        the read (missing credentials, network failure), the exception must
        surface here so the repository can fail over to a managed backup. If
        we returned a lazy generator, the exception would only fire once the
        HTTP response had already started streaming.

        For stores that expose ``iter_bytes`` we materialise the first chunk
        so any open/permission errors trip immediately, then re-yield it via
        :func:`itertools.chain`. For stores without ``iter_bytes`` we call
        ``get_bytes`` inline (which already raises eagerly) and return a
        single-chunk iterator preserving prior behaviour.
        """
        iter_method = getattr(store, "iter_bytes", None)
        if callable(iter_method):
            inner = iter_method(key, chunk_size=chunk_size)
            try:
                first = next(inner)
            except StopIteration:
                return iter(())
            from itertools import chain

            return chain((first,), inner)
        payload = store.get_bytes(key)
        return iter((payload,)) if payload else iter(())
