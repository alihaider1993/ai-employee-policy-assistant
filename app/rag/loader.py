import re
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

def load_policy_document(file_path: str):
    loader = PyPDFLoader(file_path)

    documents = loader.load()

    return documents


def split_documents(documents):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )

    chunks = text_splitter.split_documents(documents)

    return chunks

POLICY_DIRECTORY = Path("data/policies")

# The handbook was first indexed as chunk-0, chunk-1, ... so it keeps those IDs.
LEGACY_ID_PREFIXES = {"fca_employee_handbook": "chunk"}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    return slug or "document"


def display_name(title: str | None, file_path: str) -> str:
    cleaned = (title or "").removeprefix("Print ").strip()

    return cleaned or Path(file_path).stem


def list_policy_files(directory: Path = POLICY_DIRECTORY) -> list[Path]:
    return sorted(directory.glob("*.pdf"))


LINK_PATH = re.compile(r"[ \t]*\(/[\w\-/#?=.]*(?:-\n[\w\-/#?=.]*)*\)")


def strip_link_paths(text: str) -> str:
    # GOV.UK print versions keep site-relative link targets, e.g. "(/employment-status/worker)".
    return LINK_PATH.sub("", text)


def build_chunk_records(file_path: str) -> list[dict]:
    documents = load_policy_document(file_path)

    for document in documents:
        document.page_content = strip_link_paths(document.page_content)

    chunks = split_documents(documents)
    stem = Path(file_path).stem
    prefix = LEGACY_ID_PREFIXES.get(stem) or slugify(stem)

    return [
        {
            "id": f"{prefix}-{number}",
            "content": chunk.page_content,
            "source": display_name(chunk.metadata.get("title"), file_path),
            "page": chunk.metadata.get("page", 0),
        }
        for number, chunk in enumerate(chunks)
    ]


if __name__ == "__main__":
    for path in list_policy_files():
        records = build_chunk_records(str(path))
        print(f"{len(records):4d} chunks  {records[0]['source']}  ({path.name})")
