========
Overview
========

.. start-badges

.. list-table::
    :stub-columns: 1

    * - docs
      - |docs|
    * - tests
      - | |github-actions|
        | |coveralls| |codecov|
    * - package
      - | |version| |wheel| |supported-versions| |supported-implementations|
        | |commits-since|
.. |docs| image:: https://readthedocs.org/projects/python-manhole/badge/?style=flat
    :target: https://python-manhole.readthedocs.io/
    :alt: Documentation Status

.. |github-actions| image:: https://github.com/ionelmc/python-manhole/actions/workflows/github-actions.yml/badge.svg
    :alt: GitHub Actions Build Status
    :target: https://github.com/ionelmc/python-manhole/actions

.. |coveralls| image:: https://coveralls.io/repos/github/ionelmc/python-manhole/badge.svg?branch=master
    :alt: Coverage Status
    :target: https://coveralls.io/github/ionelmc/python-manhole?branch=master

.. |codecov| image:: https://codecov.io/gh/ionelmc/python-manhole/branch/master/graphs/badge.svg?branch=master
    :alt: Coverage Status
    :target: https://app.codecov.io/github/ionelmc/python-manhole

.. |version| image:: https://img.shields.io/pypi/v/manhole.svg
    :alt: PyPI Package latest release
    :target: https://pypi.org/project/manhole

.. |wheel| image:: https://img.shields.io/pypi/wheel/manhole.svg
    :alt: PyPI Wheel
    :target: https://pypi.org/project/manhole

.. |supported-versions| image:: https://img.shields.io/pypi/pyversions/manhole.svg
    :alt: Supported versions
    :target: https://pypi.org/project/manhole

.. |supported-implementations| image:: https://img.shields.io/pypi/implementation/manhole.svg
    :alt: Supported implementations
    :target: https://pypi.org/project/manhole

.. |commits-since| image:: https://img.shields.io/github/commits-since/ionelmc/python-manhole/v1.8.0.svg
    :alt: Commits since latest release
    :target: https://github.com/ionelmc/python-manhole/compare/v1.8.0...master



.. end-badges

Manhole is in-process service that will accept unix domain socket connections and present the
stacktraces for all threads and an interactive prompt. It can either work as a python daemon
thread waiting for connections at all times *or* a signal handler (stopping your application and
waiting for a connection).

Access to the socket is restricted to the application's effective user id or root.

This is just like Twisted's `manhole <http://twistedmatrix.com/documents/current/api/twisted.conch.manhole.html>`__.
It's simpler (no dependencies), it only runs on Unix domain sockets (in contrast to Twisted's manhole which
can run on telnet or ssh) and it integrates well with various types of applications.

:Documentation: http://python-manhole.readthedocs.org/en/latest/

Usage
=====

Install it::

    pip install manhole

You can put this in your django settings, wsgi app file, some module that's always imported early etc:

.. code-block:: python

    import manhole
    manhole.install() # this will start the daemon thread

    # and now you start your app, eg: server.serve_forever()

Now in a shell you can do either of these::

    netcat -U /tmp/manhole-1234
    socat - unix-connect:/tmp/manhole-1234
    socat readline unix-connect:/tmp/manhole-1234

Socat with readline is best (history, editing etc).
If your socat doesn't have readline try `this <https://launchpad.net/~ionel-mc/+archive/ubuntu/socat>`_.

Sample output::

    $ nc -U /tmp/manhole-1234

    Python 2.7.3 (default, Apr 10 2013, 06:20:15)
    [GCC 4.6.3] on linux2
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> dir()
    ['__builtins__', 'dump_stacktraces', 'os', 'socket', 'sys', 'traceback']
    >>> print 'foobar'
    foobar

Alternative client
------------------

