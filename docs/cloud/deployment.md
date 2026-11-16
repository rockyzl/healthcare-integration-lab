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

Stop the dedicated VM when the demo is not needed (the integration page's database-backed operations will become unavailable):

```bash
gcloud compute instances stop healthcare-integration-lab --zone us-central1-a --project lu-personal-tools
# Resume with the same command using 'start'. Docker services restart automatically.
```

The disk remains billed while stopped and retains the database volumes. Do not delete the disk or use `docker compose down -v` unless intentionally discarding the demonstration records.

### On-demand operation — updated 2026-11-16

**Latest owner decision:** after the cost-control stop below, the VM was restarted at 2026-11-16 17:46:37 UTC for a one-week demo window. Its seven-day maximum runtime will stop it around 2026-11-23 17:46 UTC. The public gateway separately enforces `INTEGRATION_CLOSES_AT=2026-11-23T17:46:37Z` and shows a temporary-closure notice after that time. A private Drive backup now contains all application tables, saved reviews, a native SQL Server backup, source and restore instructions; restoration into isolated SQL/Oracle namespaces and content checksums passed. The original disk has not been deleted. Reopening after the deadline requires an intentional VM start and gateway deadline update.

Earlier on 2026-11-16, the VM was stopped for cost control and its state was verified as `TERMINATED` (Google's name for a stopped, restartable VM), with the 50 GiB disk still attached and `READY`. While stopped, the public integration HTML can load but database-backed requests are unavailable. The other billing/CMS demos do not depend on this VM.

The cloud-native scheduling policy now has `maxRunDuration.seconds=604800` and `instanceTerminationAction=STOP`: each manual start can run for at most seven days before Compute Engine stops it. This is not a recurring start schedule and does not delete the VM or disk. There is no separate scheduler service to pay for. The configuration was read back from the API; an actual seven-day expiration has not yet elapsed/tested. See [Google's runtime-limit documentation](https://docs.cloud.google.com/compute/docs/instances/limit-vm-runtime).

For a short interview demo, use a two-hour window instead. Change the duration only while the VM is stopped, and start only if the scheduling update succeeds:

```bash
gcloud compute instances set-scheduling healthcare-integration-lab \
  --zone us-central1-a --project lu-personal-tools \
  --max-run-duration=2h --instance-termination-action=STOP
# After success:
gcloud compute instances start healthcare-integration-lab \
  --zone us-central1-a --project lu-personal-tools
```

Use `--max-run-duration=7d` before starting if a one-week review window is needed. Containers use `restart: unless-stopped` and database volumes are persistent; allow initialization time and check both engines/API before sharing the link. Do not manually stop individual containers and assume they will auto-start. The internal IP is retained across stop/start; the ephemeral public IP can change. No paid static public IP was reserved for this VM.

Estimated infrastructure costs at current Iowa list prices, excluding model calls, traffic, taxes and other services:

| Usage in a 730-hour month | VM compute + ephemeral IPv4 + retained disk |
|---|---:|
| Always running | $57.57 |
| One seven-day window (168 hours) | $17.10 |
| Ten hours total | $5.72 |
| Stopped throughout | $5.00 |

Formula: `$5 + running_hours * ($0.06701142 + $0.005)`. Disk is 50 GiB balanced at about $0.10/GiB-month. Compute and ephemeral external-IP charges stop when the VM is stopped; historical charges already incurred remain due. [Disk pricing](https://cloud.google.com/compute/disks-image-pricing), [IPv4 pricing](https://cloud.google.com/vpc/network-pricing).

This seven-day runtime limit is not a monthly dollar cap: repeated starts, Vertex requests and other resources can add charges. For zero ongoing disk cost, a separate verified backup/restore and disk-removal decision is required; that destructive step has not been taken.
