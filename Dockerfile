FROM python:3.9

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV PORT=7860
EXPOSE 7860

CMD ["python", "app.py"]