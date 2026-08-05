"""Build `datasets/mevzuat/` from the official legislation database.

Requirement 5 of Görev 1 is "ilgili mevzuat önerisi", and a suggestion is only
worth as much as the corpus behind it. That corpus was hand-transcribed from PDFs:
three documents, and even the regulation we relied on most carried 18 of its 39
articles. Everything a real evrak also touches -- 657 for leave, 6698 for the TCKN
we extract, 7201 for service of documents -- was simply absent.

This script fetches the full text from the source instead, through the
`mevzuat-mcp` server (github.com/saidsurucu/mevzuat-mcp, MIT), which queries
mevzuat.gov.tr and bedesten.adalet.gov.tr.

It is a **development-time** tool and deliberately not part of the runtime. The
server's dependency tree pins `playwright` and pulls a browser binary, so it is
never installed into the backend image; the analysis pipeline keeps reading the
committed Markdown files and keeps working with no network at all.

Setup (an isolated environment, not the project one):

    python -m venv /tmp/mcpvenv
    /tmp/mcpvenv/bin/pip install "git+https://github.com/saidsurucu/mevzuat-mcp"

Use the git version, not PyPI 0.3.0: only the former exposes `search_mevzuat`
and `get_mevzuat_content`, and `get_*_content` has no KANUN equivalent in the
released package.

Usage:

    python scripts/fetch_mevzuat_corpus.py --server /tmp/mcpvenv/bin/mevzuat-mcp --check
    python scripts/fetch_mevzuat_corpus.py --server /tmp/mcpvenv/bin/mevzuat-mcp --write

`--check` fetches and reports differences without touching the corpus. Run it
before `--write`: an unexpected diff on a file we already trust means either the
transcription was wrong or the tool is not returning the official text, and both
are worth knowing before six more files depend on it.
"""

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from typing import Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.mcp.client import MCPClient  # noqa: E402

CORPUS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "datasets", "mevzuat"
)


@dataclass(frozen=True)
class MevzuatSpec:
    """One piece of legislation to fetch.

    Attributes:
        slug: Corpus file name, without the .md suffix.
        title: Human-readable title, used only for the file header.
        number: Official legislation number, used to resolve the document id.
        kind: `search_mevzuat` type filter, e.g. "KANUN" or "CB_YONETMELIK".
        why: Why this text belongs in the corpus -- written into the file header
            so a reader can tell curation from accretion.
    """

    slug: str
    title: str
    number: str
    kind: str
    why: str


#: What an incoming evrak actually raises. Each entry has to earn its place: a
#: larger corpus changes what reciprocal rank fusion surfaces, so coverage is not
#: free and `scripts/evaluate_classification.py` is the gate on adding to it.
#: Resolved by number, never by title. Searching `mevzuat_adi="Devlet Memurları
#: Kanunu"` returns law 7417 -- a 2022 act *amending* 657 -- as its top hit, and
#: 657 itself does not appear at all; "Bilgi Edinme Hakkı Kanunu" likewise resolved
#: to a related document rather than law 4982. Both would have put a real
#: mevzuat_id behind the wrong text, which is precisely the fabricated-citation
#: failure this pipeline exists to prevent.
CORPUS: tuple[MevzuatSpec, ...] = (
    MevzuatSpec(
        "resmi_yazisma_yonetmeligi",
        "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik",
        "2646",
        "CB_YONETMELIK",
        "Evrak biçim kurallarının kaynağı; eksik alan kurallarının tamamı buna atıf yapar.",
    ),
    MevzuatSpec(
        "dilekce_hakki_kanunu_3071",
        "Dilekçe Hakkının Kullanılmasına Dair Kanun",
        "3071",
        "KANUN",
        "Dilekçelerde ad, imza ve adres zorunluluğu (m.4).",
    ),
    MevzuatSpec(
        "bilgi_edinme_hakki_kanunu_4982",
        "Bilgi Edinme Hakkı Kanunu",
        "4982",
        "KANUN",
        "Bilgi edinme başvurularının zorunlu unsurları ve süreleri.",
    ),
    MevzuatSpec(
        "devlet_memurlari_kanunu_657",
        "Devlet Memurları Kanunu",
        "657",
        "KANUN",
        "İzin talepleri ve personel yazışmaları; izin türleri ve süreleri.",
    ),
    MevzuatSpec(
        "kisisel_verilerin_korunmasi_kanunu_6698",
        "Kişisel Verilerin Korunması Kanunu",
        "6698",
        "KANUN",
        "Evraktan TCKN, ad ve adres çıkarıyoruz; işleme şartları buraya bağlı.",
    ),
    MevzuatSpec(
        "tebligat_kanunu_7201",
        "Tebligat Kanunu",
        "7201",
        "KANUN",
        "Evrakın muhataba tebliği ve tebligat adresinin sonuçları.",
    ),
    MevzuatSpec(
        "elektronik_imza_kanunu_5070",
        "Elektronik İmza Kanunu",
        "5070",
        "KANUN",
        "Güvenli elektronik imzanın hukuki sonucu; imza alanı tespitinin dayanağı.",
    ),
)


