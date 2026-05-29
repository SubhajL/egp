// Capability helpers for the configured payment provider. Card rails only exist
// for the acquirer-backed providers (OPN / Stripe); the ฿0-fee manual PromptPay
// (and the mock) support PromptPay QR only, so the card UI is hidden for them.

export function supportsCardPayment(provider: string | null | undefined): boolean {
  return provider === "opn" || provider === "stripe";
}
