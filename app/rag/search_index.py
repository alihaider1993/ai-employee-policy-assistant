from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
)

from app.core.config import settings

credential = AzureKeyCredential(
    settings.azure_search_api_key
)

index_client = SearchIndexClient(
    endpoint=settings.azure_search_endpoint,
    credential=credential,
)

fields = [
    SimpleField(
        name="id",
        type=SearchFieldDataType.String,
        key=True,
    ),

    SearchableField(
        name="content",
        type=SearchFieldDataType.String,
    ),

    SimpleField(
        name="source",
        type=SearchFieldDataType.String,
        filterable=True,
    ),

    SimpleField(
        name="page",
        type=SearchFieldDataType.Int32,
        filterable=True,
    ),

    SearchField(
        name="content_vector",
        type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
        searchable=True,
        vector_search_dimensions=1536,
        vector_search_profile_name="policy-vector-profile",
    ),
]


vector_search = VectorSearch(
    algorithms=[
        HnswAlgorithmConfiguration(
            name="policy-hnsw",
        )
    ],
    profiles=[
        VectorSearchProfile(
            name="policy-vector-profile",
            algorithm_configuration_name="policy-hnsw",
        )
    ],
)

index = SearchIndex(
    name=settings.azure_search_index,
    fields=fields,
    vector_search=vector_search,
)

def create_search_index():
    index_client.create_index(index)

    print(f"Created index: {settings.azure_search_index}")