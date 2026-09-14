import pytest
from app.research import extract_findings, normalize_domain

def test_normalize_domain_accepts_domain_and_url():
    assert normalize_domain("Example.com") == "example.com"
    assert normalize_domain("https://www.example.com/about") == "example.com"

@pytest.mark.parametrize("value",["localhost","not a domain","https://"])
def test_normalize_domain_rejects_invalid_values(value):
    with pytest.raises(ValueError): normalize_domain(value)

def test_extract_findings_returns_evidence_and_source():
    html="<html><body><h1>We raised a Series B</h1><p>We are hiring sales people and launching a new product.</p></body></html>"
    results=extract_findings(html,"https://example.com/news")
    kinds={item.kind for item in results}
    assert {"FUNDING","SALES_HIRING","PRODUCT_LAUNCH"}.issubset(kinds)
    assert all(item.url=="https://example.com/news" and item.evidence for item in results)
