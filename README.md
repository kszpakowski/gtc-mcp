# gtc-mcp

MCP server exposing insurance terms and conditions from the NN SOAP API.

## What it provides

- `list_gtc_documents`
  - returns document metadata
  - supports arbitrary metadata filters
  - supports substring or exact matching
  - supports sorting and limiting
- `get_gtc_document`
  - fetches a document by id
  - extracts text from PDF content for agent use
- `find_gtc_document_context`
  - returns a compact context block with matching metadata and bodies
- `search_gtc_documents`
  - filters by `prodCode`, `componentCode`, `typeName`, `withdrawn`
  - filters by `dateFrom` and `modDate` ranges
  - can restrict results to documents active on a given date
- resources
  - `gtc://documents/{doc_id}`
  - `gtc://documents/{doc_id}/full`

The flexible filters are intentional because the exact metadata schema comes from the SOAP API response.
The live API currently exposes fields such as `idBodyDoc`, `idHeadDoc`, `docName`, `docTitle`, `typeName`, `componentCode`, `prodCode`, `dateFrom`, `dateTo`, `regDate`, `modDate`, and `withdrawn`.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run

```bash
gtc-mcp
```

Optional override:

```bash
export GTC_WSDL="https://gtc.nn.pl/gtc/services/GtcServiceHttpPort?wsdl"
```

Document bodies are cached locally after the first fetch. Optional override:

```bash
export GTC_CACHE_DIR="/absolute/path/to/cache"
```

## Example MCP configuration

```json
{
  "mcpServers": {
    "gtc": {
      "command": "/absolute/path/to/gtc-mcp/.venv/bin/gtc-mcp"
    }
  }
}
```

## Example tool calls

List documents where the `product` field contains `travel`:

```json
{
  "filters": {
    "product": "travel"
  },
  "contains_match": true,
  "limit": 10
}
```

Get a document body:

```json
{
  "doc_id": "12345"
}
```

Get context for the agent:

```json
{
  "filters": {
    "language": "pl",
    "product": "life"
  },
  "limit": 3
}
```

Find active documents for a product on March 11, 2026:

```json
{
  "as_of_date": "2026-03-11",
  "prod_code": "FIR0",
  "withdrawn": 0,
  "limit": 10
}
```
