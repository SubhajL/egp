import { NextRequest, NextResponse } from "next/server";
import { sendInquiryNotification, type InquiryData } from "@/lib/mailer";

/**
 * POST /api/inquiry
 *
 * Accepts a multipart/form-data submission from the /inquiry page.
 * Fields: services, refType, projectRef, companyName, contactName,
 *         email, phone, packageSize, notes
 * Files:  files[] — TOR / announcement documents
 *
 * On success:
 *   - Sends an ops notification email to OPS_EMAIL
 *   - Sends a confirmation email to the submitter
 */
export async function POST(req: NextRequest): Promise<NextResponse> {
  try {
    const data = await req.formData();

    const inquiry: InquiryData = {
      services:    String(data.get("services")     ?? ""),
      packageSize: String(data.get("packageSize")  ?? ""),
      projectRef:  String(data.get("projectRef")   ?? ""),
      companyName: String(data.get("companyName")  ?? ""),
      contactName: String(data.get("contactName")  ?? ""),
      email:       String(data.get("email")        ?? ""),
      phone:       String(data.get("phone")        ?? ""),
      notes:       String(data.get("notes")        ?? ""),
      fileCount:   data.getAll("files").filter((f) => f instanceof File && f.size > 0).length,
    };

    console.log("[Inquiry] New submission:", {
      services:    inquiry.services,
      packageSize: inquiry.packageSize,
      company:     inquiry.companyName,
      contact:     inquiry.contactName,
      email:       inquiry.email,
      fileCount:   inquiry.fileCount,
    });

    await sendInquiryNotification(inquiry);

    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("[Inquiry] Failed to process submission:", err);
    return NextResponse.json(
      { ok: false, error: "Failed to process submission" },
      { status: 500 },
    );
  }
}
