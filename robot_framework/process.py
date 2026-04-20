"""Process for TilsynJournal queue elements.

Henstilling  → posts an inspection comment to PEZ.
Permission   → generates a PDF report and uploads it to Vejman.
"""

from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueElement
from datetime import datetime
from io import BytesIO
import json
import re

import requests
from azure.cosmos import CosmosClient
from fpdf import FPDF


# pylint: disable-next=unused-argument
def process(orchestrator_connection: OrchestratorConnection, queue_element: QueueElement | None = None) -> None:
    orchestrator_connection.log_trace("Running TilsynJournal process.")

    data = json.loads(queue_element.data)
    item_type = data.get("type")
    item_id = data.get("id")

    if item_type == "henstilling":
        process_henstilling(orchestrator_connection, data)

    elif item_type == "permission":
        selection = (data.get("selection") or "").strip()
        updates = data.get("updates") or {}

        if not selection or updates.get("hidden") is True:
            orchestrator_connection.log_info(f"Skipping {item_id} — not a tilsyn inspection.")
            return

        process_permission(orchestrator_connection, data)

    else:
        orchestrator_connection.log_info(f"Unknown type '{item_type}' for {item_id}, skipping.")


# ─── Henstilling → PEZ comment ──────────────────────────────────────────────

def process_henstilling(orchestrator_connection, data):
    item_id = data.get("id")
    inspector_email = data.get("inspector_email", "")
    comment = data.get("comment", "")
    inspected_at = data.get("inspected_at", "")
    updates = data.get("updates") or {}

    # Look up PEZUUID from Cosmos
    cosmos_cred = orchestrator_connection.get_credential("AAKTilsynDB")
    client = CosmosClient(cosmos_cred.username, credential=cosmos_cred.password)
    container = client.get_database_client("aak-tilsyn").get_container_client("TilsynItems")
    item = container.read_item(item=item_id, partition_key=item_id)

    case_uuid = item.get("PEZUUID")
    if not case_uuid:
        orchestrator_connection.log_info(f"No PEZUUID for {item_id}, skipping PEZ comment.")
        return

    # Build comment text
    initials = extract_initials(inspector_email)
    dt = parse_datetime(inspected_at)
    date_str = dt.strftime("%d-%m-%Y") if dt else "ukendt dato"
    time_str = dt.strftime("%H:%M") if dt else ""

    parts = [f"AAK Tilsyn af {initials} d. {date_str} kl. {time_str}"]

    faktura_status = updates.get("fakturaStatus", "")

    if updates.get("kvadratmeter") is not None:
        parts.append(f"Kvm: {updates['kvadratmeter']}")

    if updates.get("end_date"):
        end_dt = parse_datetime(updates["end_date"])
        end_str = end_dt.strftime("%d-%m-%Y") if end_dt else updates["end_date"]
        if faktura_status == "Ny":
            parts.append(f"Sidst set: {end_str}")
        else:
            parts.append(f"Slutdato: {end_str}")

    forseelse = item.get("Forseelse", "")
    if forseelse:
        parts.append(f"Forseelse: {forseelse}")

    # "Ny" is displayed as "Stadig opstillet" in the comment
    faktura_status_display = "Stadig opstillet" if faktura_status == "Ny" else faktura_status
    if faktura_status_display:
        parts.append(f"Status: {faktura_status_display}")

    if comment:
        max_comment = 3500 - len(" | ".join(parts)) - len(" | Kommentar: ")
        if len(comment) > max_comment:
            comment = comment[:max_comment].rstrip() + " (...)"
        parts.append(f"Kommentar: {comment}")

    pez_comment_text = " | ".join(parts)

    # Login to PEZ and post comment
    pez_cred = orchestrator_connection.get_credential("PEZUI")
    session = requests.Session()
    access_token = pez_login(session, pez_cred.username, pez_cred.password)

    post_pez_comment(session, access_token, case_uuid, pez_comment_text)
    orchestrator_connection.log_info(f"Posted PEZ comment for {item_id}: {pez_comment_text}")


# ─── Permission → PDF + Vejman upload ────────────────────────────────────────

def process_permission(orchestrator_connection, data):
    item_id = data.get("id")
    inspector_email = data.get("inspector_email", "")
    comment = data.get("comment", "")
    selection = data.get("selection", "")
    inspected_at = data.get("inspected_at", "")

    initials = extract_initials(inspector_email)
    dt = parse_datetime(inspected_at)

    filename = build_pdf_filename(initials, dt, selection, comment)
    pdf_bytes = generate_inspection_pdf(initials, inspector_email, dt, selection, comment)

    # Upload to Vejman (same pattern as TilsynBilleder)
    vejman_token = orchestrator_connection.get_credential("VejmanToken").password
    url = f"https://vejman.vd.dk/permissions/file?token={vejman_token}"

    orchestrator_connection.log_trace(f"Uploading {filename} to Vejman for case {item_id}.")

    response = requests.post(
        url,
        headers={
            "accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
        },
        data={
            "caseid": item_id,
            "type": "4",
            "transaction": "undefined",
        },
        files=[("filename", (filename, BytesIO(pdf_bytes), "application/pdf"))],
        timeout=30,
    )
    response.raise_for_status()

    orchestrator_connection.log_info(f"Uploaded {filename} for {item_id}: {response.text}")


