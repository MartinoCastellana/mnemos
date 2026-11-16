# Migrazione su Linux CPU-only — versione attuale

Documento operativo per trasferire l'attuale versione di **Fascicolo AI** su un PC
Linux con Intel Core i7 di dodicesima generazione, 32 GB di RAM e nessuna GPU
dedicata.

La procedura conserva:

- applicazione FastAPI e pipeline Micro-Memory 3.0;
- frontend React/Nginx;
- PostgreSQL 17;
- PyMuPDF e Tesseract `ita+eng`;
- istruzioni in `docs/ISTRUZIONI GLOBALI.md`;
- modello logico Qwen2.5-VL-7B-Instruct quantizzato a 4 bit;
- API OpenAI-compatible sulla porta `8081`.

> Stato della versione documentata: 17 agosto 2026. Prima della migrazione creare
> un archivio del repository nello stato effettivamente installato, perché il progetto
> non deve essere ricostruito affidandosi solo al nome delle immagini Docker `latest`.

## 1. Architettura attuale

| Componente | Versione/configurazione corrente | Porta |
|---|---|---:|
| Frontend | React 19, Vite 6, Nginx 1.27 Alpine | 5174 |
| Backend | Python 3.12, FastAPI, Uvicorn | 8000 |
| Database | PostgreSQL 17 Alpine | interna 5432 |
| Amministrazione DB | Adminer 5 | 8082 locale |
| OCR | PyMuPDF + Tesseract italiano/inglese | — |
| VLM | Qwen2.5-VL-7B-Instruct MLX 4-bit, circa 5,3 GB | 8081 |
| KV cache corrente | 128.000 token, 8 bit | — |

Il backend e gli altri servizi sono eseguiti in Docker. Il server MLX-VLM è avviato
sull'host e viene raggiunto dal backend mediante `host.docker.internal:8081`.

## 2. Limiti della macchina di destinazione

32 GB di RAM sono sufficienti per una singola elaborazione alla volta. La macchina
non deve eseguire due inferenze VLM contemporanee. L'orchestrazione, PostgreSQL, OCR e
rendering sono adatti alla CPU; l'inferenza Vision è il collo di bottiglia.

Configurazione prudenziale:

- una sola run attiva;
- nessun altro modello residente in memoria;
- swap da 16–32 GB come protezione, non come memoria ordinaria del modello;
- contesto VLM iniziale tra 24.576 e 32.768 token;
- nessun parallelismo tra richieste al modello;
- almeno 30 GB liberi per repository, modello, immagini, database e backup.

La pipeline corrente può impiegare ore per fascicoli di alcune decine di pagine su
CPU Intel. La migrazione garantisce l'esecuzione, non le prestazioni interattive.

## 3. Preparazione e backup sul computer sorgente

Eseguire dalla radice del progetto.

```bash
mkdir -p migration-backup
docker compose exec -T postgres pg_dump \
  -U document_ai -d document_ai -Fc \
  > migration-backup/document_ai.dump

docker run --rm \
  -v multiagent_document_storage:/source:ro \
  -v "$PWD/migration-backup:/backup" \
  alpine sh -c 'cd /source && tar czf /backup/document_storage.tar.gz .'

tar --exclude='./migration-backup' \
  --exclude='./.venv*' \
  --exclude='./frontend/node_modules' \
  --exclude='./frontend/dist' \
  --exclude='*/__pycache__' \
  --exclude='*/.pytest_cache' \
  -czf migration-backup/multiagent-current.tar.gz .
sha256sum migration-backup/* > migration-backup/SHA256SUMS
```

Verificare che siano presenti:

- `document_ai.dump`;
- `document_storage.tar.gz`;
- `multiagent-current.tar.gz`;
- `SHA256SUMS`.

Il modello MLX è incluso nell'archivio del repository se la cartella `models/` non è
esclusa. Il modello attuale occupa circa 5,3 GB; verificare la dimensione finale prima
del trasferimento.

