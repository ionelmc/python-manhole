.PHONY: test all

.bootstrap:
	virtualenv .bootstrap
	.bootstrap/bin/pip install jinja2

tox.ini: .bootstrap
	.bootstrap/bin/python confenvs.py

test: tox.ini
	tox

clean:
	rm -f tox.ini .travis.yml
