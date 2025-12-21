# Project Prime Migration Plan: Clean History Strategy

## 1. Strategy Overview
To ensure `my-prime-jennie` and `our-prime-jennie` start with a pristine git history and a fully working "One-Click" setup, we will execute all structural changes (MariaDB containerization, Installer script) within the **current repository** (`carbon-silicons-council`) first. Only after full verification will we copy the finalized files to the new repositories.

---

## 2. Phase 1: In-Place Modernization (Current Repo)
*Execute these steps in the current `carbon-silicons-council` repository.*

### A. MariaDB Dockerization (Priority 1)
Migrate the database from Windows Host to a Docker container to ensure system portability.
1.  **Snapshot Data**: Export current schema and data from Windows MariaDB.
    -   Command: `mysqldump -u root -p --all-databases > docker/init/init_dump.sql`
2.  **Docker Compose Update**:
    -   Add `mariadb` service to `docker-compose.yml`.
    -   Host Port: `3306` (or `3307` to avoid conflict during transition).
    -   Volume: `./data/mariadb:/var/lib/mysql` (Local persistence).
    -   Config: Map `my.cnf` for UTF-8MB4 settings.
3.  **App Configuration**:
    -   Update `secrets.json` or `.env` to point `MARIADB_HOST` to `mariadb` (service name) or `localhost` (if running script outside docker).
    -   Update `shared/db/connection.py` to handle Docker-to-Docker communication.

### B. Universal Installer Script (Priority 2)
Develop `scripts/install_prime.sh` to construct a trading environment from a fresh Ubuntu WSL2 state.
1.  **Prerequisites**: Check for `nvidia-smi` (GPU), Internet connection.
2.  **System Packages**: `apt install docker.io docker-compose-v2 python3-venv build-essential ...`
3.  **NVIDIA Container Toolkit**: Auto-install script to enable GPU access for `qwen3`.
4.  **Environment Setup**:
    -   `python3 -m venv venv`
    -   `source venv/bin/activate && pip install -r requirements.txt`
5.  **Data Initialization**:
    -   Create directory structure (`data/`, `logs/`, `models/`).
    -   Download/Pull LLM models (Ollama).

### C. Verification
1.  **Test Clean Install**: Create a fresh directory, copy files, run `install_prime.sh`.
2.  **Test DB**: Ensure data persists after `docker-compose down && docker-compose up`.
3.  **Test Trading**: Execute a dry-run `scout-job` to verify end-to-end connectivity.

---

## 3. Phase 2: The "Prime" Genesis (New Repos)
*Execute this only after Phase 1 is verified.*

### A. Private Prime (`my-prime-jennie`)
1.  Create local directory `my-prime-jennie`.
2.  **File Copy**: Copy all files from verification build **excluding** `.git`, `.idea`, `__pycache__`, and temporary logs.
3.  **Git Init**: Initialize new git repo.
4.  **First Commit**: "Initial Commit: Project Prime v1.0".

### B. Public Prime (`our-prime-jennie`)
1.  Clone `my-prime-jennie` to `our-prime-jennie`.
2.  **Sanitization**:
    -   Remove `secrets.json` (Ensure `.env.example` exists).
    -   Remove proprietary strategy files (e.g., `shared/strategy/alpha_logic.py`, `utilities/proprietary_*.py`).
    -   Replace complex Alpha logic with "Basic Moving Average" examples.
3.  **Git Init**: Initialize new git repo.
4.  **First Commit**: "Initial Commit: Open Source Trading Engine".

---

## 4. Execution Checklist
- [ ] **[DB]** Create `docker/mariadb/` directory and config.
- [ ] **[DB]** Dump Host DB.
- [ ] **[DB]** Update `docker-compose.yml`.
- [ ] **[Script]** Write `scripts/install_prime.sh`.
- [ ] **[Verify]** Confirm local `scout-job` runs with Docker DB.
