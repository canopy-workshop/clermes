.PHONY: test install install-bin honcho-up lint

test:
	./tests/run-tests.sh

install:
	pip install -e .

install-bin:
	@mkdir -p $$HOME/.local/bin
	@ln -sf $(CURDIR)/bin/clermes $$HOME/.local/bin/clermes
	@echo "Symlinked $(CURDIR)/bin/clermes to $$HOME/.local/bin/clermes"
	@command -v clermes >/dev/null || echo "Warning: add ~/.local/bin to PATH"

honcho-up:
	cd honcho && docker compose up -d

lint:
	python -m py_compile clermes/*.py
