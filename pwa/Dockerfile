FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY templates ./templates
COPY static ./static
RUN useradd --system --no-create-home pwa && chown -R pwa:pwa /app
USER pwa
EXPOSE 5000
CMD ["waitress-serve", "--listen=0.0.0.0:5000", "app:app"]
