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
  - truncates returned text by default and reports truncation metadata
- `find_gtc_document_context`
  - returns a compact context block with matching metadata and truncated bodies
- `search_gtc_document_text`
  - searches a document body for phrases
  - returns grep-like line context windows around matches
  - caps the total response size
- `search_gtc_documents`
  - filters by `prodCode`, `componentCode`, `typeName`, `withdrawn`
  - filters by `dateFrom` and `modDate` ranges
  - can restrict results to documents active on a given date
- `diff_gtc_documents`
  - compares two documents by extracted text
  - returns a unified diff and metadata for both files
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

Run with streamable HTTP:

```bash
gtc-mcp --transport streamable-http
```

Bind on all interfaces for container or homelab use:

```bash
gtc-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

Optional mount path for SSE:

```bash
gtc-mcp --transport sse --mount-path /mcp
```

Optional streamable HTTP path:

```bash
gtc-mcp --transport streamable-http --streamable-http-path /mcp
```

Optional override:

```bash
export GTC_WSDL="https://gtc.nn.pl/gtc/services/GtcServiceHttpPort?wsdl"
```

Document bodies are cached locally after the first fetch. Optional override:

```bash
export GTC_CACHE_DIR="/absolute/path/to/cache"
```

You can also set the transport defaults with environment variables:

```bash
export MCP_TRANSPORT="streamable-http"
export MCP_MOUNT_PATH="/mcp"
export MCP_HOST="0.0.0.0"
export MCP_PORT="8000"
export MCP_STREAMABLE_HTTP_PATH="/mcp"
export MCP_ALLOWED_HOSTS="gtc-mcp.gtc-mcp:8000"
```

If you run behind Kubernetes or another reverse proxy and see `421 Misdirected Request` with `Invalid Host header`, set `MCP_HOST=0.0.0.0` and provide the externally used hostnames in `MCP_ALLOWED_HOSTS`.

## Container image

Build locally:

```bash
make docker-build
```

Publish to your Zot registry:

```bash
make docker-publish ZOT_REGISTRY=zot.example.lan:5000 IMAGE_TAG=latest
```

Build and push a multi-arch image for `linux/amd64` and `linux/arm64`:

```bash
make docker-publishx ZOT_REGISTRY=zot.example.lan:5000 IMAGE_TAG=latest
```

You can override the target platforms if needed:

```bash
make docker-publishx ZOT_REGISTRY=zot.example.lan:5000 IMAGE_TAG=latest PLATFORMS=linux/amd64,linux/arm64
```

Run locally:

```bash
make docker-run
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
  "doc_id": "12345",
  "max_text_chars": 6000
}
```

Get context for the agent:

```json
{
  "filters": {
    "language": "pl",
    "product": "life"
  },
  "limit": 3,
  "max_text_chars_per_document": 2500,
  "max_result_chars": 7000
}
```

Search a document body for specific phrases with line context:

```json
{
  "doc_id": "12345",
  "phrases": ["wyłączenia", "karencja"],
  "before_lines": 2,
  "after_lines": 3,
  "max_matches": 10,
  "max_result_chars": 6000
}
```

Compare two documents:

```json
{
  "left_doc_id": "104352",
  "right_doc_id": "104356",
  "context_lines": 2,
  "max_diff_lines": 200
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
