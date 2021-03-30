
Changelog
=========

dev
* Simplify connection closing code
* Graceful connection shutdown in ``manhole-cli``

1.7.0 (2021-03-22)
------------------

* Fixed memory leak via ``sys.last_type``, ``sys.last_value``, ``sys.last_traceback``.
  Contributed by Anton Ryzhov in `#59 <https://github.com/ionelmc/python-manhole/pull/59>`_.
* Fixed a bunch of double-close bugs and simplified stream handler code.
  Contributed by Anton Ryzhov in `#58 <https://github.com/ionelmc/python-manhole/pull/58>`_.
* Loosen up ``pid`` argument parsing in ``manhole-cli`` to allow using paths with any prefix
  (not just ``/tmp``).

1.6.0 (2019-01-19)
------------------

* Testing improvements (changed some skips to xfail, added osx in Travis).
* Fixed long standing Python 2.7 bug where ``sys.getfilesystemencoding()`` would be broken after installing a threaded
  manhole. See `#51 <https://github.com/ionelmc/python-manhole/issues/51>`_.
* Dropped support for Python 2.6, 3.3 and 3.4.
* Fixed handling when ``socket.setdefaulttimeout()`` is used.
  Contributed by "honnix" in `#53 <https://github.com/ionelmc/python-manhole/pull/53>`_.
* Fixed some typos. Contributed by Jesús Cea in `#43 <https://github.com/ionelmc/python-manhole/pull/43>`_.
* Fixed handling in ``manhole-cli`` so that timeout is actually seconds and not milliseconds.
  Contributed by Nir Soffer in `#45 <https://github.com/ionelmc/python-manhole/pull/45>`_.
* Cleaned up useless polling options in ``manhole-cli``.
  Contributed by Nir Soffer in `#46 <https://github.com/ionelmc/python-manhole/pull/46>`_.
* Documented and implemented a solution for using Manhole with Eventlet.
  See `#49 <https://github.com/ionelmc/python-manhole/issues/49>`_.

1.5.0 (2017-08-31)
------------------

* Added two string aliases for ``connection_handler`` option. Now you can conveniently use ``connection_handler="exec"``.
* Improved ``handle_connection_exec``. It now has a clean way to exit (``exit()``) and properly closes the socket.

1.4.0 (2017-08-29)
------------------

* Added the ``connection_handler`` install option. Default value is ``manhole.handle_connection_repl``, and alternate
  ``manhole.handle_connection_exec`` is provided (very simple: no output redirection, no stacktrace dumping).
* Dropped Python 3.2 from the test grid. It may work but it's a huge pain to support (pip/pytest don't support it anymore).
* Added Python 3.5 and 3.6 in the test grid.
* Fixed issues with piping to ``manhole-cli``. Now ``echo foobar | manhole-cli`` will wait 1 second for output from manhole
  (you can customize this with the ``--timeout`` option).
* Fixed issues with newer PyPy (caused by gevent/eventlet socket unwrapping).

1.3.0 (2015-09-03)
------------------

* Allowed Manhole to be configured without any thread or activation (in case you want to manually activate).
* Added an example and tests for using Manhole with uWSGi.
* Fixed error handling in ``manhole-cli`` on Python 3 (exc vars don't leak anymore).
* Fixed support for running in gevent/eventlet-using apps on Python 3 (now that they support Python 3).
* Allowed reinstalling the manhole (in non-``strict`` mode). Previous install is undone.

1.2.0 (2015-07-06)
------------------

* Changed ``manhole-cli``:

  * Won't spam the terminal with errors if socket file doesn't exist.
  * Allowed sending any signal (new ``--signal`` argument).
  * Fixed some validation issues for the ``PID`` argument.

1.1.0 (2015-06-06)
------------------

* Added support for installing the manhole via the ``PYTHONMANHOLE`` environment variable.
* Added a ``strict`` install option. Set it to false to avoid getting the ``AlreadyInstalled`` exception.
* Added a ``manhole-cli`` script that emulates ``socat readline unix-connect:/tmp/manhole-1234``.

1.0.0 (2014-10-13)
------------------

* Added ``socket_path`` install option (contributed by `Nir Soffer`_).
* Added ``reinstall_delay`` install option.
* Added ``locals`` install option (contributed by `Nir Soffer`_).
* Added ``redirect_stderr`` install option (contributed by `Nir Soffer`_).
* Lots of internals cleanup (contributed by `Nir Soffer`_).

0.6.2 (2014-04-28)
------------------

* Fix OS X regression.

0.6.1 (2014-04-28)
------------------

* Support for OS X (contributed by `Saulius Menkevičius`_).

.. _Saulius Menkevičius: https://github.com/razzmatazz
.. _Nir Soffer: https://github.com/nirs
