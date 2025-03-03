SHELL = bash

all: install_dev isort isort_check lint test
check: install_dev isort_check lint test clean

install_dev:
	@pip install -e .[dev] >/dev/null 2>&1

isort:
	@isort -s venv -s venv_py -s .tox -s tools -rc --atomic .

isort_check:
	@isort -rc -s venv -s venv_py -s .tox -s tools -c .

lint:
	@flake8

test:
	@tox

clean:
	@rm -rf .pytest_cache .tox habitat.egg-info
	@rm -rf tests/*.pyc tests/__pycache__ build dist

package:
	@python3 setup.py sdist
	@pex -P core -r requirements.txt -f dist -e core.main -o hab.pex --python-shebang='python3' --sh-boot

.IGNORE: install_dev
.PHONY: all check install_dev isort isort_check lint test
