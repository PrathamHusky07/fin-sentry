FROM python:3.13-slim

WORKDIR /app

# Shares the project's one requirements.txt rather than a separate
# dashboard-only dependency file -- this pulls in gateway-only packages
# (torch, nemoguardrails) the dashboard never imports, which is unused image
# weight. Accepted for Day 8: one dependency source of truth, not a second
# requirements file to keep in sync, for a service that isn't the
# performance-sensitive one in this topology.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY finsentry/ ./finsentry/

ENV PYTHONUNBUFFERED=1

EXPOSE 8081

CMD ["uvicorn", "finsentry.dashboard.app:app", "--host", "0.0.0.0", "--port", "8081"]