def _normalise(text: str) -> str:
    """Repair the line wrapping the source conversion introduces.

    The fetched Markdown breaks lines mid-heading ("RESMÎ\\nYAZIŞMALARDA
    UYGULANACAK\\nUSUL"), which would split a heading across chunks and cost the
    BM25 half of the retriever the very tokens it matches on.

    Args:
        text: Raw text as returned by the server.

    Returns:
        Text with intra-paragraph line breaks joined and blank lines collapsed.
    """
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    # A newline that is not followed by a blank line, a heading, or an article
    # marker is a wrap, not a paragraph break.
    text = re.sub(r"\n(?!\s*\n)(?!\s*(?:MADDE|BİRİNCİ|İKİNCİ|ÜÇÜNCÜ|DÖRDÜNCÜ|"
                  r"BEŞİNCİ|ALTINCI|YEDİNCİ|SEKİZİNCİ|EK |GEÇİCİ|#))", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _header(spec: MevzuatSpec, mevzuat_id: str, fetched_on: str) -> str:
    """Build the provenance block written above every corpus file.

    Every citation this project emits has to be traceable to the official text --
    a web summary once put the Sayı requirement at article 8 when the regulation
    says 11 -- so the file records exactly what was fetched and when.

    Args:
        spec: The legislation being written.
        mevzuat_id: Source identifier the content was retrieved with.
        fetched_on: ISO date of the fetch.

    Returns:
        The Markdown header.
    """
    return (
        f"# {spec.title}\n\n"
        f"> Kaynak: mevzuat.gov.tr (bedesten.adalet.gov.tr üzerinden)\n"
        f"> Mevzuat no: {spec.number} ({spec.kind})\n"
        f"> mevzuat_id: {mevzuat_id}\n"
        f"> Çekilme tarihi: {fetched_on}\n"
        f"> Korpustaki gerekçesi: {spec.why}\n"
        f">\n"
        f"> Bu dosya `scripts/fetch_mevzuat_corpus.py` ile üretilmiştir; elle "
        f"düzenlemeyin.\n\n"
    )


def _strip_header(text: str) -> str:
    """Remove a provenance block so two versions can be compared on content.

    Args:
        text: A corpus file's contents.

    Returns:
        The text below the header.
    """
    return re.sub(r"\A#[^\n]*\n\n(?:>[^\n]*\n)+\n", "", text)


def _articles(text: str) -> set[int]:
    """Return the article numbers a text contains.

    Args:
        text: Legislation text.

    Returns:
        Every `MADDE n` number found.
    """
    return {int(n) for n in re.findall(r"MADDE\s+(\d+)", text, re.IGNORECASE)}


async def _resolve_id(session, spec: MevzuatSpec) -> Optional[str]:
    """Look up a document's id by its official number and type.

    The result line is required to lead with `- [<number>]`, so a search that
    drifts to a neighbouring document is rejected rather than silently accepted.

    Args:
        session: Live MCP session.
        spec: The legislation to resolve.

    Returns:
        The document id, or None when nothing matches the number exactly.
    """
    result = await session.call_tool(
        name="search_mevzuat",
        arguments={
            "mevzuat_no": spec.number,
            "mevzuat_tur": spec.kind,
            "page_size": 5,
        },
    )
    text = result.content[0].text if result.content else ""
    for line in text.splitlines():
        match = re.match(rf"-\s*\[{re.escape(spec.number)}\].*?mevzuatId:\s*(\d+)", line)
        if match:
            return match.group(1)
    print(f"    {spec.number} numarasıyla tam eşleşme yok: {text.strip()[:200]}")
    return None


async def _fetch_one(session, spec: MevzuatSpec) -> Optional[tuple[str, str]]:
    """Fetch one piece of legislation in full.

    Args:
        session: Live MCP session.
        spec: The legislation to fetch.

    Returns:
        The document id and its normalised text, or None on failure.
    """
    mevzuat_id = await _resolve_id(session, spec)
    if mevzuat_id is None:
        return None

    result = await session.call_tool(
        name="get_mevzuat_content", arguments={"mevzuat_id": mevzuat_id}
    )
    body = result.content[0].text if result.content else ""
    if not body.strip():
        print("    boş içerik döndü")
        return None
    return mevzuat_id, _normalise(body)


async def run(server: str, write: bool) -> int:
    """Fetch every corpus entry and report or write the result.

    Args:
        server: Path to the mevzuat-mcp executable.
        write: Whether to write the files, as opposed to only reporting.

    Returns:
        Process exit code.
    """
    client = MCPClient(name="mevzuat", command=server, args=[])
    fetched_on = date.today().isoformat()
    failures = 0

    async with client.connect() as session:
        for spec in CORPUS:
            path = os.path.join(CORPUS_DIR, f"{spec.slug}.md")
            existing = ""
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as handle:
                    existing = handle.read()

            print(f"\n{spec.slug}")
            fetched = await _fetch_one(session, spec)
            if fetched is None:
                failures += 1
                print("    ATLANDI (mevcut dosyaya dokunulmadı)")
                continue

            mevzuat_id, body = fetched
            new_articles = _articles(body)
            old_articles = _articles(_strip_header(existing))
            print(
                f"    mevzuat_id={mevzuat_id}  {len(body):,} karakter  "
                f"{len(new_articles)} madde"
            )
            if existing:
                gained = sorted(new_articles - old_articles)
                lost = sorted(old_articles - new_articles)
                print(f"    mevcut dosyada {len(old_articles)} madde vardı")
                if gained:
                    print(f"    kazanılan madde: {gained}")
                if lost:
                    # Worth stopping for: the fetched text should be a superset of
                    # a correct transcription, so a loss means one of them is wrong.
                    print(f"    !! KAYBEDİLEN madde: {lost} -- inceleyin")

            if write:
                os.makedirs(CORPUS_DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(_header(spec, mevzuat_id, fetched_on) + body)
                print("    yazıldı")

    if not write:
        print("\n(--check modu: hiçbir dosya değiştirilmedi; yazmak için --write)")
    if failures:
        print(f"\n{failures} kayıt çekilemedi.")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mevzuat korpusunu resmî kaynaktan güncelle."
    )
    parser.add_argument(
        "--server",
        required=True,
        help="mevzuat-mcp çalıştırılabilir dosyasının yolu (izole bir sanal ortamda).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="Yalnızca farkları raporla, dosyaları değiştirme (varsayılan).",
    )
    group.add_argument("--write", action="store_true", help="Korpus dosyalarını yaz.")
    args = parser.parse_args()

    return asyncio.run(run(args.server, write=args.write))


if __name__ == "__main__":
    raise SystemExit(main())
