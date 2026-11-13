.PHONY: install run migrate test lint check coverage seed docker-up docker-down

install:
	python -m pip install -r requirements-dev.txt
	pre-commit install

run:
	python manage.py runserver

migrate:
	python manage.py migrate

test:
	python manage.py test

lint:
	ruff check .

check: lint
	python manage.py makemigrations --check --dry-run
	python manage.py test

coverage:
	coverage run manage.py test
	coverage report

seed:
	python manage.py seed_test_data --reset

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
