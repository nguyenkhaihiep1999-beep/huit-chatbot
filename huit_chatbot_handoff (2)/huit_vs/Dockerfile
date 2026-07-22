FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# Hugging Face Spaces default port is 7860
EXPOSE 7860

# Command to run FastAPI server on 0.0.0.0:7860
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "7860"]
