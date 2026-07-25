"""FAQPage JSON-LD validation — the '@iga' bug must become an explicit violation."""

from __future__ import annotations

from app.pipeline.execution.jsonld import validate_faqpage

VALID = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": [
        {
            "@type": "Question",
            "name": "What is X?",
            "acceptedAnswer": {"@type": "Answer", "text": "X is a thing."},
        }
    ],
}


def test_valid_faqpage_has_no_violations():
    assert validate_faqpage(VALID) == []


def test_none_is_allowed():
    # No structured data is fine; only MALFORMED data is a fault.
    assert validate_faqpage(None) == []


def test_misspelled_accepted_answer_key_is_caught():
    # The real bug: the answer landed under "@iga" instead of "acceptedAnswer".
    bad = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "How does X compare?",
                "@iga": {"@type": "Answer", "text": "It compares well."},
            }
        ],
    }
    violations = validate_faqpage(bad)
    assert any("acceptedAnswer is missing" in v for v in violations)
    assert any("@iga" in v for v in violations)  # names what it emitted instead


def test_empty_answer_text_is_caught():
    bad = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Q?",
                "acceptedAnswer": {"@type": "Answer", "text": "   "},
            }
        ],
    }
    assert any("text is empty" in v for v in validate_faqpage(bad))


def test_wrong_type_and_empty_entities():
    assert any(
        "@type is not FAQPage" in v
        for v in validate_faqpage(
            {"@context": "https://schema.org", "@type": "WebPage", "mainEntity": []}
        )
    )
    assert any(
        "mainEntity is missing or empty" in v
        for v in validate_faqpage(
            {"@context": "https://schema.org", "@type": "FAQPage"}
        )
    )
