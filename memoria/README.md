# memoria/ — memoria administrada en tres capas

Carpeta para administrar la memoria del ecosistema de trabajo. **Ninguna capa
es un volcado**: cada entrada es `tipo + idea + explicación` de **máximo 300
palabras** (el gestor la rechaza si se pasa — fail-closed).

```
memoria/
  cache/        datos MOMENTÁNEOS (TTL). Se purgan con `purgar_cache()`.
                No se commitea (ver .gitignore: memoria/cache/).
  chat/         datos BUSCABLES dentro de UN proyecto: chat/<proyecto>/<id>.json
                Solo entran las cosas más relevantes (relevancia >= 0.5);
                el resto se rechaza en la admisión.
  ecosistema/   memoria GLOBAL entre todos los proyectos: ecosistema/<id>.json
                (el campo `proyecto` es la etiqueta de origen).
```

Administración desde Python (`src/harness_candy/memoria.py`) o desde la CLI:

```bash
scripts/memoria guardar-chat Harness-Candy decision "usamos BM25 local" "sin dependencias externas" --relevancia 0.9
scripts/memoria guardar-cache borrador estado "compilando ola 8" --ttl 600
scripts/memoria guardar-eco patron "300 palabras por entrada" "tipo+idea+explicacion, nada mas" --proyecto Harness-Candy
scripts/memoria buscar chat "por que BM25?" --proyecto Harness-Candy
scripts/memoria buscar ecosistema "memoria"
scripts/memoria purgar        # borra cache expirada
scripts/memoria listar chat --proyecto Harness-Candy
scripts/memoria stats
```

Búsqueda: BM25 léxico (reusa `rag.BM25Index`) sobre `tipo + idea + explicacion + tags`.
