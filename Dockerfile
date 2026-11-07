FROM python:3.12-slim
WORKDIR /app
COPY pwa/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY pwa/app.py .
COPY pwa/templates ./templates
COPY pwa/static ./static
RUN useradd --system --no-create-home pwa && chown -R pwa:pwa /app
USER pwa
EXPOSE 5000
CMD ["sh", "-c", "waitress-serve --listen=0.0.0.0:${PORT:-5000} app:app"]