# ─── PDF generation ──────────────────────────────────────────────────────────

def generate_inspection_pdf(initials, email, dt, selection, comment):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ── Title ──
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 14, "AAK Tilsyn", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Tilsynsrapport", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # Separator
    pdf.set_draw_color(80, 80, 80)
    pdf.set_line_width(0.4)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(8)

    # ── Details table ──
    date_str = dt.strftime("%d-%m-%Y") if dt else "Ukendt"
    time_str = dt.strftime("%H:%M") if dt else "Ukendt"

    label_w = 55
    value_w = 125
    row_h = 9

    rows = [
        ("Tilsynsf\u00f8rende", f"{initials} ({email})"),
        ("Dato", date_str),
        ("Tidspunkt", time_str),
        ("Kategori", selection or "Ikke angivet"),
    ]

    # Table header
    pdf.set_fill_color(41, 65, 122)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(label_w, row_h, "  Felt", border=1, fill=True)
    pdf.cell(value_w, row_h, "  Detalje", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

    # Table rows
    pdf.set_text_color(0, 0, 0)
    for i, (label, value) in enumerate(rows):
        fill = i % 2 == 0
        if fill:
            pdf.set_fill_color(235, 237, 245)

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(label_w, row_h, f"  {label}", border=1, fill=fill)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(value_w, row_h, f"  {value}", border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")

    # ── Comment section ──
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Supplerende kommentar:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_fill_color(248, 248, 248)
    pdf.multi_cell(0, 7, comment if comment else "Ingen kommentar.", border=1, fill=True)

    # ── Footer ──
    pdf.ln(10)
    pdf.set_draw_color(80, 80, 80)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    generated_str = datetime.now().strftime("%d-%m-%Y %H:%M")
    pdf.cell(0, 5, f"Genereret af AAK Tilsyn app d. {generated_str}")

    return pdf.output()


# ─── PEZ helpers ─────────────────────────────────────────────────────────────

def pez_login(session, username, password):
    session.get("https://pez.giantleap.net/login", timeout=30).raise_for_status()

    session.post(
        "https://pez.giantleap.net/rest/public/initiate-login",
        json={"username": username},
        headers={
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://pez.giantleap.net",
            "referer": "https://pez.giantleap.net/login",
        },
        timeout=30,
    ).raise_for_status()

    resp = session.post(
        "https://pez.giantleap.net/rest/oauth/token",
        data={
            "client_id": "web-client",
            "grant_type": "password",
            "username": username,
            "password": password,
        },
        headers={
            "accept": "application/json, text/plain, */*",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://pez.giantleap.net",
            "referer": "https://pez.giantleap.net/login",
            "authorization": "Basic d2ViLWNsaWVudDp3ZWItY2xpZW50",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def post_pez_comment(session, access_token, case_uuid, comment_text):
    session.post(
        f"https://pez.giantleap.net/rest/tickets/cases/{case_uuid}/comments",
        headers={
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {access_token}",
            "content-type": "application/json;charset=UTF-8",
            "x-bpid": "bp_aarhus",
            "x-gltlocale": "da",
        },
        json={"comment": comment_text, "isInternal": True},
        timeout=30,
    ).raise_for_status()


# ─── Utilities ───────────────────────────────────────────────────────────────

def extract_initials(email):
    """'test@aarhus.dk' → 'TEST'"""
    if not email or "@" not in email:
        return "UKENDT"
    return email.split("@")[0].upper()


def parse_datetime(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def build_pdf_filename(initials, dt, selection, comment, max_total_len=215):
    date_part = dt.strftime("%d%m%y") if dt else "000000"
    time_part = dt.strftime("%H%M") if dt else "0000"

    parts = [initials, date_part, time_part]

    if selection:
        parts.append(sanitize_for_filename(selection))

    if comment:
        parts.append(sanitize_for_filename(comment))

    name = "_".join(parts)
    if len(name) > max_total_len:
        name = name[:max_total_len].rstrip(" _") + " (...)"

    return name + ".pdf"



def sanitize_for_filename(text):
    """Remove filesystem-unsafe characters, keep Danish chars."""
    text = text.strip()
    text = re.sub(r'[<>:"/\\|?*]', "", text)
    text = re.sub(r"\s+", " ", text)
    return text