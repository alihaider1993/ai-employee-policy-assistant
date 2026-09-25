from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from app.ai.embeddings import embeddings
from app.core.config import settings
from app.rag.loader import load_policy_document, split_documents

search_client = SearchClient(
    endpoint=settings.azure_search_endpoint,
    index_name=settings.azure_search_index,
    credential=AzureKeyCredential(settings.azure_search_api_key),
)

def index_policy_document(file_path: str):
    documents = load_policy_document(file_path)
    chunks = split_documents(documents)

    print(f"Loaded {len(documents)} pages")
    print(f"Created {len(chunks)} chunks")
    
    texts = [
        chunk.page_content
        for chunk in chunks
    ]

    vectors = embeddings.embed_documents(texts)
    
    search_documents = []

    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        search_document = {
            "id": f"chunk-{i}",
            "content": chunk.page_content,
            "source": chunk.metadata.get("title", "Unknown"),
            "page": chunk.metadata.get("page", 0),
            "content_vector": vector,
        }

        search_documents.append(search_document)

    print(f"Prepared {len(search_documents)} documents for Azure AI Search")

    print(f"Generated {len(vectors)} embeddings")
    print(f"Vector dimensions: {len(vectors[0])}")
    
    result = search_client.upload_documents(
        documents=search_documents
    )

    successful = sum(
        1 for item in result if item.succeeded
    )

    print(f"Uploaded {successful} documents to Azure AI Search")

if __name__ == "__main__":
    index_policy_document(
        "data/policies/fca_employee_handbook.pdf"
    )