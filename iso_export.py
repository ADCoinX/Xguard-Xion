from lxml import etree
from datetime import datetime
import uuid

NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"
NSMAP = {None: NS}

def _el(parent, tag, text=None):
    el = etree.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el

def generate_iso_pain001(
    wallet_addr: str,
    amount: str | float = "0.00",
    currency: str = "UXION",
    debtor_name: str = "XGuard Xion Wallet",
    creditor_name: str = "Beneficiary",
    creditor_iban: str = "DE00000000000000000000",
    svc_level: str = "SEPA",
) -> str:
    """
    Hasilkan ISO 20022 pain.001.001.03 'Customer Credit Transfer Initiation'
    dengan struktur lengkap (GrpHdr, PmtInf, CdtTrfTxInf).

    - wallet_addr dimasukkan di Debtor Account (Othr/Id) supaya jelas “on-chain account”.
    - amount & currency boleh override (default 0.00 UXION).
    """
    # Normalisasi amaun ke 2 decimal
    try:
        amount = f"{float(amount):.2f}"
    except Exception:
        amount = "0.00"

    now = datetime.utcnow()
    msg_id = f"XGUARD-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    pmt_inf_id = f"PMT-{uuid.uuid4().hex[:8].upper()}"
    end_to_end_id = f"E2E-{uuid.uuid4().hex[:10].upper()}"
    req_date = now.strftime("%Y-%m-%d")

    # <Document>
    doc = etree.Element("Document", nsmap=NSMAP)

    # <CstmrCdtTrfInitn>
    root = _el(doc, "CstmrCdtTrfInitn")

    # ---- Group Header ----
    grp = _el(root, "GrpHdr")
    _el(grp, "MsgId", msg_id)
    _el(grp, "CreDtTm", now.replace(microsecond=0).isoformat() + "Z")
    _el(grp, "NbOfTxs", "1")
    _el(grp, "CtrlSum", amount)
    initg = _el(grp, "InitgPty")
    _el(initg, "Nm", "ADCX LAB VALIDATOR")

    # ---- Payment Info ----
    pmt = _el(root, "PmtInf")
    _el(pmt, "PmtInfId", pmt_inf_id)
    _el(pmt, "PmtMtd", "TRF")
    _el(pmt, "BtchBookg", "false")
    _el(pmt, "NbOfTxs", "1")
    _el(pmt, "CtrlSum", amount)

    pmt_tp = _el(pmt, "PmtTpInf")
    svc = _el(pmt_tp, "SvcLvl")
    _el(svc, "Cd", svc_level)

    _el(pmt, "ReqdExctnDt", req_date)

    # Debtor (penghantar) = Xion wallet owner
    dbtr = _el(pmt, "Dbtr")
    _el(dbtr, "Nm", debtor_name)

    dbtr_acct = _el(pmt, "DbtrAcct")
    dbtr_id = _el(dbtr_acct, "Id")
    # Letak wallet address dalam Other Id
    othr = _el(dbtr_id, "Othr")
    _el(othr, "Id", wallet_addr)

    # Optional: Debtor Agent (boleh biar placeholder)
    dbtr_agt = _el(pmt, "DbtrAgt")
    fin = _el(dbtr_agt, "FinInstnId")
    _el(fin, "BIC", "ADCXLABXXX")

    # ---- Credit Transfer Tx ----
    cdt = _el(pmt, "CdtTrfTxInf")

    pmt_id = _el(cdt, "PmtId")
    _el(pmt_id, "EndToEndId", end_to_end_id)

    amt = _el(cdt, "Amt")
    instd = _el(amt, "InstdAmt", amount)
    instd.set("Ccy", currency)

    cdtr = _el(cdt, "Cdtr")
    _el(cdtr, "Nm", creditor_name)

    cdtr_acct = _el(cdt, "CdtrAcct")
    cdtr_id = _el(cdtr_acct, "Id")
    iban = _el(cdtr_id, "IBAN", creditor_iban)

    # Optional purpose/remittance untuk hias panjang & audit
    rmt = _el(cdt, "RmtInf")
    _el(rmt, "Ustrd", f"Validation export for {wallet_addr}")

    # Serialize
    xml_bytes = etree.tostring(doc, pretty_print=True, encoding="UTF-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")
