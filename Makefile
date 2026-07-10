PREFIX ?= $(HOME)/.local

.PHONY: install man test clean

install:
	pip install -e .

man:
	mkdir -p $(PREFIX)/share/man/man1
	install -m 644 man/agent-sessions.1 $(PREFIX)/share/man/man1/agent-sessions.1
	@echo "Installed man page to $(PREFIX)/share/man/man1/agent-sessions.1"
	@echo "Ensure $(PREFIX)/share/man is on MANPATH (it usually already is)."

test:
	python3 -m pytest -q

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache
