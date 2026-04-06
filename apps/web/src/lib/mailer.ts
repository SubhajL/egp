/**
 * Thin SMTP mailer for the Next.js app.
 *
 * Reads the same env vars used by the Python notification-core package so that
 * a single SMTP account serves both the API worker and the web inquiry handler:
 *
 *   EGP_SMTP_HOST        — e.g. smtp.gmail.com
 *   EGP_SMTP_PORT        — e.g. 587
 *   EGP_SMTP_USERNAME    — SMTP login
 *   EGP_SMTP_PASSWORD    — SMTP password / app password
 *   EGP_SMTP_FROM        — envelope From address, e.g. "e-GP Platform <no-reply@example.com>"
 *   EGP_SMTP_USE_TLS     — "true" | "false"  (defaults to true)
 *
 *   OPS_EMAIL            — inbox that receives new inquiry notifications
 */

import nodemailer, { type Transporter } from "nodemailer";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

function getSmtpTransporter(): Transporter {
  const host = process.env.EGP_SMTP_HOST;
  const port = parseInt(process.env.EGP_SMTP_PORT ?? "587", 10);
  const user = process.env.EGP_SMTP_USERNAME;
  const pass = process.env.EGP_SMTP_PASSWORD;
  const useTls = (process.env.EGP_SMTP_USE_TLS ?? "true") !== "false";

  if (!host || !user || !pass) {
    throw new Error(
      "SMTP is not configured. Set EGP_SMTP_HOST, EGP_SMTP_USERNAME, and EGP_SMTP_PASSWORD.",
    );
  }

  return nodemailer.createTransport({
    host,
    port,
    secure: port === 465 ? true : false,
    auth: { user, pass },
    // STARTTLS for port 587; explicit TLS for port 465
    tls: useTls ? { rejectUnauthorized: false } : undefined,
  });
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface InquiryData {
  services: string;
  packageSize: string;
  projectRef: string;
  companyName: string;
  contactName: string;
  email: string;
  phone: string;
  notes: string;
  fileCount: number;
}

// ---------------------------------------------------------------------------
// Email builders
// ---------------------------------------------------------------------------

const SERVICE_LABELS: Record<string, string> = {
  tor: "จัดทำข้อเสนอ TOR",
  poc: "พัฒนา POC / Pilot",
};

const PACKAGE_LABELS: Record<string, string> = {
  small: "แพ็กเกจ S — วงเงิน < 5M บาท (฿50,000 / 7 วัน)",
  medium: "แพ็กเกจ M — วงเงิน < 10M บาท (฿100,000 / 10 วัน)",
};

function buildOpsHtml(d: InquiryData): string {
  const serviceLabel =
    d.services
      .split(",")
      .map((s) => SERVICE_LABELS[s.trim()] ?? s.trim())
      .join(", ") || "-";

  return `
<html><body style="font-family:sans-serif;font-size:14px;color:#1e293b">
<h2 style="color:#4f46e5">📋 คำขอใช้บริการที่ปรึกษาใหม่</h2>
<table cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:600px">
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600;width:160px">บริการที่เลือก</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${serviceLabel}</td></tr>
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600">แพ็กเกจ</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${PACKAGE_LABELS[d.packageSize] ?? d.packageSize}</td></tr>
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600">เลขที่โครงการ / TOR</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${d.projectRef || "-"}</td></tr>
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600">บริษัท / หน่วยงาน</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${d.companyName}</td></tr>
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600">ผู้ติดต่อ</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${d.contactName}</td></tr>
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600">อีเมล</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0"><a href="mailto:${d.email}">${d.email}</a></td></tr>
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600">โทรศัพท์</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${d.phone || "-"}</td></tr>
  <tr><td style="padding:8px;background:#f8fafc;font-weight:600">ไฟล์แนบ</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${d.fileCount} ไฟล์</td></tr>
  ${d.notes ? `<tr><td style="padding:8px;background:#f8fafc;font-weight:600;vertical-align:top">หมายเหตุ</td>
      <td style="padding:8px;border-bottom:1px solid #e2e8f0">${d.notes}</td></tr>` : ""}
</table>
<p style="margin-top:24px;color:#64748b;font-size:12px">ส่งโดยอัตโนมัติจาก e-GP Intelligence Platform</p>
</body></html>
  `.trim();
}

function buildConfirmationHtml(d: InquiryData): string {
  return `
<html><body style="font-family:sans-serif;font-size:14px;color:#1e293b">
<h2 style="color:#4f46e5">ขอบคุณสำหรับคำขอของคุณ</h2>
<p>เรียน คุณ${d.contactName},</p>
<p>เราได้รับคำขอใช้บริการที่ปรึกษาของคุณเรียบร้อยแล้ว ทีมงานจะติดต่อกลับภายใน <strong>1 วันทำการ</strong> เพื่อยืนยันรายละเอียดและตกลงกำหนดการ</p>
<h3 style="color:#4f46e5;margin-top:24px">สรุปคำขอ</h3>
<ul style="padding-left:20px;line-height:1.8">
  <li><strong>บริการ:</strong> ${d.services.split(",").map((s) => SERVICE_LABELS[s.trim()] ?? s.trim()).join(", ")}</li>
  <li><strong>แพ็กเกจ:</strong> ${PACKAGE_LABELS[d.packageSize] ?? d.packageSize}</li>
  <li><strong>บริษัท:</strong> ${d.companyName}</li>
</ul>
<p style="margin-top:24px">หากมีข้อสงสัยเพิ่มเติม กรุณาตอบกลับอีเมลนี้</p>
<p>ขอบคุณที่ไว้วางใจ e-GP Intelligence Platform</p>
<p style="color:#64748b;font-size:12px;margin-top:32px">อีเมลนี้ส่งโดยอัตโนมัติ กรุณาอย่าตอบกลับหากไม่ได้ส่งคำขอ</p>
</body></html>
  `.trim();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Sends two emails:
 *  1. Ops notification → OPS_EMAIL env var
 *  2. Submitter confirmation → d.email
 *
 * Throws if SMTP is not configured or sending fails.
 */
export async function sendInquiryNotification(d: InquiryData): Promise<void> {
  const transporter = getSmtpTransporter();
  const from = process.env.EGP_SMTP_FROM ?? process.env.EGP_SMTP_USERNAME ?? "";
  const opsEmail = process.env.OPS_EMAIL;

  const serviceLabel =
    d.services
      .split(",")
      .map((s) => SERVICE_LABELS[s.trim()] ?? s.trim())
      .join(", ") || "ที่ปรึกษา";

  const sends: Promise<unknown>[] = [];

  // 1. Notify the ops team
  if (opsEmail) {
    sends.push(
      transporter.sendMail({
        from,
        to: opsEmail,
        subject: `[e-GP] คำขอใหม่: ${serviceLabel} — ${d.companyName}`,
        html: buildOpsHtml(d),
      }),
    );
  } else {
    console.warn("[Inquiry] OPS_EMAIL is not set — skipping ops notification.");
  }

  // 2. Confirmation to the submitter
  sends.push(
    transporter.sendMail({
      from,
      to: d.email,
      subject: "e-GP Platform: เราได้รับคำขอของคุณแล้ว",
      html: buildConfirmationHtml(d),
    }),
  );

  await Promise.all(sends);
}
