CC = gcc
CPPFLAGS = -Iinclude
CFLAGS = -std=c11 -Wall -Wextra -Wpedantic -Werror -O2
LDFLAGS =
CORE = src/structures.c src/clinic.c src/reports.c src/persistence.c
OBJECTS = $(CORE:src/%.c=build/%.o)
.PHONY: all test sanitize clean
all: build/clinic
build:
	mkdir -p build
build/%.o: src/%.c include/clinic.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@
build/clinic: $(OBJECTS) build/main.o
	$(CC) $(LDFLAGS) $^ -o $@
build/test_clinic: tests/test_clinic.c $(OBJECTS) include/clinic.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) tests/test_clinic.c $(OBJECTS) -o $@
test: build/clinic build/test_clinic
	./build/test_clinic
	sh tests/cli.sh
build/test_sanitize: tests/test_clinic.c $(CORE) include/clinic.h | build
	$(CC) $(CPPFLAGS) -std=c11 -Wall -Wextra -Wpedantic -Werror -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer tests/test_clinic.c $(CORE) -o $@
build/clinic_sanitize: src/main.c $(CORE) include/clinic.h | build
	$(CC) $(CPPFLAGS) -std=c11 -Wall -Wextra -Wpedantic -Werror -g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer src/main.c $(CORE) -o $@
sanitize: build/test_sanitize build/clinic_sanitize
	ASAN_OPTIONS=detect_leaks=1 ./build/test_sanitize
	ASAN_OPTIONS=detect_leaks=1 CLINIC_BIN=./build/clinic_sanitize sh tests/cli.sh
clean:
	rm -rf build
-include $(wildcard build/*.d)
