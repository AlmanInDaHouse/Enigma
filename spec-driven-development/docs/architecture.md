# Enigma — Arquitectura

> Vista detallada de componentes, flujos y decisiones de despliegue.

---

## 1. Diagrama de componentes (alto nivel)

```mermaid
flowchart TB
    subgraph Cliente
        OBS[Obsidian App]
        CLI[enigma-cli]
    end

    subgraph Servidor["Servidor (máquina admin)"]
        API[FastAPI :8077]
        WATCHER[File Watcher]
        QUEUE[(SQLite Queue)]
        VAULT[(Vault Markdown<br/>+ Git)]

        subgraph Workers
            ING[Ingestor]
            TRANS[Transcriptor<br/>faster-whisper]
            EXT[Extractor<br/>Ollama LLM]
            VECT[Vectorizer]
            AGT[Agente RAG]
        end

        subgraph Infra
            OLL[Ollama :11434]
            QDR[(Qdrant :6333)]
        end
    end

    CLI -- HTTP --> API
    OBS -- read/write --> VAULT
    API --> QUEUE
    QUEUE --> ING
    ING --> TRANS
    TRANS --> EXT
    EXT --> VAULT
    VAULT -- file events --> WATCHER
    WATCHER --> VECT
    VECT --> QDR
    TRANS -.uses.-> OLL
    EXT -.uses.-> OLL
    AGT -.uses.-> OLL
    AGT -.queries.-> QDR
    API --> AGT
```

---

## 2. Flujo principal: de audio a nota conectada

```mermaid
sequenceDiagram
    autonumber
    participant U as Usuario
    participant C as enigma-cli
    participant A as API
    participant Q as Cola (SQLite)
    participant I as Ingestor
    participant T as Transcriptor
    participant E as Extractor
    participant V as Vault Writer
    participant W as Watcher
    participant VE as Vectorizer
    participant QD as Qdrant

    U->>C: enigma ingest audio.wav
    C->>A: POST /ingest (multipart)
    A->>Q: enqueue(call_id)
    A-->>C: 202 Accepted (call_id)
    Q->>I: dispatch
    I->>T: transcribe(audio)
    T->>T: faster-whisper + pyannote
    T->>E: transcript.json
    E->>E: chunk + LLM extract
    E->>V: List[Note]
    V->>V: idempotent upsert .md
    V-->>VAULT: write files
    Note over W: file watcher detecta
    W->>VE: note paths
    VE->>VE: embed + link suggestion
    VE->>QD: upsert vectors
    VE-->>V: update wikilinks
```

---

## 3. Flujo de consulta (RAG)

```mermaid
sequenceDiagram
    autonumber
    participant U as Usuario
    participant C as enigma-cli
    participant A as API
    participant AG as Agente
    participant QD as Qdrant
    participant OL as Ollama

    U->>C: enigma ask "¿qué decidimos sobre captación de padel?"
    C->>A: POST /ask
    A->>AG: query
    AG->>OL: embed(query)
    OL-->>AG: vector
    AG->>QD: search top-k
    QD-->>AG: notas relevantes
    AG->>OL: LLM(query + contexto)
    OL-->>AG: respuesta + citas
    AG-->>A: respuesta con [[wikilinks]]
    A-->>C: JSON
    C-->>U: texto formateado
```

---

## 4. Topología de despliegue

```mermaid
flowchart LR
    subgraph Admin["Máquina Admin (Manuel)"]
        DK[Docker Desktop]
        OL2[Ollama]
        API2[API Enigma]
        VAULT2[Vault local]
        DK --> QD2[Qdrant container]
    end

    subgraph User1["Usuario 1"]
        OBS1[Obsidian + obsidian-git]
        VAULT_U1[Vault clonado]
    end

    subgraph User2["Usuario 2-5"]
        OBS2[Obsidian + obsidian-git]
        VAULT_U2[Vault clonado]
    end

    GH[(GitHub: Enigma-Vault.git)]

    VAULT2 <--> GH
    VAULT_U1 <--> GH
    VAULT_U2 <--> GH

    User1 -. opcional .-> API2
    User2 -. opcional .-> API2
```

**Notas:**
- El procesamiento pesado (transcripción + LLM) corre **solo en la máquina admin**. Los demás usuarios consumen las notas vía Obsidian.
- Si un usuario quiere ingerir un audio, lo envía al admin (drag-and-drop en una carpeta compartida, o vía CLI apuntando a la API).
- El Vault se sincroniza vía **Git** (no Syncthing).

---

## 5. Layout del Vault de Obsidian

```
vault/
├── .obsidian/                  # config compartida (themes, plugins)
├── .gitignore                  # ignora workspace.json local
├── inbox/                      # notas recién extraídas, sin validar
│   └── 2026-05-14-estrategia-captacion-padel-8f2a1c.md
├── notes/                      # notas validadas (movidas desde inbox)
│   └── estrategia-captacion-padel-8f2a1c.md
├── calls/                      # nota índice por llamada
│   └── 2026-05-14-brainstorm-captacion.md
├── people/                     # notas-entidad por persona (v2)
│   └── manuel.md
├── topics/                     # hubs temáticos (v2)
│   └── padel.md
├── decisions/                  # decisiones extraídas (v2)
│   └── 2026-05-14-precio-equipacion-padel.md
└── tasks/                      # tareas extraídas (v2)
    └── tasks.md
```

**Convenciones:**
- Una nota cambia de carpeta solo cuando un humano la valida (mueve de `inbox/` a `notes/`).
- El status del frontmatter se actualiza al mover: `draft → validated`.
- `archived/` es opcional para notas obsoletas que no queremos borrar.

---

## 6. Plugins recomendados de Obsidian

Los plugins se versionan en `vault/.obsidian/community-plugins.json`:

- `obsidian-git` — sync automático con GitHub
- `dataview` — queries sobre el frontmatter (decisiones, tareas, etc.)
- `templater` — plantillas para notas creadas a mano
- `graph-analysis` — métricas del grafo (centralidad, comunidades)
- `excalidraw` — diagramas embebidos (ya tienes el conector Excalidraw)

---

## 7. Modelo de seguridad

- **Repositorio del Vault privado** en GitHub (no público).
- Acceso por SSH key por usuario.
- Audios nunca se commitean al Vault (solo notas derivadas).
- Audios en disco local del admin, en carpeta `data/audio/` excluida por `.gitignore`.
- Variables sensibles en `.env`, fuera del repo.
- En v2: cifrado at-rest de audios con `cryptography`/`age`.
