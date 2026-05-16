from __future__ import annotations

from pathlib import Path

from egp_db.repositories import billing_repo
from egp_db.repositories.billing_events import BillingEventMixin
from egp_db.repositories.billing_invoices import BillingInvoiceMixin
from egp_db.repositories.billing_payment_requests import BillingPaymentRequestMixin
from egp_db.repositories.billing_payments import BillingPaymentMixin
from egp_db.repositories.billing_subscriptions import BillingSubscriptionMixin


REPO_ROOT = Path(__file__).resolve().parents[2]
BILLING_REPOSITORY_DIR = REPO_ROOT / "packages/db/src/egp_db/repositories"


def test_billing_repository_is_split_into_focused_modules() -> None:
    expected_modules = {
        "billing_events.py",
        "billing_invoices.py",
        "billing_models.py",
        "billing_payment_requests.py",
        "billing_payments.py",
        "billing_schema.py",
        "billing_subscriptions.py",
        "billing_utils.py",
    }

    existing_modules = {
        path.name for path in BILLING_REPOSITORY_DIR.glob("billing_*.py")
    }
    assert expected_modules <= existing_modules

    facade_lines = (
        (BILLING_REPOSITORY_DIR / "billing_repo.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(facade_lines) < 220


def test_billing_repo_remains_public_facade() -> None:
    assert issubclass(billing_repo.SqlBillingRepository, BillingInvoiceMixin)
    assert issubclass(billing_repo.SqlBillingRepository, BillingPaymentRequestMixin)
    assert issubclass(billing_repo.SqlBillingRepository, BillingPaymentMixin)
    assert issubclass(billing_repo.SqlBillingRepository, BillingSubscriptionMixin)
    assert issubclass(billing_repo.SqlBillingRepository, BillingEventMixin)
    assert billing_repo.BILLING_RECORDS_TABLE.name == "billing_records"
    assert (
        billing_repo.BILLING_PAYMENT_REQUESTS_TABLE.name == "billing_payment_requests"
    )
    assert billing_repo.BillingRecordDetail.__name__ == "BillingRecordDetail"
