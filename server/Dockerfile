FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m fph && chown -R fph /srv
USER fph
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m app.serve"]
