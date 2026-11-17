import sys

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from app.ai.embeddings import embeddings
from app.core.config import settings
from app.rag.loader import build_chunk_records, list_policy_files

search_client = SearchClient(
    endpoint=settings.azure_search_endpoint,
    index_name=settings.azure_search_index,
    credential=AzureKeyCredential(settings.azure_search_api_key),
)


def index_policy_document(file_path: str):
    records = build_chunk_records(file_path)

    print(f"{file_path}: created {len(records)} chunks")

    vectors = embeddings.embed_documents([record["content"] for record in records])

    search_documents = [
        {**record, "content_vector": vector}
        for record, vector in zip(records, vectors)
    ]

    result = search_client.upload_documents(documents=search_documents)

    successful = sum(1 for item in result if item.succeeded)

    print(f"{file_path}: uploaded {successful} of {len(search_documents)} documents")


def index_policy_documents(file_paths: list[str]):
    for file_path in file_paths:
        index_policy_document(file_path)


if __name__ == "__main__":
    # With no arguments, index every PDF in data/policies/; otherwise only the given files.
    index_policy_documents(sys.argv[1:] or [str(path) for path in list_policy_files()])
