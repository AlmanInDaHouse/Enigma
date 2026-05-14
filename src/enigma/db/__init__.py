"""Persistencia SQLite compartida (`calls`, transcripts en T-104, jobs futuros).

Solo contiene **infraestructura**: conexión, esquema, helpers CRUD por tabla.
La lógica de negocio (`register_call`, etc.) vive en los módulos de dominio
(`enigma.ingest`, `enigma.extract`, ...) y consume este paquete.
"""
