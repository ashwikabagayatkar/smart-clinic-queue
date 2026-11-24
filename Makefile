# Native mingw32-make (cmd.exe) and Linux GNU Make share the same Python builder.
# Strict C11/UTF-8/MinGW flags and .exe/.dll naming live in tools/build.py.
.DEFAULT_GOAL := all
CC = gcc
export CC
PYTHON ?= python3
EXE =
SHARED_EXT = so
ifeq ($(OS),Windows_NT)
SHELL := cmd.exe
.SHELLFLAGS := /d /c
PYTHON = tools\python.bat
EXE = .exe
SHARED_EXT = dll
endif
CORE = src/structures.c src/clinic.c src/reports.c src/persistence.c
HEADERS = include/clinic.h include/bridge.h
.PHONY: all cli web test api-test test-posix sanitize clean run
all: cli web
cli:
	$(PYTHON) tools/build.py cli
web:
	$(PYTHON) tools/build.py web
# Aliases retain explicit artifact targets, but use the same build fingerprint.
.PHONY: build/clinic$(EXE) build/clinic_core.$(SHARED_EXT) build/test_clinic$(EXE) build/test_bridge$(EXE)
build/clinic$(EXE): cli
build/clinic_core.$(SHARED_EXT): web
build/test_clinic$(EXE):
	$(PYTHON) tools/build.py test-core
build/test_bridge$(EXE):
	$(PYTHON) tools/build.py test-bridge
run: all
	$(PYTHON) tools/server.py
test:
	$(PYTHON) tools/test.py
api-test: web
	$(PYTHON) -m unittest discover -s tests -p "test_api.py" -v
test-posix: cli
	$(PYTHON) tools/manage.py posix-test
ifeq ($(OS),Windows_NT)
sanitize:
	$(PYTHON) tools/manage.py sanitize
else
SANFLAGS = -std=c11 -Wall -Wextra -Wpedantic -Werror -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer -Iinclude
build:
	$(PYTHON) tools/manage.py mkdir build
build/test_sanitize: tests/test_clinic.c $(CORE) $(HEADERS) | build
	"$(CC)" $(SANFLAGS) tests/test_clinic.c $(CORE) -o "$@"
build/clinic_sanitize: src/main.c $(CORE) $(HEADERS) | build
	"$(CC)" $(SANFLAGS) src/main.c $(CORE) -o "$@"
build/test_bridge_sanitize: tests/test_bridge.c $(CORE) src/bridge.c $(HEADERS) | build
	"$(CC)" $(SANFLAGS) tests/test_bridge.c $(CORE) src/bridge.c -o "$@"
sanitize: build/test_sanitize build/clinic_sanitize build/test_bridge_sanitize
	$(PYTHON) tools/manage.py sanitize
endif
clean:
	$(PYTHON) tools/manage.py clean
