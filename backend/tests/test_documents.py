from backend.database import split_sections


def test_list_sections(client):
    wording = client.get("/api/documents/policy_wording/sections").json()
    assert [s["number"] for s in wording] == list(range(13))
    assert wording[0]["title"] == "UnderCover Travel Insurance: Policy Wording"
    assert wording[1] == {"number": 1, "title": "Your plan"}
    manual = client.get("/api/documents/claims_manual/sections").json()
    assert [s["number"] for s in manual] == list(range(15))


def test_read_section(client):
    section = client.get("/api/documents/claims_manual/sections/9").json()
    assert section["document"] == "claims_manual"
    assert section["title"] == "Repeat claims"
    assert section["text"].startswith("## 9. Repeat claims")
    assert "third claim within any 12 month period" in section["text"]
    assert "## 10." not in section["text"]


def test_section_zero_holds_the_version(client):
    section = client.get("/api/documents/policy_wording/sections/0").json()
    assert "Version 2026.1" in section["text"]


def test_unknown_sections(client):
    assert client.get("/api/documents/claims_manual/sections/99").status_code == 404
    assert client.get("/api/documents/menu/sections").status_code == 422
    assert client.get("/api/documents/menu/sections/1").status_code == 422


def test_split_sections():
    text = "# Title\n\nIntro.\n\n## 1. First\n\nOne.\n\n## 2. Second\n\nTwo.\n"
    assert split_sections(text) == [
        (0, "Title", "# Title\n\nIntro."),
        (1, "First", "## 1. First\n\nOne."),
        (2, "Second", "## 2. Second\n\nTwo."),
    ]
