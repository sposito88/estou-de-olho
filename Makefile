# Atalhos para desenvolvimento. `make ajuda` lista tudo.
PY ?= .venv/bin/python
DEMO_DB ?= sqlite:///data/demo.db

.PHONY: ajuda instalar demo api web dev testes verificar limpar-demo

ajuda:
	@echo "make instalar    - cria .venv, instala Python e o front (npm)"
	@echo "make demo        - cria data/demo.db com dados FICTÍCIOS (sem baixar nada)"
	@echo "make api         - sobe a API em http://localhost:8000 usando o banco de exemplo"
	@echo "make web         - sobe o front em http://localhost:5173 (em outro terminal)"
	@echo "make dev         - demo + instruções para api e web"
	@echo "make testes      - testes do Python"
	@echo "make verificar   - testes + checagem de tipos e build do front (o mesmo que o CI roda)"

instalar:
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt
	cd web && npm ci

demo:
	DATABASE_URL=$(DEMO_DB) $(PY) -m civic.demo

limpar-demo:
	rm -f data/demo.db data/demo.db-wal data/demo.db-shm

api:
	DATABASE_URL=$(DEMO_DB) $(PY) -m uvicorn civic.api:app --reload --port 8000

web:
	cd web && VITE_API_URL=http://localhost:8000 npm run dev

dev: demo
	@echo ""
	@echo "Banco de exemplo pronto. Agora, em dois terminais:"
	@echo "  make api"
	@echo "  make web"
	@echo "e abra http://localhost:5173/cidade/PE/Vila%20Exemplo"

testes:
	DATABASE_URL=sqlite:// $(PY) -m pytest -q -p no:cacheprovider -o addopts=

verificar: testes
	cd web && npx tsc --noEmit && npm run build