## 4. Preparazione del sistema Linux

Distribuzione consigliata: Ubuntu Server 24.04 LTS x86-64 o equivalente recente.

Installare:

```bash
sudo apt update
sudo apt install -y \
  ca-certificates curl git build-essential python3 python3-venv \
  tesseract-ocr tesseract-ocr-ita zstd
```

Installare Docker Engine e il plugin Compose dal repository ufficiale Docker. Al
termine verificare:

```bash
docker version
docker compose version
```

Creare una directory applicativa, ad esempio `/opt/fascicolo-ai`, ed estrarre qui
`multiagent-current.tar.gz`. Evitare di eseguire l'applicazione come `root`.

## 5. Scelta del runtime del modello

Sono possibili due profili. Non combinarli.

### Profilo A — massima fedeltà: MLX-VLM CPU su Linux

Questo profilo mantiene gli stessi pesi MLX e lo stesso server `mlx_vlm.server`.
Richiede una versione MLX dotata di backend Linux CPU e deve essere collaudato sulla
specifica distribuzione prima di trasferire carichi reali.

```bash
cd /opt/fascicolo-ai
python3 -m venv .venv-mlx-linux
.venv-mlx-linux/bin/pip install --upgrade pip
.venv-mlx-linux/bin/pip install 'mlx[cpu]' mlx-vlm
```

Avvio di prova, senza cache KV da 128K:

```bash
.venv-mlx-linux/bin/mlx_vlm.server \
  --host 0.0.0.0 \
  --port 8081 \
  --model /opt/fascicolo-ai/models/Qwen2.5-VL-7B-Instruct-4bit \
  --max-kv-size 32768 \
  --kv-bits 8 \
  --vision-cache-size 1
```

Non usare direttamente `scripts/start_mlx.sh`: è uno script `zsh` preparato per macOS
e configura una cache da 128K. Su Linux deve essere sostituito da un servizio `systemd`
equivalente al comando precedente.

Verifica minima:

```bash
curl -f http://127.0.0.1:8081/v1/models
```

Se installazione, caricamento del modello o inferenza Vision falliscono, usare il
Profilo B. Non convertire automaticamente i pesi MLX esistenti presumendo che siano
equivalenti a un GGUF.

### Profilo B — consigliato su Intel: llama.cpp CPU

Questo profilo conserva Qwen2.5-VL-7B-Instruct e il contratto API, ma cambia runtime e
artefatti del modello. Occorrono il GGUF quantizzato e il relativo proiettore
multimodale `mmproj`, provenienti dalla stessa release compatibile.

Esempio di avvio da adattare ai nomi reali dei file:

```bash
./llama-server \
  --host 0.0.0.0 \
  --port 8081 \
  --model /opt/fascicolo-ai/models/gguf/qwen2.5-vl-7b-q4_k_m.gguf \
  --mmproj /opt/fascicolo-ai/models/gguf/mmproj-qwen2.5-vl-7b-f16.gguf \
  --ctx-size 32768 \
  --threads 8 \
  --threads-batch 8 \
  --parallel 1
```

Impostare `--threads` inizialmente al numero di core fisici disponibili, non al numero
massimo di thread logici. Misurare poi 4, 6, 8 e 10 thread sul medesimo documento.

Il backend corrente accetta già `DOC_AI_MODEL_BACKEND=llama.cpp`; non sono necessarie
modifiche al contratto HTTP `/v1/chat/completions`.

## 6. Override Docker per Linux

Creare sul computer Linux un file non segreto `docker-compose.linux.yml`:

```yaml
services:
  backend:
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      DOC_AI_MODEL_BACKEND: ${DOC_AI_MODEL_BACKEND:-mlx}
      DOC_AI_MODEL_ENDPOINT: http://host.docker.internal:8081
      DOC_AI_MODEL_NAME: ${DOC_AI_MODEL_NAME:-/opt/fascicolo-ai/models/Qwen2.5-VL-7B-Instruct-4bit}
```

