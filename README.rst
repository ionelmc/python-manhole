===========================
       python-manhole
===========================

Manhole is a python daemon thread that will accept unix domain socket connections and present the
stacktraces for all threads and an interactive prompt.

Access to the socket is restricted to the application's effective user id or root.

Usage::

    import manhole
    manhole.install() # this will start the daemon thread

Now in a shell you can do either of these::

    netcat -U /tmp/manhole-1234
    socat - unix-connect:/tmp/manhole-1234
    socat readline unix-connect:/tmp/manhole-1234

Sample output::



Goals
=====

Design goals for this component:

* Have some common sense about security: uses unix domain sockets and checks who connects (via SO_PEERCRED)
* Be reliable and lightweight enough to leave it always active:

  * Work as a python daemon thread for normal operation
  * Do not mess with process's environment:

    * No custom signal handlers
    * No dup2 or fiddling with file descriptors

  * Be compatible with applications that fork (rebind the UDS on fork) - **TODO**
  * Be compatible with eventlet/stackless (provide alternative implementation without thread) - **TODO**
  * Wake the process as little as possible (async I/O until connection is made)


Notes
-----

* It will patch sys.__std\*__/sys.std\* when connection is establised.
* Windows not supported. It could (named pipes, localhost tcp etc) ...

Requirements
============

Not sure yet ... maybe Python 2.6 and 2.7. Check Travis:

.. image:: https://secure.travis-ci.org/ionelmc/python-manhole.png
    :alt: Build Status
    :target: http://travis-ci.org/ionelmc/python-manhole

.. image:: https://coveralls.io/repos/ionelmc/python-manhole/badge.png?branch=master
    :alt: Coverage Status
    :target: https://coveralls.io/r/ionelmc/python-manhole

