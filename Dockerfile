# Container image for the public HTTP MCP server (e.g. https://mcp.librarycard.net/mcp).
# The image holds code + catalog only; data is fetched from publishers at request time.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY schema ./schema
COPY catalog ./catalog
COPY ops ./ops
RUN pip install --no-cache-dir . && useradd -m odc
USER odc
ENV ODC_HOST=0.0.0.0 ODC_PORT=8080 ODC_REPO_ROOT=/app ODC_CACHE_DIR=/tmp/odc-cache
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=5)"
CMD ["odc-server", "--http"]
