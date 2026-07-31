.PHONY: up down logs psql seed ps

COMPOSE := docker compose -f infra/docker-compose.yml

up:           ## Levanta los 3 servicios (db, api, ui)
	$(COMPOSE) up -d --wait

down:         ## Baja los servicios y limpia huérfanos
	$(COMPOSE) down --remove-orphans

logs:         ## Sigue los logs de todos los servicios
	$(COMPOSE) logs -f

ps:           ## Estado de los servicios
	$(COMPOSE) ps

psql:         ## Consola psql contra rappi_cases
	$(COMPOSE) exec db psql -U rappi -d rappi_cases

seed:         ## Seed de los 150 casos originales desde el host
	python3 infra/db/seeds/seed_cases.py
