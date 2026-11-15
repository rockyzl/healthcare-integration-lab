# Cloud integration runtime

Public entry: https://revenue-cycle-agent-1038659864130.us-central1.run.app/integration

The public HTML and gateway live in the separate [revenue-cycle-agent](https://github.com/rockyzl/revenue-cycle-agent) repository. This repository owns the integration API, actual SQL Server/Oracle storage, FHIR importer, and LangGraph/Vertex agent.

## Deployment boundary

- GCP project `lu-personal-tools`, VM `healthcare-integration-lab`, zone `us-central1-a`, `e2-standard-2` (2 vCPU / 8 GiB), 50 GB balanced persistent boot disk.
- Docker Compose runs SQL Server 2022 Developer, Oracle Database Free, and one integration API worker. Database volumes persist across container and VM restarts. This is a development demonstration, not licensed SQL Server production hosting.
- SQL Server and Oracle bind only to VM loopback. The API uses port 8780 and is reachable from the Cloud Run subnet. VM-specific firewall rules allow SSH only via IAP, allow the API from the VPC subnet, and deny other inbound traffic.
- The existing Cloud Run service uses Direct VPC egress for private IP traffic. It mints a Google ID token with the configured audience; the VM validates signature, audience, expiry and the verified gateway service-account email.
- The VM service account has Vertex AI User permission. Model inference uses metadata credentials, not a browser API key. The configured model remains `gemini-3.8-flash`.
- The gateway exposes only the fixed integration operations. Mutations require same-origin browser requests with a custom header, bounded body size and shared daily budgets (40 drafts, 200 other writes). These are spending/CSRF boundaries for a public synthetic-data lab, not private patient authentication.
- Staff review here is shared demonstration logic persisted in SQL Server. The **other** billing demo uses Identity Platform and real UiPath Maestro / Action Center. The two source-specific test populations are not silently mapped together.

## Reproduce on a dedicated VM

Create a private `.env.cloud` based on `.env.example` with fresh passwords, project/region/model, plus `LAB_CLOUD=true`, `LAB_ALLOWED_HOSTS`, `LAB_TOKEN_AUDIENCE`, and `LAB_GATEWAY_EMAIL`. Never put this file in an image or Git. Install Docker and Compose v2. From this repository:

```bash
docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml up -d sqlserver oracle
docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml build app
# Wait for both engines to initialize.
docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml run --rm app python scripts/bootstrap.py
docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml up -d app
```

Set gateway `INTEGRATION_BACKEND_URL` to the private API URL and `INTEGRATION_TOKEN_AUDIENCE` to the exact audience. Use one API worker because import/draft serialization is process-local.

## Costs and lifecycle

At the official Iowa list price observed on 2026-11-14, the VM compute rate is $0.06701142/hour, approximately $48.92 for 730 hours. Disk, external IPv4, egress, Cloud Run and Vertex calls are additional; this is an estimate, not a spending cap. [Official VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose).

Stop the dedicated VM when the demo is not needed (the online integration page will become unavailable):

```bash
gcloud compute instances stop healthcare-integration-lab --zone us-central1-a --project lu-personal-tools
# Resume with the same command using 'start'. Docker services restart automatically.
```

The disk remains billed while stopped and retains the database volumes. Do not delete the disk or use `docker compose down -v` unless intentionally discarding the demonstration records. There is no automatic shutdown schedule.
