.PHONY: install run test test-mobile clean

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

run:
	./start.sh

test:
	python3 -m unittest discover -s tests -v

test-mobile:
	cd mobile && flutter test

clean:
	rm -rf .venv __pycache__ */__pycache__ .pytest_cache
	rm -f finance.db finance.db-wal finance.db-shm
