"""SQLTexter SDK - Text2SQL without a server.

This package provides a Python SDK for SQLTexter's text-to-SQL
functionality, allowing you to convert natural language questions
to SQL queries directly in your Python applications.

Example:
    ```python
    from sqltexter import SQLTexter
    
    async def main():
        client = SQLTexter(falkordb_url="redis://localhost:6379")
        await client.connect_database("postgresql://user:pass@host/mydb")
        
        result = await client.query("mydb", "Show me all customers from NYC")
        print(result.sql_query)   # SELECT * FROM customers WHERE city = 'NYC'
        print(result.results)      # [{"id": 1, "name": "John", "city": "NYC"}, ...]
        print(result.ai_response)  # "Found 42 customers from New York City..."
    ```

Requirements:
    - FalkorDB instance (local or remote)
    - OpenAI or Azure OpenAI API key
    - Target SQL database (PostgreSQL or MySQL)
"""

from sqltexter.client import SQLTexter
from sqltexter.models import (
    QueryResult,
    QueryMetadata,
    QueryAnalysis,
    SchemaResult,
    DatabaseConnection,
    RefreshResult,
    QueryRequest,
    ChatMessage,
)
from sqltexter.connection import FalkorDBConnection

__all__ = [
    "SQLTexter",
    "QueryResult",
    "QueryMetadata",
    "QueryAnalysis",
    "SchemaResult",
    "DatabaseConnection",
    "RefreshResult",
    "QueryRequest",
    "ChatMessage",
    "FalkorDBConnection",
]

__version__ = "0.3.2"
