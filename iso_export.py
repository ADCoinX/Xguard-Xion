from lxml import etree

def generate_iso_pain001(wallet_addr: str) -> str:
    # Dummy XML for demo, not full schema
    root = etree.Element("Document", nsmap={None: "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"})
    pain001 = etree.SubElement(root, "pain.001")
    acct = etree.SubElement(pain001, "Acct")
    addr = etree.SubElement(acct, "Id")
    addr.text = wallet_addr
    amt = etree.SubElement(acct, "Amt")
    amt.text = "100.00"
    status = etree.SubElement(acct, "Status")
    status.text = "Validated"
    return etree.tostring(root, pretty_print=True, encoding="UTF-8", xml_declaration=True).decode()