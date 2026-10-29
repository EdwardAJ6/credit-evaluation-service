# Credit Evaluation Service

Servicio HTTP que evalúa solicitudes de crédito con la política de riesgo de cada producto (PHONE, TWIST, CARD), guarda cada solicitud con su decisión y sus razones, y permite consultarlas, listarlas con filtros y reevaluarlas con la política vigente.

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2, SQLite, pytest, Docker y GitHub Actions.

## Cómo correrlo

### Con Docker

```bash
docker compose up --build              # API en http://localhost:8000 · docs en /docs
docker compose run --rm app pytest -v  # tests dentro del contenedor
```

Compose define `API_KEY=dev-api-key`, una clave **solo para desarrollo** (ver [Autenticación](#autenticación)). La base SQLite vive en el volumen `data`. Para empezar de cero: `docker compose down -v`, que **borra todas las solicitudes**.

Compose construye la etapa `dev` del Dockerfile, que incluye pytest. La imagen de producción es la etapa `runtime`, la última, así que un `docker build .` la produce: tiene solo el entorno virtual y `app/`, y corre con un usuario no-root.

### Local, sin Docker

Requiere **Python 3.11–3.13**; se recomienda 3.12, el mismo de Docker y del CI. Con 3.14 o superior la instalación falla, porque las versiones fijadas de `pydantic` dependen de un `pydantic-core` sin wheels para esas versiones.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export API_KEY=dev-api-key       # PowerShell: $env:API_KEY = "dev-api-key"
uvicorn app.main:app --reload    # usa ./credit_eval.db (variable DATABASE_URL)
```

Sin `API_KEY` la app no arranca: falla cerrada a propósito.

### Tests y gates de calidad (los mismos del CI)

```bash
pytest -v
ruff check . && ruff format --check .
coverage run --branch --source=app -m pytest
coverage report --show-missing --fail-under=90                 # total ≥ 90 %
coverage report --include='app/strategies/*' --fail-under=100  # políticas = 100 %
```

Estado actual: 146 tests en verde, 97 % de cobertura de ramas en total y 100 % en `app/strategies/`.

Los nombres de los tests indican qué verifican: el criterio de aceptación (`test_ac02_…`), los casos de referencia de negocio (`R01`…`R23`) y los casos borde de validación y de autenticación (`E01`…`E30`).

## Reglas de evaluación

| Producto | Política | Aprueba si… |
| --- | --- | --- |
| PHONE | Conservadora | `score ≥ 700` y `employment_months ≥ 12` y `cuota ≤ 25 %` del ingreso |
| TWIST | Estándar | `score ≥ 600` y `cuota ≤ 35 %` del ingreso |
| CARD | Agresiva | (`score ≥ 550`, o `score ≥ 500` con `monthly_income ≥ 3.000.000`) **y** `cuota ≤ 50 %` del ingreso **y** `amount ≤ 20.000.000` ¹ |

¹ La cuota y el cupo de CARD no están en el enunciado: se agregaron por el hallazgo que se explica en [Hallazgo: CARD aprobaba créditos impagables](#hallazgo-card-aprobaba-créditos-impagables).

- **Cuota:** `amount / 12`. Se compara solo con enteros, como `100·amount ≤ pct·12·ingreso`: es exacto y funciona con ingreso 0.
- **Razones de rechazo:** cada política informa **todas** las condiciones incumplidas, en el orden de la tabla. En CARD, si falla la regla de score, se informa el score (citando 500 si el ingreso alcanza; si no, 550) y, si el ingreso no llega a 3.000.000, también el ingreso. Después van la cuota y el cupo.
- **Códigos:** forman un catálogo cerrado (`SCORE_BELOW_MINIMUM`, `EMPLOYMENT_BELOW_MINIMUM`, `INSTALLMENT_ABOVE_LIMIT`, `INCOME_BELOW_MINIMUM`, `AMOUNT_ABOVE_LIMIT`). Los `message` son solo informativos.

### Hallazgo: CARD aprobaba créditos impagables

**Qué se encontró.** La regla del enunciado para CARD solo mira el score y, en la vía de score reducido, el ingreso. No controla la capacidad de pago. Aplicada literalmente, una solicitud con score 550, **ingreso 0** y un monto de **100.000.000** se aprobaba.

**Por qué se cambió.** En un producto real ese resultado es una pérdida casi segura, y las otras dos políticas ya controlan la cuota. Aplicar la regla literal era defendible para una prueba técnica, pero se decidió tratar el servicio como producto real y cerrar el hueco.

**Qué se hizo.** CARD ahora exige, además de su regla original:

- **Cuota ≤ 50 % del ingreso.** Es el techo habitual de endeudamiento (el mismo que usa la libranza en Colombia) y queda por encima del 35 % de TWIST, así que CARD sigue siendo la más permisiva en score y en porcentaje de cuota.
- **Monto ≤ 20.000.000.** El tope de cuota escala con el ingreso; el cupo limita la exposición en ingresos altos. Por eso, con ingresos altos CARD puede rechazar montos que TWIST aprobaría (por ejemplo, 30.000.000 con ingreso 10.000.000).

Las dos razones que CARD ahora puede dar (`INSTALLMENT_ABOVE_LIMIT`, la misma de PHONE y TWIST, y `AMOUNT_ABOVE_LIMIT`, nueva) se suman a las de score e ingreso, así que el rechazo explica todo lo que falló. El caso que originó el hallazgo queda fijado por un test: ahora sale `REJECTED` por cuota y por cupo. Los dos umbrales son parámetros de `AggressivePolicy`: si Riesgo los cambia, basta con un deploy y un `POST /applications/{id}/reevaluate` para recalcular las solicitudes existentes, y cada evaluación guarda con qué umbrales se tomó.

## API

Todas las rutas de `/applications` exigen el header `X-API-Key` (ver [Autenticación](#autenticación)); `/health`, `/docs` y `/openapi.json` son públicas.

| Método y ruta | Respuesta |
| --- | --- |
| `POST /applications` | `201` con `Location: /applications/{id}`, también si la solicitud se rechaza |
| `GET /applications/{id}` | `200`; `404` si no existe |
| `GET /applications?status=&product=&limit=&offset=` | `200`, lista ordenada de la más nueva a la más vieja (máximo 100) |
| `POST /applications/{id}/reevaluate` | `200`, con la decisión recalculada con la política vigente |
| `GET /health` | `200`, `{"status": "ok"}` |

```bash
KEY='X-API-Key: dev-api-key'

# PHONE aprobada
curl -i -X POST localhost:8000/applications -H "$KEY" -H 'content-type: application/json' \
  -d '{"amount": 2400000, "monthly_income": 1500000, "employment_months": 24, "external_score": 750, "product": "PHONE"}'

# CARD rechazada: score 549 con ingreso menor a 3.000.000
curl -X POST localhost:8000/applications -H "$KEY" -H 'content-type: application/json' \
  -d '{"amount": 1000000, "monthly_income": 2999999, "employment_months": 0, "external_score": 549, "product": "CARD"}'

curl -H "$KEY" 'localhost:8000/applications?status=REJECTED&product=CARD'
curl -H "$KEY" -X POST localhost:8000/applications/1/reevaluate
```

Respuesta de un rechazo:

```json
{
  "id": 2,
  "amount": 1000000,
  "monthly_income": 2999999,
  "employment_months": 0,
  "external_score": 549,
  "product": "CARD",
  "status": "REJECTED",
  "rejection_reasons": [
    {"code": "SCORE_BELOW_MINIMUM", "message": "external_score 549 is below the minimum 550"},
    {"code": "INCOME_BELOW_MINIMUM", "message": "monthly_income 2999999 is below the minimum 3000000 required to qualify with external_score from 500 to 549"}
  ],
  "created_at": "2026-10-29T14:28:15.850574Z",
  "evaluated_at": "2026-10-29T14:28:15.850574Z"
}
```

Una entrada inválida responde `422` sin guardar nada: por ejemplo, enteros enviados como `true`, `"1000"` o `1000.0`, campos desconocidos o valores fuera de rango.

### Autenticación

Es una **API key compartida**, porque a este servicio lo llaman sistemas internos (servicio a servicio), no personas:

- El cliente envía `X-API-Key: <clave>`; el servidor la compara con la variable `API_KEY` usando `secrets.compare_digest` sobre bytes. Comparar `str` fallaba con un 500 ante un header no ASCII.
- Sin clave o con otra clave responde `401` con `WWW-Authenticate: ApiKey`, **antes** de validar la entrada, así que un anónimo no recibe detalles de validación. La única excepción es un JSON mal formado: FastAPI lo rechaza con `422` antes de resolver la auth, y ese `422` no incluye datos.
- No hay clave por defecto en el código ni en la imagen, y la app no arranca sin `API_KEY`.
- En `/docs`, el botón **Authorize** pide la clave.

Se evaluó portar una autenticación JWT con usuarios (email y contraseña) de otro proyecto y se descartó. Modela personas, no sistemas, y traía 4–5 dependencias, dos de ellas con CVE publicados (`python-jose 3.3.0` y `PyJWT 2.8.0`), además de `passlib` sin mantenimiento, un secreto por defecto en el código y registro abierto. La API key cubre el riesgo principal sin dependencias nuevas.

## Arquitectura

```text
app/
├── main.py                       # composición: lifespan, handler de 422, router, /health
├── api.py                        # rutas HTTP y API key; inyecta sesión y políticas con Depends
├── schemas.py                    # validación de entrada y serialización (Pydantic)
├── domain.py                     # Product, Status, ReasonCode, Reason (sin frameworks)
├── strategies/policies.py        # políticas (Strategy) y su registro get_policies()
├── services/applications.py      # casos de uso; un único commit por escritura
├── repositories/applications.py  # únicas consultas SQLAlchemy
├── models.py                     # tablas applications y evaluations
└── database.py                   # engine, sesión y get_db
```

Es una arquitectura en capas con un núcleo de dominio que no depende de FastAPI ni de SQLAlchemy:

- **Strategy para las políticas.** Cada política es una dataclass inmutable cuyos campos son sus umbrales, y se prueba sin HTTP ni base de datos.
- **Registro inyectado en lugar de `if/elif`.** `get_policies()` devuelve `producto → política` y la API lo recibe con `Depends`. Un producto nuevo es una entrada más, y los tests cambian umbrales con `dependency_overrides`.
- **Repository.** Las rutas llaman al servicio, y las consultas viven solo en el repositorio.
- **Service layer con unit of work.** El servicio orquesta cada caso de uso y hace un único `commit` por escritura.

**Alternativas descartadas:**

- Lógica en el endpoint: viola las dos restricciones de diseño del enunciado.
- Hexagonal con puertos explícitos: cada puerto tendría una sola implementación.
- Clean Architecture completa: unas 3 veces más archivos para 4 endpoints.

Respecto de la estructura sugerida, se agregaron `api.py` (las rutas salen de `main.py`, que queda como raíz de composición) y `domain.py` (tipos sin dependencias de frameworks).

### Reevaluación e historial (bonus)

Cada evaluación se agrega a la tabla `evaluations` con una foto de la política usada (nombre y umbrales), y nunca se modifica ni se borra. La solicitud guarda una copia de la decisión vigente, que es la evaluación de mayor `id`; así el GET y los filtros leen una sola tabla. Ambas escrituras van en el mismo `commit`.

**Alternativas descartadas:**

- Sobrescribir la decisión: perdería una decisión de crédito ya comunicada y no podría explicar por qué cambió.
- Historial como lista JSON dentro de la solicitud: dos reevaluaciones simultáneas se pisarían.

## Decisiones y desviaciones del enunciado

| Decisión | Por qué |
| --- | --- |
| Cuota comparada solo con enteros | Con `float`, `amount/12 <= ingreso*0.35` rechaza casos justo en el límite. Ejemplo: TWIST con monto 5.880.000 e ingreso 1.400.000 tiene una cuota de exactamente el 35 %, y el cálculo con decimales la rechaza. |
| Se reportan **todas** las condiciones incumplidas | Una notificación de rechazo útil necesita todas las razones, no solo la primera. |
| `201` también al rechazar | Se creó un recurso; el rechazo es un resultado de negocio, no un error HTTP. |
| Validación estricta | Enteros estrictos, campos desconocidos prohibidos y un tope de 2^53 − 1, el mayor entero que JSON transmite sin pérdida. |
| Listado paginado (50 por defecto, máximo 100) | Sin paginar, cada consulta leería la tabla entera. |
| Ids enteros | Con una sola clave compartida, quien la tiene ya puede listar todo, así que un UUID no protege más; el entero da un orden determinista. |
| API key compartida | Ver [Autenticación](#autenticación). |
| Fechas en UTC con sufijo `Z` | SQLite descarta la zona horaria; se reaplica UTC al responder. |
| Python 3.12 en lugar de 3.11 | El enunciado admite 3.11+. |
| Versiones fijadas del boilerplate; `uvicorn` sin `[standard]`; piso `h11>=0.16.0` | Starlette 0.41.3 tiene 7 CVE publicados, y ninguno es alcanzable aquí. No se usan formularios, archivos estáticos, `HTTPEndpoint` ni `request.url`. El único alcanzable con la configuración por defecto (CVE-2026-48710, la redirección de barra final) se cierra con `redirect_slashes=False`. Los extras de uvicorn eran paquetes sin uso. |
| Errores `422` sin el valor recibido | El handler por defecto repetía ingreso y score en la respuesta, y con un `NaN` respondía 500. |
| Reglas del enunciado aplicadas literalmente, salvo en CARD | CARD suma un tope de cuota del 50 % y un cupo de 20.000.000. Ver [el hallazgo](#hallazgo-card-aprobaba-créditos-impagables). |

## Despliegue en AWS (Terraform)

[`infra/`](infra/) despliega el servicio en **una instancia EC2** de la VPC por defecto:

- Al arrancar, la instancia instala Docker, clona este repositorio, construye la imagen `runtime` y la levanta en el puerto 80 con un volumen para SQLite en su disco EBS cifrado. Por eso el repositorio tiene que ser **público** y el código tiene que estar subido en `git_ref` (por defecto `main`). La API tarda unos minutos en responder tras el `apply`.
- La API key se guarda cifrada en **SSM Parameter Store**, así que no aparece en el *user data*. El rol IAM de la instancia solo puede leer esa clave.
- No hay SSH ni Session Manager. El primer arranque se sigue con la salida de consola (output `boot_log`).
- La instancia exige IMDSv2 con límite de un salto, así que los contenedores no alcanzan sus credenciales.
- El security group solo deja entrar a las IPs de `allowed_cidrs`.
- La subred se elige entre las zonas que ofrecen el tipo de instancia, y una AMI nueva no reemplaza la instancia en el siguiente `apply`, lo que borraría SQLite.

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # allowed_cidrs y api_key (openssl rand -hex 32)
terraform init
terraform apply
curl "$(terraform output -raw api_url)/health"  # unos minutos después del apply
```

**Por qué EC2 y no ECS:** el servicio guarda SQLite en disco local, que admite un solo escritor. En Fargate el disco del contenedor es efímero y la alternativa, EFS, es un sistema de archivos de red sobre el que SQLite puede corromperse. ECS con RDS Postgres es el paso natural junto con la migración a Postgres (ver [Limitaciones](#limitaciones-y-qué-haría-con-más-tiempo)).

No se ejecutó contra una cuenta de AWS; está validado con `terraform fmt -check` y `terraform validate` (Terraform 1.17, provider AWS 6.x). Tiene dos límites conocidos: la API va por HTTP, sin TLS, y los datos se pierden si la instancia se reemplaza a propósito (no hay backups). `terraform.tfvars` y el estado de Terraform están en `.gitignore` porque contienen la clave.

## Limitaciones y qué haría con más tiempo

1. **TLS y autorización fina.** En el despliegue de ejemplo la API va por HTTP, así que la clave viaja en claro: falta un ALB con certificado (ACM) delante. Además hay una sola clave compartida; lo siguiente es una clave por cliente (u OAuth2 *client credentials*), rotación y autorización por objeto.
2. **Postgres en lugar de SQLite.** SQLite serializa las escrituras: con carga concurrente aparece `database is locked` y la petición termina en 500. Al migrar, reevaluar debe bloquear la fila (`SELECT … FOR UPDATE`) para que la decisión vigente siga siendo la de la última evaluación.
3. **Migraciones y backups.** Agregar Alembic y backups; hoy las tablas se crean al arrancar y no hay respaldo.
4. **Idempotencia y rate limiting** en `POST`, y un endpoint para consultar el historial de evaluaciones.
5. **Observabilidad:** logs estructurados, métricas y trazas.
6. **Lock file de dependencias** y actualizar a Starlette 1.x para cerrar los CVE sin depender de la configuración.
