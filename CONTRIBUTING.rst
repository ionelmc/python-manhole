============
Contributing
============

Reporting bugs
==============

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Sending feedback
================

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

Fixing bugs or adding features
==============================

Not many rules for sending changes:

* Just make the pull request.
* Try to run as many tests as possible if your test environment is different
  than `travis <https://travis-ci.org/ionelmc/python-manhole>`_ (it should be
  some sort of Ubuntu 12.04):

    Install `tox <https://testrun.org/tox/latest/>`_ and run `tox` to get the all tests running.

    There are very many test configurations - to only run one, find out whatever test you want to run with::

        tox --listenvs

    And then, e.g.::

        tox -e 2.7

Technical details about the tests
---------------------------------

The test matrix for tox and travis is generated with ``bootstrap.py``. If you want to regenerate it::

    ./bootstrap.py
