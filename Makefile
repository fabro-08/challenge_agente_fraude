.PHONY: up down logs psql seed ps

COMPOSE := docker compose -f infra/docker-compose.yml
PSQL := $(COMPOSE) exec -T db psql -U rappi -d rappi_cases

up:           ## Levanta DB+API+UI y garantiza el seed (datos cargados)
	$(COMPOSE) up -d --wait
	$(MAKE) seed

down:         ## Baja los servicios y limpia huérfanos
	$(COMPOSE) down --remove-orphans

logs:         ## Sigue los logs de todos los servicios
	$(COMPOSE) logs -f

ps:           ## Estado de los servicios
	$(COMPOSE) ps

psql:         ## Consola psql contra rappi_cases
	$(COMPOSE) exec db psql -U rappi -d rappi_cases

seed:         ## Garantiza esquema + datos (idempotente: no duplica si ya hay casos)
	@echo "--> Aplicando esquema (idempotente)..."
	@$(PSQL) -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/01_create_tables.sql
	@$(PSQL) -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/02_add_features.sql
	@$(PSQL) -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/05_resolution_case.sql
	@$(PSQL) -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/06_batch_runs.sql
	@count=$$($(PSQL) -tAc "SELECT COUNT(*) FROM cases;" | tr -d ' '); \
	if [ "$$count" = "0" ]; then \
		echo "--> cases vacía: sembrando 09_seed_completo.sql..."; \
		$(PSQL) -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/09_seed_completo.sql; \
	else \
		echo "--> ya hay $$count casos: seed omitido (idempotente)."; \
	fi