There's a new experimental ``manhole-cli`` bin since 1.1.0, that emulates ``socat``::

    usage: manhole-cli [-h] [-t TIMEOUT] [-1 | -2 | -s SIGNAL] PID

    Connect to a manhole.

    positional arguments:
      PID                   A numerical process id, or a path in the form:
                            /tmp/manhole-1234

    optional arguments:
      -h, --help            show this help message and exit
      -t TIMEOUT, --timeout TIMEOUT
                            Timeout to use. Default: 1 seconds.
      -1, -USR1             Send USR1 (10) to the process before connecting.
      -2, -USR2             Send USR2 (12) to the process before connecting.
      -s SIGNAL, --signal SIGNAL
                            Send the given SIGNAL to the process before
                            connecting.

.. end-badges


Features
========

* Uses unix domain sockets, only root or same effective user can connect.
* Can run the connection in a thread or in a signal handler (see ``oneshot_on`` option).
* Can start the thread listening for connections from a signal handler (see ``activate_on`` option)
* Compatible with apps that fork, reinstalls the Manhole thread after fork - had to monkeypatch os.fork/os.forkpty for
  this.
* Compatible with gevent and eventlet with some limitations - you need to either:

  * Use ``oneshot_on``, *or*
  * Disable thread monkeypatching (eg: ``gevent.monkey.patch_all(thread=False)``, ``eventlet.monkey_patch(thread=False)``

  Note: on eventlet `you might <https://github.com/eventlet/eventlet/issues/401>`_ need to setup the hub first to prevent
  circular import problems:

  .. sourcecode:: python

    import eventlet
    eventlet.hubs.get_hub()  # do this first
    eventlet.monkey_patch(thread=False)

* The thread is compatible with apps that use signalfd (will mask all signals for the Manhole threads).

Options
-------

.. code-block:: python

    manhole.install(
        verbose=True,
        verbose_destination=2,
        patch_fork=True,
        activate_on=None,
        oneshot_on=None,
        sigmask=manhole.ALL_SIGNALS,
        socket_path=None,
        reinstall_delay=0.5,
        locals=None,
        strict=True,
    )

* ``verbose`` - Set it to ``False`` to squelch the logging.
* ``verbose_destination`` - Destination for verbose messages. Set it to a file descriptor or handle. Default is
  unbuffered stderr (stderr ``2`` file descriptor).
* ``patch_fork`` - Set it to ``False`` if you don't want your ``os.fork`` and ``os.forkpy`` monkeypatched
* ``activate_on`` - Set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you want the Manhole thread
  to start when this signal is sent. This is desirable in case you don't want the thread active all the time.
* ``thread`` - Set to ``True`` to start the always-on ManholeThread. Default: ``True``.
  Automatically switched to ``False`` if ``oneshot_on`` or ``activate_on`` are used.
* ``oneshot_on`` - Set to ``"USR1"``, ``"USR2"`` or some other signal name, or a number if you want the Manhole to
  listen for connection in the signal handler. This is desireable in case you don't want threads at all.
* ``sigmask`` - Will set the signal mask to the given list (using ``signalfd.sigprocmask``). No action is done if
  ``signalfd`` is not importable. **NOTE**: This is done so that the Manhole thread doesn't *steal* any signals;
  Normally that is fine because Python will force all the signal handling to be run in the main thread but signalfd
  doesn't.
* ``socket_path`` - Use a specific path for the unix domain socket (instead of ``/tmp/manhole-<pid>``). This disables
  ``patch_fork`` as children cannot reuse the same path.
* ``reinstall_delay`` - Delay the unix domain socket creation *reinstall_delay* seconds. This alleviates
  cleanup failures when using fork+exec patterns.
* ``locals`` - Names to add to manhole interactive shell locals.
* ``daemon_connection`` - The connection thread is daemonic (dies on app exit). Default: ``False``.
* ``redirect_stderr`` - Redirect output from stderr to manhole console. Default: ``True``.
* ``strict`` - If ``True`` then ``AlreadyInstalled`` will be raised when attempting to install manhole twice.
  Default: ``True``.

Environment variable installation
---------------------------------

Manhole can be installed via the ``PYTHONMANHOLE`` environment variable.

This::

    PYTHONMANHOLE='' python yourapp.py

Is equivalent to having this in ``yourapp.py``::

    import manhole
    manhole.install()

Any extra text in the environment variable is passed to ``manhole.install()``. Example::

    PYTHONMANHOLE='oneshot_on="USR2"' python yourapp.py

What happens when you actually connect to the socket
----------------------------------------------------

1. Credentials are checked (if it's same user or root)
2. ``sys.__std*__``/``sys.std*`` are redirected to the UDS
3. Stacktraces for each thread are written to the UDS
4. REPL is started so you can fiddle with the process

Known issues
============

* Using threads and file handle (not raw file descriptor) ``verbose_destination`` can cause deadlocks. See bug reports:
  `PyPy <https://foss.heptapod.net/pypy/pypy/-/issues/1895>`_ and `Python 3.4 <http://bugs.python.org/issue22697>`_.

SIGTERM and socket cleanup
--------------------------

By default Python doesn't call the ``atexit`` callbacks with the default SIGTERM handling. This makes manhole leave
stray socket files around. If this is undesirable you should install a custom SIGTERM handler so ``atexit`` is
properly invoked.

Example:

.. code-block:: python

    import signal
    import sys

    def handle_sigterm(signo, frame):
        sys.exit(128 + signo)  # this will raise SystemExit and cause atexit to be called

    signal.signal(signal.SIGTERM, handle_sigterm)

Using Manhole with uWSGI
------------------------

Because uWSGI overrides signal handling Manhole is a bit more tricky to setup. One way is to use "uWSGI signals" (not
the POSIX signals) and have the workers check a file for the pid you want to open the Manhole in.

Stick something this in your WSGI application file:

.. sourcecode:: python

    from __future__ import print_function
    import sys
    import os
    import manhole

    stack_dump_file = '/tmp/manhole-pid'
    uwsgi_signal_number = 17

    try:
        import uwsgi

        if not os.path.exists(stack_dump_file):
            open(stack_dump_file, 'w')

        def open_manhole(dummy_signum):
            with open(stack_dump_file, 'r') as fh:
                pid = fh.read().strip()
                if pid == str(os.getpid()):
                    inst = manhole.install(strict=False, thread=False)
                    inst.handle_oneshot(dummy_signum, dummy_signum)

        uwsgi.register_signal(uwsgi_signal_number, 'workers', open_manhole)
        uwsgi.add_file_monitor(uwsgi_signal_number, stack_dump_file)

        print("Listening for stack mahole requests via %r" % (stack_dump_file,), file=sys.stderr)
    except ImportError:
        print("Not running under uwsgi; unable to configure manhole trigger", file=sys.stderr)
    except IOError:
        print("IOError creating manhole trigger %r" % (stack_dump_file,), file=sys.stderr)


    # somewhere bellow you'd have something like
    from django.core.wsgi import get_wsgi_application
    application = get_wsgi_application()
    # or
    def application(environ, start_response):
        start_response('200 OK', [('Content-Type', 'text/plain'), ('Content-Length', '2')])
        yield b'OK'

To open the Manhole just run `echo 1234 > /tmp/manhole-pid` and then `manhole-cli 1234`.

Requirements
============

:OS: Linux, OS X
:Runtime: Python 2.7, 3.4, 3.5, 3.6 or PyPy

Similar projects
================

* Twisted's `manhole <http://twistedmatrix.com/documents/current/api/twisted.conch.manhole.html>`__ - it has colors and
  server-side history.
* `wsgi-shell <https://github.com/GrahamDumpleton/wsgi-shell>`_ - spawns a thread.
* `pyrasite <https://github.com/lmacken/pyrasite>`_ - uses gdb to inject code.
* `pydbattach <https://github.com/albertz/pydbattach>`_ - uses gdb to inject code.
* `pystuck <https://github.com/alonho/pystuck>`_ - very similar, uses `rpyc <https://github.com/tomerfiliba/rpyc>`_ for
  communication.
* `pyringe <https://github.com/google/pyringe>`_ - uses gdb to inject code, more reliable, but relies on `dbg` python
  builds unfortunatelly.
* `pdb-clone <https://pypi.python.org/pypi/pdb-clone>`_ - uses gdb to inject code, with a `different strategy
  <https://code.google.com/p/pdb-clone/wiki/RemoteDebugging>`_.