Per il Profilo B impostare nell'ambiente:

```bash
export DOC_AI_MODEL_BACKEND=llama.cpp
export DOC_AI_MODEL_NAME=qwen2.5-vl-7b-instruct
```

Il valore di `DOC_AI_MODEL_NAME` deve corrispondere a quello accettato dal server. Il
server del modello resta sull'host; non deve essere esposto alla rete pubblica.

Avviare lo stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.linux.yml up -d --build
```

## 7. Ripristino dei dati

Arrestare prima il backend per evitare scritture durante il ripristino:

```bash
docker compose stop backend
docker compose exec -T postgres pg_restore \
  -U document_ai -d document_ai --clean --if-exists \
  < migration-backup/document_ai.dump

docker run --rm \
  -v multiagent_document_storage:/target \
  -v "$PWD/migration-backup:/backup:ro" \
  alpine sh -c 'cd /target && tar xzf /backup/document_storage.tar.gz'

docker compose start backend
```

Il volume può avere un prefisso diverso se la directory Compose non si chiama
`multiagent`. Verificarlo prima con `docker volume ls`.

## 8. Collaudo obbligatorio

### Servizi

```bash
docker compose ps
curl -f http://127.0.0.1:8000/api/health
curl -fI http://127.0.0.1:5174/
curl -f http://127.0.0.1:8081/v1/models
```

### OCR

```bash
docker compose exec backend tesseract --list-langs
```

L'output deve contenere almeno `eng` e `ita`.

### Test applicativi

1. Caricare un PDF di una pagina noto.
2. Verificare la creazione di una Micro-Memory.
3. Controllare che le bounding box siano comprese tra `0` e `1`.
4. Controllare candidati e selezione del protocollo.
5. Modificare manualmente un campo e ricaricare la pagina.
6. Verificare l'evento `MANUAL_EDIT` nell'audit.
7. Riavviare il backend durante un fascicolo di prova e verificare il recupero.

Non iniziare il collaudo con fascicoli da centinaia di pagine.

## 9. Benchmark di accettazione

Usare sempre lo stesso PDF campione da 10 pagine e registrare:

- tempo totale;
- secondi per pagina;
- RAM massima (`docker stats` e `systemd-cgtop`);
- numero di candidati prodotti e scartati;
- pagine senza candidati;
- errori JSON e timeout;
- protocollo finale e relativa pagina;
- temperatura e throttling della CPU.

Eseguire tre prove consecutive. Il sistema è accettabile solo se termina tutte e tre
senza swap continuo, riavvii del model server o output semanticamente degradati.

## 10. Configurazione di esercizio consigliata

- un solo worker Uvicorn;
- una sola elaborazione documentale attiva;
- model server gestito da `systemd` con riavvio su errore;
- backend avviato solo dopo il health check del modello;
- backup giornaliero PostgreSQL e volume documentale;
- accesso pubblico solo attraverso reverse proxy HTTPS;
- porte `8000`, `8081` e `8082` non esposte su Internet;
- conservazione dei log e rotazione configurata;
- gruppo di continuità se la macchina elabora fascicoli per diverse ore.

## 11. Rollback

Conservare sorgente, dump e volume originali fino al completamento del collaudo. In
caso di problemi:

1. fermare lo stack Linux;
2. non modificare ulteriormente il dump sorgente;
3. riattivare la macchina precedente;
4. verificare `/api/health` e un documento già completato;
5. trasferire sulla macchina precedente solo eventuali modifiche manuali prodotte dopo
   il backup, mediante export controllato e non copiando direttamente i file del DB.

La migrazione si considera conclusa solo dopo avere validato prestazioni, protocollo,
indirizzo, dati catastali, navigazione alla pagina e persistenza delle modifiche manuali.
