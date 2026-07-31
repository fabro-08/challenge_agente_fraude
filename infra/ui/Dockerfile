FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir streamlit pandas plotly httpx

COPY src/ /app/src

ENV PYTHONPATH=/app
ENV API_URL=http://api:8000

EXPOSE 8501

CMD ["streamlit", "run", "src/ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
