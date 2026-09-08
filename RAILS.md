# Rail inventory

| Name | Layer | Purpose | Latency budget |
|------|-------|---------|----------------|
| prompt-guard-2 | input | Detects direct prompt injection attempts via Llama Prompt Guard 2 86M | 20-50 ms |
| pii-redaction | input | Redacts SSN, credit card, email, phone, bank account, and IBAN entities via Presidio | 30-80 ms |
| llama-guard-3 | input | Flags requests against Meta's hazard taxonomy via Llama Guard 3 8B NF4 | 500-1500 ms |
