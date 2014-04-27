.bootstrap:
	virtualenv .bootstrap
	.bootstrap/bin/pip install jinja2

configure: .bootstrap tox.ini .travis.yml
	.bootstrap/bin/python configure.py

test: configure
	tox

all: test

clean:
    rm tox.ini .travis.yml