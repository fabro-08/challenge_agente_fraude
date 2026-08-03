FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --retries 10 --timeout 300 \
    fastapi==0.140.13 \
    uvicorn[standard]==0.52.0 \
    psycopg2-binary==2.9.12 \
    langgraph==1.2.10 \
    langchain-openai==1.4.1 \
    langchain-core==1.5.3 \
    pandas==3.0.5 \
    pyarrow==24.0.0 \
    openpyxl==3.1.5 \
    PyYAML==6.0.3 \
    python-dotenv==1.2.2

COPY src/ /app/src
COPY docs/politicas_decision.md /app/docs/politicas_decision.md
COPY data/casos_con_features.parquet /app/data/casos_con_features.parquet

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
