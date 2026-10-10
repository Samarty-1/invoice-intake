FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[api,demo]"
RUN useradd --create-home app
USER app
EXPOSE 8000
# point at a local model server, e.g. LM Studio on the host:
#   INVOICE_INTAKE_LLM_URL=http://host.docker.internal:1234/v1 INVOICE_INTAKE_MODEL=gemma-4-12b-it-qat
ENV INVOICE_INTAKE_EXTRACTOR=auto
CMD ["invoice-intake", "serve", "--host", "0.0.0.0", "--port", "8000"]
