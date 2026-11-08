# Rebuild everything:   make setup && make all
# Other shapes:         make stl ARGS="--preset tall"   (then make preview slice)

PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
ARGS ?=

.PHONY: setup stl preview slice all

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

stl:
	$(PY) macbook_riser.py $(ARGS)

preview:
	$(PY) render_preview.py

slice:
	$(PY) tools/slice_bambu.py

all: stl preview slice
