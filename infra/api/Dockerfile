FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    psycopg2-binary \
    langgraph \
    langchain-openai \
    langchain-core \
    pandas \
    pyyaml \
    python-dotenv

COPY src/ /app/src

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
